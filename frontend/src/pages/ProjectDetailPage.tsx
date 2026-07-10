import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { projectsApi } from "@/features/projects/api/projectsApi";
import { useRunWorkflow } from "@/features/workflow/hooks/useRunWorkflow";
import { Badge } from "@/shared/components/ui/Badge";
import { Button } from "@/shared/components/ui/Button";
import { Spinner } from "@/shared/components/ui/Spinner";
import { formatDateTime } from "@/shared/lib/utils";
import { extractErrorMessage } from "@/shared/lib/axios";
import type { Project } from "@/shared/types";

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    projectsApi
      .get(id)
      .then(setProject)
      .catch((err) => setError(extractErrorMessage(err)))
      .finally(() => setLoading(false));
  }, [id]);

  const {
    triggerRun,
    loading: runLoading,
    error: runError,
  } = useRunWorkflow(id ?? "", project?.name ?? "");

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" className="text-brand-500" />
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="text-center py-16">
        <p className="text-red-600 mb-4">{error ?? "Project not found"}</p>
        <Link to="/dashboard" className="text-brand-600 hover:underline text-sm">
          Back to dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-500">
        <Link to="/dashboard" className="hover:text-gray-700 transition-colors">
          Dashboard
        </Link>
        <span className="mx-2 text-gray-300">/</span>
        <span className="text-gray-900 font-medium">{project.name}</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
          {project.description && (
            <p className="text-gray-500 mt-1 text-sm">{project.description}</p>
          )}
        </div>
        <Badge label={project.status} variant="status" />
      </div>

      {/* Requirements */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Requirements
        </h2>
        <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans leading-relaxed">
          {project.requirements}
        </pre>
      </div>

      {/* Metadata */}
      <div className="card p-5 grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Created</p>
          <p className="text-gray-700">{formatDateTime(project.created_at)}</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Last updated</p>
          <p className="text-gray-700">{formatDateTime(project.updated_at)}</p>
        </div>
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Project ID</p>
          <p className="text-gray-700 font-mono text-xs">{project.id}</p>
        </div>
      </div>

      {/* Run AI Workflow */}
      <div className="card p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-1">AI Agent Pipeline</h2>
          <p className="text-sm text-gray-500">
            Runs 9 AI agents in sequence — requirements analysis, architecture design,
            task planning, database schema, backend code, frontend code, code review,
            refinement, and artifact packaging.
          </p>
        </div>

        {runError && (
          <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{runError}</p>
        )}

        <div className="flex items-center gap-4">
          <Button
            onClick={triggerRun}
            loading={runLoading}
            disabled={runLoading}
            size="md"
          >
            Run AI Workflow
          </Button>

          {runLoading && (
            <p className="text-xs text-gray-400">
              Pipeline running — this takes 1–3 min with real LLMs…
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
