/**
 * Run History — /runs
 *
 * Displays all pipeline runs across the authenticated user's projects.
 * Reuses GET /analytics/runs (no new backend endpoint).
 *
 * Features:
 *  - Search by project name (client-side, instant)
 *  - Filter by status: All | Completed | Running | Failed | Cancelled
 *  - Newest-first sort (API default)
 *  - Full column set: Project, Status, Started, Finished, Duration,
 *    Tokens, Cost, Artifacts, Open Run
 *  - Loading / empty / error states
 */
import { Link } from "react-router-dom";
import { Badge } from "@/shared/components/ui/Badge";
import { Button } from "@/shared/components/ui/Button";
import { Input } from "@/shared/components/ui/Input";
import { Spinner } from "@/shared/components/ui/Spinner";
import { useRunHistory, type StatusFilter } from "@/features/analytics/hooks/useRunHistory";
import {
  formatDateTime,
  formatRuntime,
  formatCost,
  formatTokens,
  cn,
} from "@/shared/lib/utils";
import type { RunHistoryItem } from "@/shared/types";

// ── Constants ──────────────────────────────────────────────────────────────

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

// ── Table row ──────────────────────────────────────────────────────────────

function RunTableRow({ run }: { run: RunHistoryItem }) {
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      {/* Project */}
      <td className="py-3 pl-4 pr-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-800 truncate max-w-[200px]">
            {run.project_name || <span className="text-gray-400 italic">Unknown</span>}
          </p>
          <p className="text-xs text-gray-400 font-mono">{run.run_id.slice(0, 8)}…</p>
        </div>
      </td>

      {/* Status */}
      <td className="py-3 px-3 whitespace-nowrap">
        <Badge label={run.status} variant="status" />
      </td>

      {/* Started */}
      <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap">
        {run.started_at ? formatDateTime(run.started_at) : "—"}
      </td>

      {/* Finished */}
      <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap">
        {run.completed_at ? formatDateTime(run.completed_at) : "—"}
      </td>

      {/* Duration */}
      <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap tabular-nums">
        {run.duration_seconds !== null ? formatRuntime(run.duration_seconds) : "—"}
      </td>

      {/* Tokens */}
      <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap tabular-nums text-right">
        {run.tokens > 0 ? formatTokens(run.tokens) : "—"}
      </td>

      {/* Cost */}
      <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap tabular-nums text-right">
        {run.cost_usd > 0 ? formatCost(run.cost_usd) : "—"}
      </td>

      {/* Artifacts */}
      <td className="py-3 px-3 text-xs text-gray-600 whitespace-nowrap text-center">
        {run.artifact_count > 0 ? (
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-brand-50 text-brand-700 text-xs font-medium">
            {run.artifact_count}
          </span>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </td>

      {/* Open Run */}
      <td className="py-3 pl-3 pr-4 text-right">
        <Link
          to={`/runs/${run.run_id}`}
          className="text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline whitespace-nowrap"
        >
          Open →
        </Link>
      </td>
    </tr>
  );
}

// ── Table header ───────────────────────────────────────────────────────────

function TableHeader() {
  const cols = [
    { label: "Project", className: "pl-4 pr-3 text-left w-[200px]" },
    { label: "Status", className: "px-3 text-left" },
    { label: "Started", className: "px-3 text-left" },
    { label: "Finished", className: "px-3 text-left" },
    { label: "Duration", className: "px-3 text-left" },
    { label: "Tokens", className: "px-3 text-right" },
    { label: "Cost", className: "px-3 text-right" },
    { label: "Artifacts", className: "px-3 text-center" },
    { label: "", className: "pl-3 pr-4 text-right" },
  ];

  return (
    <thead>
      <tr className="border-b border-gray-200 bg-gray-50">
        {cols.map((col) => (
          <th
            key={col.label}
            className={cn(
              "py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap",
              col.className
            )}
          >
            {col.label}
          </th>
        ))}
      </tr>
    </thead>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────

function EmptyState({
  hasFilters,
  onClear,
}: {
  hasFilters: boolean;
  onClear: () => void;
}) {
  if (hasFilters) {
    return (
      <div className="text-center py-16">
        <p className="text-gray-500 text-sm">No runs match your search or filter.</p>
        <button
          onClick={onClear}
          className="mt-2 text-sm text-brand-600 hover:underline"
        >
          Clear filters
        </button>
      </div>
    );
  }
  return (
    <div className="text-center py-16">
      <p className="text-gray-400 text-sm">No pipeline runs yet.</p>
      <p className="text-gray-400 text-xs mt-1">
        Trigger a run from a project page to see it here.
      </p>
      <Link to="/dashboard" className="mt-4 inline-block text-sm text-brand-600 hover:underline">
        Go to Dashboard →
      </Link>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export function RunHistoryPage() {
  const {
    runs,
    allRuns,
    total,
    loading,
    error,
    search,
    setSearch,
    statusFilter,
    setStatusFilter,
    refetch,
  } = useRunHistory();

  const hasFilters = search.trim() !== "" || statusFilter !== "all";
  const hasTruncation = total > allRuns.length && !loading;

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <nav className="text-xs text-gray-400 mb-1 flex items-center gap-1.5">
            <Link to="/dashboard" className="hover:text-gray-600 transition-colors">
              Dashboard
            </Link>
            <span>/</span>
            <span className="text-gray-600">Run History</span>
          </nav>
          <h1 className="text-2xl font-bold text-gray-900">Run History</h1>
          {!loading && (
            <p className="text-gray-500 text-sm mt-0.5">
              {total === 0
                ? "No runs yet"
                : `${total} run${total !== 1 ? "s" : ""} across all projects`}
            </p>
          )}
        </div>
        <Button variant="secondary" size="sm" onClick={refetch} disabled={loading}>
          {loading ? <Spinner size="sm" /> : "↻ Refresh"}
        </Button>
      </div>

      {/* Search + filter bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="flex-1 max-w-sm">
          <Input
            placeholder="Search by project name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Status filter pills */}
        <div className="flex items-center gap-1 flex-wrap">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={cn(
                "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                statusFilter === f.value
                  ? "bg-brand-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Truncation notice */}
      {hasTruncation && (
        <div className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Showing the {allRuns.length} most recent runs out of {total} total. Use the search
          box to narrow results.
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="card p-5 bg-red-50 border border-red-200">
          <p className="text-sm text-red-600 mb-3">{error}</p>
          <Button variant="secondary" size="sm" onClick={refetch}>
            Retry
          </Button>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="card p-10 flex items-center justify-center gap-3 text-gray-400">
          <Spinner size="md" className="text-brand-500" />
          <span className="text-sm">Loading run history…</span>
        </div>
      )}

      {/* Table */}
      {!loading && !error && (
        <>
          {runs.length === 0 ? (
            <div className="card">
              <EmptyState
                hasFilters={hasFilters}
                onClear={() => {
                  setSearch("");
                  setStatusFilter("all");
                }}
              />
            </div>
          ) : (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full">
                  <TableHeader />
                  <tbody>
                    {runs.map((run) => (
                      <RunTableRow key={run.run_id} run={run} />
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Row count footer */}
              <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50 text-xs text-gray-400">
                {hasFilters
                  ? `${runs.length} of ${allRuns.length} run${allRuns.length !== 1 ? "s" : ""} match filters`
                  : `${runs.length} run${runs.length !== 1 ? "s" : ""}`}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
