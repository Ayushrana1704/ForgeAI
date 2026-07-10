import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { useRun } from "@/features/workflow/hooks/useRun";
import { useRunStream } from "@/features/workflow/hooks/useRunStream";
import { useWorkflowStore } from "@/features/workflow/store/workflowStore";
import { workflowApi } from "@/features/workflow/api/workflowApi";
import { Badge } from "@/shared/components/ui/Badge";
import { Button } from "@/shared/components/ui/Button";
import { Spinner } from "@/shared/components/ui/Spinner";
import { formatDateTime } from "@/shared/lib/utils";
import type { Artifact } from "@/shared/types";

// ── Agent ordering / labels ────────────────────────────────────────────────

const AGENT_LABELS: Record<string, string> = {
  requirements_analyst: "Requirements Analyst",
  software_architect: "Software Architect",
  task_planner: "Task Planner",
  database_designer: "Database Designer",
  backend_generator: "Backend Generator",
  frontend_generator: "Frontend Generator",
  reviewer: "Reviewer",
  refiner: "Refiner",
  artifact_packager: "Artifact Packager",
};

const AGENT_ORDER = Object.keys(AGENT_LABELS);
const TOTAL_AGENTS = AGENT_ORDER.length;

// ── Formatting helpers ─────────────────────────────────────────────────────

function artifactLabel(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function filenameFromPath(path: string): string {
  return path.split("/").pop() ?? path;
}

// ── Markdown Preview Modal ─────────────────────────────────────────────────

interface PreviewModalProps {
  artifact: Artifact;
  runId: string;
  onClose: () => void;
}

function PreviewModal({ artifact, runId, onClose }: PreviewModalProps) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const blob = await workflowApi.downloadArtifact(runId, artifact.id);
        const text = await blob.text();
        if (!cancelled) setContent(text);
      } catch (err) {
        if (!cancelled) setError("Failed to load content.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [runId, artifact.id]);

  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleDownload = async () => {
    try {
      const blob = await workflowApi.downloadArtifact(runId, artifact.id);
      workflowApi.saveBlobAs(blob, filenameFromPath(artifact.file_path));
    } catch {
      // Silently ignore — user can retry
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl flex flex-col w-full max-w-3xl max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="min-w-0">
            <p className="font-semibold text-gray-900 truncate">
              {artifactLabel(artifact.artifact_type)}
            </p>
            <p className="text-xs text-gray-400 font-mono truncate">{artifact.file_path}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 ml-4">
            <Button variant="secondary" size="sm" onClick={handleDownload}>
              Download
            </Button>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors p-1"
              aria-label="Close preview"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-5">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" className="text-brand-500" />
            </div>
          )}
          {error && (
            <p className="text-red-600 text-sm text-center py-8">{error}</p>
          )}
          {content !== null && !loading && (
            <pre className="text-xs font-mono text-gray-700 whitespace-pre-wrap leading-relaxed">
              {content}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function ProgressBar({ pct, cancelled }: { pct: number; cancelled?: boolean }) {
  return (
    <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
      <div
        className={`h-2 rounded-full transition-all duration-500 ${
          cancelled ? "bg-gray-400" : "bg-brand-500"
        }`}
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}

function AgentTimeline({
  completedAgents,
  currentAgent,
  cancelled,
}: {
  completedAgents: string[];
  currentAgent: string | null;
  cancelled?: boolean;
}) {
  const completedSet = new Set(completedAgents);
  return (
    <ol className="space-y-2">
      {AGENT_ORDER.map((key) => {
        const isDone = completedSet.has(key);
        const isActive = currentAgent === key && !isDone && !cancelled;
        return (
          <li key={key} className="flex items-center gap-3 text-sm">
            <span className="w-5 flex-shrink-0 flex items-center justify-center">
              {isDone ? (
                <span className="text-green-500 font-bold">&#10003;</span>
              ) : isActive ? (
                <Spinner size="sm" className="text-brand-500" />
              ) : cancelled && !isDone ? (
                <span className="w-3 h-3 rounded-full border border-gray-200 bg-gray-100 block" />
              ) : (
                <span className="w-3 h-3 rounded-full border border-gray-200 bg-gray-50 block" />
              )}
            </span>
            <span
              className={
                isDone
                  ? "text-gray-700"
                  : isActive
                  ? "text-brand-700 font-medium"
                  : "text-gray-400"
              }
            >
              {AGENT_LABELS[key] ?? key}
            </span>
            {isActive && (
              <span className="text-xs text-brand-400 animate-pulse">running…</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

interface ArtifactListProps {
  artifacts: Artifact[];
  runId: string;
}

function ArtifactList({ artifacts, runId }: ArtifactListProps) {
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);

  const handleDownloadOne = useCallback(async (artifact: Artifact) => {
    setDownloadingId(artifact.id);
    try {
      const blob = await workflowApi.downloadArtifact(runId, artifact.id);
      workflowApi.saveBlobAs(blob, filenameFromPath(artifact.file_path));
    } catch {
      // Silently ignore — no toast system
    } finally {
      setDownloadingId(null);
    }
  }, [runId]);

  const handleDownloadAll = useCallback(async () => {
    setDownloadingAll(true);
    try {
      const blob = await workflowApi.downloadRunZip(runId);
      workflowApi.saveBlobAs(blob, `forgeai-run-${runId.slice(0, 8)}.zip`);
    } catch {
      // Silently ignore
    } finally {
      setDownloadingAll(false);
    }
  }, [runId]);

  if (artifacts.length === 0) {
    return <p className="text-sm text-gray-400 italic">No artifacts generated yet.</p>;
  }

  return (
    <>
      {/* Download All button */}
      <div className="flex justify-end mb-3">
        <Button
          variant="secondary"
          size="sm"
          onClick={handleDownloadAll}
          disabled={downloadingAll}
        >
          {downloadingAll ? (
            <span className="flex items-center gap-1.5">
              <Spinner size="sm" />
              Preparing ZIP…
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download All
            </span>
          )}
        </Button>
      </div>

      <ul className="divide-y divide-gray-100">
        {artifacts.map((a) => {
          const isDownloading = downloadingId === a.id;
          return (
            <li key={a.id} className="py-3 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">
                  {artifactLabel(a.artifact_type)}
                </p>
                {a.description && (
                  <p className="text-xs text-gray-500 truncate mt-0.5">{a.description}</p>
                )}
                <p className="text-xs text-gray-400 font-mono truncate">{a.file_path}</p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-xs text-gray-400">{formatBytes(a.size_bytes)}</span>
                {/* Preview button */}
                <button
                  onClick={() => setPreviewArtifact(a)}
                  className="text-xs text-brand-600 hover:text-brand-800 hover:underline transition-colors"
                  title="Preview"
                >
                  Preview
                </button>
                {/* Download button */}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleDownloadOne(a)}
                  disabled={isDownloading}
                >
                  {isDownloading ? (
                    <Spinner size="sm" />
                  ) : (
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                  )}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>

      {/* Preview Modal */}
      {previewArtifact && (
        <PreviewModal
          artifact={previewArtifact}
          runId={runId}
          onClose={() => setPreviewArtifact(null)}
        />
      )}
    </>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, loading, error, refetch } = useRun(runId);
  const { events, streaming, streamRunId, upsertRun } = useWorkflowStore();

  // ── Cancellation state ─────────────────────────────────────────────────
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const handleCancel = useCallback(async () => {
    if (!runId || cancelling) return;
    setCancelling(true);
    setCancelError(null);
    try {
      await workflowApi.cancelRun(runId);
      refetch();
    } catch (err: unknown) {
      const statusCode = (err as { response?: { status?: number } })?.response?.status;
      if (statusCode === 409) {
        refetch();
      } else {
        setCancelError("Failed to cancel run. Please try again.");
      }
    } finally {
      setCancelling(false);
    }
  }, [runId, cancelling, refetch]);

  // Always open SSE stream — backend handles completed/cancelled runs via
  // synthetic replay so we get the animated timeline on every page load.
  useRunStream(runId, () => { refetch(); });

  // ── Derive live progress from accumulated SSE events ───────────────────
  const isLiveStream = streamRunId === runId;

  const liveCompleted: string[] | null = isLiveStream
    ? events
        .filter((e) => e.type === "agent_completed" && e.agent)
        .map((e) => e.agent as string)
    : null;

  const liveCurrentAgent: string | null = isLiveStream
    ? (() => {
        const completedSet = new Set(
          events.filter((e) => e.type === "agent_completed").map((e) => e.agent),
        );
        const started = events
          .filter((e) => e.type === "agent_started" && e.agent)
          .map((e) => e.agent as string);
        const pending = started.filter((a) => !completedSet.has(a));
        return pending[pending.length - 1] ?? null;
      })()
    : null;

  const liveProgress: number | null = isLiveStream
    ? (() => {
        for (let i = events.length - 1; i >= 0; i--) {
          const e = events[i];
          if (
            (e.type === "progress_updated" ||
              e.type === "run_completed" ||
              e.type === "run_cancelled") &&
            e.progress !== undefined
          ) {
            return e.progress;
          }
        }
        return null;
      })()
    : null;

  // ── Persist run record to store for the dashboard ─────────────────────
  useEffect(() => {
    if (!run) return;
    const existingRecord = useWorkflowStore
      .getState()
      .recentRuns.find((r) => r.run_id === run.id);
    upsertRun({
      run_id: run.id,
      project_id: run.project_id,
      project_name: existingRecord?.project_name ?? "",
      status: run.status,
      progress_percentage:
        run.status === "completed"
          ? 100
          : Math.round((run.completed_agents.length / TOTAL_AGENTS) * 100),
      artifact_count: run.artifacts.length,
      created_at: run.created_at,
      completed_at: run.completed_at,
    });
  }, [run, upsertRun]);

  // ── Render states ─────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" className="text-brand-500" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="text-center py-16">
        <p className="text-red-600 mb-4">{error ?? "Run not found"}</p>
        <div className="flex items-center justify-center gap-3">
          <Button variant="secondary" onClick={refetch}>
            Retry
          </Button>
          <Link to="/dashboard" className="text-brand-600 hover:underline text-sm">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  // ── Displayed values — prefer live SSE data while streaming ──────────
  const displayCompleted = liveCompleted ?? run.completed_agents;
  const displayCurrent = liveCurrentAgent ?? run.current_agent;
  const displayProgress =
    liveProgress !== null
      ? liveProgress
      : run.status === "completed"
      ? 100
      : Math.round((run.completed_agents.length / TOTAL_AGENTS) * 100);

  const isActive = run.status === "queued" || run.status === "running";
  const isCancelled = run.status === "cancelled";

  return (
    <div className="max-w-3xl space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-500 flex items-center gap-2">
        <Link to="/dashboard" className="hover:text-gray-700 transition-colors">
          Dashboard
        </Link>
        <span className="text-gray-300">/</span>
        <Link
          to={`/projects/${run.project_id}`}
          className="hover:text-gray-700 transition-colors"
        >
          Project
        </Link>
        <span className="text-gray-300">/</span>
        <span className="text-gray-900 font-medium font-mono text-xs">
          {run.id.slice(0, 8)}&hellip;
        </span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pipeline Run</h1>
          <p className="text-gray-400 text-xs font-mono mt-1">{run.id}</p>
        </div>
        <div className="flex items-center gap-2">
          {streaming && isLiveStream && (
            <span className="flex items-center gap-1 text-xs text-brand-600 font-medium">
              <span className="w-2 h-2 rounded-full bg-brand-500 animate-pulse" />
              Live
            </span>
          )}
          <Badge label={run.status} variant="status" />
          {isActive && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleCancel}
              disabled={cancelling}
              className="text-red-600 hover:text-red-700 border-red-200 hover:border-red-300 disabled:opacity-50"
            >
              {cancelling ? (
                <span className="flex items-center gap-1">
                  <Spinner size="sm" />
                  Cancelling…
                </span>
              ) : (
                "Cancel Run"
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Cancel error banner */}
      {cancelError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center justify-between gap-4">
          {cancelError}
          <button
            className="text-xs text-red-500 hover:underline flex-shrink-0"
            onClick={() => setCancelError(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Cancellation notice */}
      {isCancelled && (
        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
          This run was cancelled. Partial results are shown below.
        </div>
      )}

      {/* Progress */}
      <div className="card p-5 space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-gray-700">Progress</span>
          <span className="text-gray-500">{Math.round(displayProgress)}%</span>
        </div>
        <ProgressBar pct={displayProgress} cancelled={isCancelled} />
        <div className="text-xs text-gray-400">
          {displayCompleted.length} / {TOTAL_AGENTS} agents completed
        </div>
      </div>

      {/* Agent timeline */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
          Agent Pipeline
        </h2>
        <AgentTimeline
          completedAgents={displayCompleted}
          currentAgent={displayCurrent}
          cancelled={isCancelled}
        />
      </div>

      {/* Metadata */}
      <div className="card p-5 grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Started</p>
          <p className="text-gray-700">
            {run.started_at ? formatDateTime(run.started_at) : "—"}
          </p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Completed</p>
          <p className="text-gray-700">
            {run.completed_at ? formatDateTime(run.completed_at) : "—"}
          </p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Trigger</p>
          <p className="text-gray-700 capitalize">{run.trigger}</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Run ID</p>
          <p className="text-gray-700 font-mono text-xs">{run.id}</p>
        </div>
      </div>

      {/* Error */}
      {run.error_message && (
        <div className="card p-4 bg-red-50 border border-red-200">
          <p className="text-sm font-medium text-red-700 mb-1">Error</p>
          <pre className="text-xs text-red-600 whitespace-pre-wrap font-mono">
            {run.error_message}
          </pre>
          <Button variant="secondary" size="sm" className="mt-3" onClick={refetch}>
            Refresh
          </Button>
        </div>
      )}

      {/* Artifacts */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
          Generated Artifacts
          {run.artifacts.length > 0 && (
            <span className="ml-2 text-brand-600 normal-case font-normal">
              ({run.artifacts.length})
            </span>
          )}
        </h2>
        {isActive ? (
          <p className="text-sm text-gray-400 italic flex items-center gap-2">
            <Spinner size="sm" className="text-brand-400" />
            Artifacts will appear when the pipeline completes.
          </p>
        ) : (
          <ArtifactList artifacts={run.artifacts} runId={run.id} />
        )}
      </div>
    </div>
  );
}
