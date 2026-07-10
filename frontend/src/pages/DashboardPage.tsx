import { Link } from "react-router-dom";
import { Button } from "@/shared/components/ui/Button";
import { Badge } from "@/shared/components/ui/Badge";
import { Spinner } from "@/shared/components/ui/Spinner";
import { ProjectList } from "@/features/projects/components/ProjectList";
import { useAuthStore } from "@/features/auth/store/authStore";
import { useAnalytics } from "@/features/analytics/hooks/useAnalytics";
import { formatDate, formatRuntime, formatCost, formatTokens } from "@/shared/lib/utils";
import type { RunHistoryItem } from "@/shared/types";

// ── Success rate bar ───────────────────────────────────────────────────────

function SuccessBar({ rate }: { rate: number }) {
  const pct = Math.min(100, Math.max(0, rate));
  const color =
    pct >= 80 ? "bg-green-500" : pct >= 50 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div className="w-full bg-gray-100 rounded-full h-1.5 mt-2 overflow-hidden">
      <div
        className={`h-1.5 rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ── Stat card ──────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  accent,
  bar,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
  bar?: number;
}) {
  return (
    <div className="card p-4">
      <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent ?? "text-gray-900"} leading-tight`}>
        {value}
      </p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      {bar !== undefined && <SuccessBar rate={bar} />}
    </div>
  );
}

// ── Run history row (compact — dashboard preview) ──────────────────────────

function RunRow({ run }: { run: RunHistoryItem }) {
  return (
    <li className="py-3 grid grid-cols-[1fr_auto] gap-4 items-center">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-700 truncate">{run.project_name}</p>
        <div className="flex items-center gap-3 mt-0.5 flex-wrap">
          <span className="text-xs text-gray-400 font-mono">{run.run_id.slice(0, 8)}…</span>
          <span className="text-xs text-gray-400">{formatDate(run.started_at ?? "")}</span>
          {run.duration_seconds !== null && (
            <span className="text-xs text-gray-400">⏱ {formatRuntime(run.duration_seconds)}</span>
          )}
          {run.tokens > 0 && (
            <span className="text-xs text-gray-400">{formatTokens(run.tokens)} tok</span>
          )}
          {run.cost_usd > 0 && (
            <span className="text-xs text-gray-400">{formatCost(run.cost_usd)}</span>
          )}
          {run.artifact_count > 0 && (
            <span className="text-xs text-gray-400">
              {run.artifact_count} artifact{run.artifact_count !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        <Badge label={run.status} variant="status" />
        <Link to={`/runs/${run.run_id}`} className="text-xs text-brand-600 hover:underline">
          Open →
        </Link>
      </div>
    </li>
  );
}

// ── Main dashboard ─────────────────────────────────────────────────────────

export function DashboardPage() {
  const { user } = useAuthStore();
  const { overview, history, loading, error, refetch } = useAnalytics();

  const firstName =
    user?.full_name?.split(" ")[0] ?? user?.email?.split("@")[0] ?? "there";

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Hey, {firstName} 👋</h1>
          <p className="text-gray-500 mt-1 text-sm">Your ForgeAI analytics</p>
        </div>
        <Link to="/projects/new">
          <Button>+ New project</Button>
        </Link>
      </div>

      {/* Analytics section */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
          <Spinner size="sm" className="text-brand-500" />
          Loading analytics…
        </div>
      )}

      {error && !loading && (
        <div className="card p-4 bg-red-50 border border-red-200 text-sm text-red-600 flex items-center justify-between gap-4">
          {error}
          <button onClick={refetch} className="text-xs text-red-500 hover:underline">
            Retry
          </button>
        </div>
      )}

      {overview && !loading && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Projects" value={overview.total_projects} />
            <StatCard
              label="Total Runs"
              value={overview.total_runs}
              sub={`${overview.completed_runs} completed`}
            />
            <StatCard
              label="Success Rate"
              value={`${overview.success_rate}%`}
              accent={
                overview.success_rate >= 80
                  ? "text-green-600"
                  : overview.success_rate >= 50
                  ? "text-yellow-500"
                  : "text-red-500"
              }
              bar={overview.success_rate}
            />
            <StatCard label="Artifacts" value={overview.total_artifacts} accent="text-brand-600" />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <StatCard
              label="Tokens Used"
              value={formatTokens(overview.total_tokens)}
              sub="across all runs"
            />
            <StatCard
              label="Estimated Cost"
              value={formatCost(overview.estimated_total_cost)}
              sub="LLM API spend"
            />
            <StatCard
              label="Avg Runtime"
              value={
                overview.average_runtime_seconds > 0
                  ? formatRuntime(overview.average_runtime_seconds)
                  : "—"
              }
              sub="per completed run"
            />
          </div>

          {overview.total_runs > 0 && (
            <div className="card p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-3">
                Run Status Breakdown
              </p>
              <div className="flex rounded-full overflow-hidden h-3 bg-gray-100">
                {overview.completed_runs > 0 && (
                  <div
                    className="bg-green-500"
                    style={{ width: `${(overview.completed_runs / overview.total_runs) * 100}%` }}
                    title={`${overview.completed_runs} completed`}
                  />
                )}
                {overview.failed_runs > 0 && (
                  <div
                    className="bg-red-400"
                    style={{ width: `${(overview.failed_runs / overview.total_runs) * 100}%` }}
                    title={`${overview.failed_runs} failed`}
                  />
                )}
                {overview.cancelled_runs > 0 && (
                  <div
                    className="bg-gray-400"
                    style={{ width: `${(overview.cancelled_runs / overview.total_runs) * 100}%` }}
                    title={`${overview.cancelled_runs} cancelled`}
                  />
                )}
              </div>
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
                  {overview.completed_runs} completed
                </span>
                {overview.failed_runs > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-red-400 inline-block" />
                    {overview.failed_runs} failed
                  </span>
                )}
                {overview.cancelled_runs > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-gray-400 inline-block" />
                    {overview.cancelled_runs} cancelled
                  </span>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* Recent runs — compact preview, link to full history */}
      {history && history.items.length > 0 && (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
              Recent Runs
            </h2>
            <Link to="/runs" className="text-xs text-brand-600 hover:underline">
              View all runs →
            </Link>
          </div>
          <ul className="divide-y divide-gray-100">
            {history.items.slice(0, 5).map((run) => (
              <RunRow key={run.run_id} run={run} />
            ))}
          </ul>
        </div>
      )}

      {/* Project grid */}
      <ProjectList />
    </div>
  );
}
