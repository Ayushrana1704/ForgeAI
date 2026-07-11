/**
 * Workflow API — wraps all /runs endpoints plus SSE streaming.
 *
 * REST calls use the shared axios instance (auth + error interceptors).
 * SSE uses raw fetch() because EventSource does not support custom headers
 * and axios does not support streaming responses.
 */
import { api } from "@/shared/lib/axios";
import { useAuthStore } from "@/features/auth/store/authStore";
import type {
  RunCreateResponse,
  RunDetail,
  RunStatusPoll,
  RunArtifactsResponse,
  WorkflowEvent,
} from "@/shared/types";

const API_BASE =
  import.meta.env.PROD
    ? import.meta.env.VITE_API_BASE_URL
    : "/api/v1";

// ── REST endpoints ─────────────────────────────────────────────────────────

/**
 * POST /projects/{projectId}/run — trigger a new AI pipeline run.
 *
 * timeout: 0 = no limit.  The backend executes the full 9-agent pipeline
 * synchronously before returning, which may take several minutes with real
 * LLM calls.  The default axios 30 s timeout would cut the request off.
 */
async function triggerRun(projectId: string): Promise<RunCreateResponse> {
  const { data } = await api.post<RunCreateResponse>(
    `/projects/${projectId}/run`,
    null,
    { timeout: 0 },
  );
  return data;
}

/** GET /runs/{runId} — full run detail including artifacts */
async function getRun(runId: string): Promise<RunDetail> {
  const { data } = await api.get<RunDetail>(`/runs/${runId}`);
  return data;
}

/** GET /runs/{runId}/status — lightweight status poll */
async function getRunStatus(runId: string): Promise<RunStatusPoll> {
  const { data } = await api.get<RunStatusPoll>(`/runs/${runId}/status`);
  return data;
}

/** GET /runs/{runId}/artifacts — artifact list for a run */
async function getRunArtifacts(runId: string): Promise<RunArtifactsResponse> {
  const { data } = await api.get<RunArtifactsResponse>(`/runs/${runId}/artifacts`);
  return data;
}

export interface CancelRunResponse {
  run_id: string;
  status: string;
  message: string;
}

/**
 * POST /runs/{runId}/cancel — request cancellation of a QUEUED or RUNNING run.
 *
 * Throws AxiosError with status 409 if the run is already terminal.
 */
async function cancelRun(runId: string): Promise<CancelRunResponse> {
  const { data } = await api.post<CancelRunResponse>(`/runs/${runId}/cancel`);
  return data;
}

// ── SSE streaming ──────────────────────────────────────────────────────────

export interface StreamHandlers {
  onEvent: (event: WorkflowEvent) => void;
  onComplete: () => void;
  onError: (err: Error) => void;
}

/**
 * Open an SSE connection to GET /runs/{runId}/stream.
 *
 * Uses fetch() with ReadableStream so we can attach the Authorization header
 * (native EventSource doesn't support custom headers).
 *
 * Returns an AbortController so the caller can cancel the stream.
 */
function streamRun(runId: string, handlers: StreamHandlers): AbortController {
  const controller = new AbortController();

  (async () => {
    const token = useAuthStore.getState().accessToken;
    let response: Response;

    try {
      response = await fetch(`${API_BASE}/runs/${runId}/stream`, {
        headers: {
          Authorization: token ? `Bearer ${token}` : "",
          Accept: "text/event-stream",
        },
        signal: controller.signal,
      });
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      handlers.onError(err instanceof Error ? err : new Error(String(err)));
      return;
    }

    if (!response.ok) {
      if (response.status === 401) {
        useAuthStore.getState().logout();
        window.location.replace("/login");
        return;
      }
      const statusText =
        response.status === 403
          ? "Access denied (403)"
          : response.status === 404
          ? "Run not found (404)"
          : `Stream responded ${response.status}`;
      handlers.onError(new Error(statusText));
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      handlers.onError(new Error("Response body is not readable"));
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Double-newline separates SSE frames
        const frames = buffer.split("\n\n");
        // Last element may be incomplete; keep it in the buffer
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          if (!frame.trim()) continue;

          let dataLine = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("data: ")) {
              dataLine = line.slice(6);
            }
          }

          if (!dataLine) continue;

          try {
            const event = JSON.parse(dataLine) as WorkflowEvent;
            handlers.onEvent(event);

            if (
              event.type === "run_completed" ||
              event.type === "run_failed" ||
              event.type === "run_cancelled"
            ) {
              handlers.onComplete();
              return;
            }
          } catch {
            // Ignore malformed frames
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      handlers.onError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      reader.releaseLock();
    }

    // Stream ended without a terminal event (server closed cleanly)
    handlers.onComplete();
  })();

  return controller;
}

// ── Download helpers ───────────────────────────────────────────────────────

/**
 * GET /runs/{runId}/artifacts/{artifactId}/download
 *
 * Returns the artifact content as a Blob suitable for triggering a browser
 * file-save.
 */


async function downloadArtifact(
  runId: string,
  artifactId: string
): Promise<Blob> {
  const { data } = await api.get(
    `/runs/${runId}/artifacts/${artifactId}/download`,
    {
      responseType: "blob",
    }
  );

  return data;
}
/**
 * GET /runs/{runId}/download
 *
 * Returns a ZIP Blob containing all artifacts for the run.
 */
async function downloadRunZip(runId: string): Promise<Blob> {
  const { data } = await api.get(
    `/runs/${runId}/download`,
    {
      responseType: "blob",
    }
  );

  return data;
}

/** Trigger a browser file-save from a Blob without leaving the page. */
function saveBlobAs(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const workflowApi = {
  triggerRun,
  getRun,
  getRunStatus,
  getRunArtifacts,
  cancelRun,
  streamRun,
  downloadArtifact,
  downloadRunZip,
  saveBlobAs,
};
