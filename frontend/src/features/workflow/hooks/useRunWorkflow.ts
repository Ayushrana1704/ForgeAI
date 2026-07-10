/**
 * Hook: trigger a workflow run for a project.
 * POST /projects/{projectId}/run → navigate to /runs/:runId
 *
 * The backend executes the full 9-agent pipeline synchronously before
 * returning, so by the time we navigate to the run page the run status is
 * already "completed" (or "failed").  We persist the correct state
 * in the store immediately so the dashboard is never misleading.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { workflowApi } from "@/features/workflow/api/workflowApi";
import { useWorkflowStore } from "@/features/workflow/store/workflowStore";
import { extractErrorMessage } from "@/shared/lib/axios";

export function useRunWorkflow(projectId: string, projectName: string) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { upsertRun } = useWorkflowStore();

  async function triggerRun() {
    setLoading(true);
    setError(null);
    try {
      const result = await workflowApi.triggerRun(projectId);
      upsertRun({
        run_id: result.run_id,
        project_id: result.project_id,
        project_name: projectName,
        status: result.status,
        // Pipeline is synchronous — status is "completed" by the time we get here.
        // The RunDetailPage will update artifact_count once it fetches the full record.
        progress_percentage: result.status === "completed" ? 100 : 0,
        artifact_count: 0,
        created_at: result.created_at,
        completed_at: null,
      });
      navigate(`/runs/${result.run_id}`);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to start workflow"));
      setLoading(false);
    }
    // Note: do NOT put setLoading(false) in finally — if navigate() succeeds
    // the component unmounts and setting state on an unmounted component is
    // a no-op (harmless in React 18 but noisy in dev).  The catch branch
    // handles the failure case explicitly.
  }

  return { triggerRun, loading, error };
}
