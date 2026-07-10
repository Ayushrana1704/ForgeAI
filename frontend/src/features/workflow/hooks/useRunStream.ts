/**
 * Hook: open an SSE stream for a run and accumulate events in workflowStore.
 *
 * The backend supports COMPLETED runs via synthetic event replay, so we
 * always connect — callers do NOT need to guard on run status.
 *
 * React StrictMode double-invokes effects:
 *   mount → effect 1 starts stream → cleanup aborts stream 1 →
 *   mount → effect 2 starts fresh stream (startStream clears stale events)
 * This is intentional: the second invocation gets a clean replay.
 *
 * The AbortController returned by workflowApi.streamRun is cancelled on
 * unmount, which prevents orphaned fetch readers from consuming data after
 * the component is gone.
 */
import { useEffect, useRef } from "react";
import { workflowApi } from "@/features/workflow/api/workflowApi";
import { useWorkflowStore } from "@/features/workflow/store/workflowStore";
import type { WorkflowEvent } from "@/shared/types";

export function useRunStream(
  runId: string | undefined,
  onComplete?: (event: WorkflowEvent) => void,
) {
  const { startStream, addEvent, endStream } = useWorkflowStore();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!runId) return;

    // Clear any stale events from a previous stream and mark streaming=true
    startStream(runId);

    abortRef.current = workflowApi.streamRun(runId, {
      onEvent: (event) => {
        addEvent(event);
        if (
          event.type === "run_completed" ||
          event.type === "run_failed" ||
          event.type === "run_cancelled"
        ) {
          onComplete?.(event);
        }
      },
      onComplete: () => endStream(),
      onError: (err) => {
        console.error("[SSE] stream error:", err);
        endStream();
      },
    });

    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
      endStream();
    };
    // startStream / addEvent / endStream are stable Zustand actions
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);
}
