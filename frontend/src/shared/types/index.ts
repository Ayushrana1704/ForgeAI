// ── API / Domain types shared across features ──────────────────────────────

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export type ProjectStatus = "pending" | "running" | "completed" | "failed";

export interface Project {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  requirements: string;
  tech_stack: Record<string, unknown>;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface ApiError {
  detail: string;
}

// ── Form / UI helpers ──────────────────────────────────────────────────────

export type FormState = "idle" | "loading" | "success" | "error";

// ── Workflow / Run types ───────────────────────────────────────────────────

export type RunStatusValue = "queued" | "running" | "completed" | "failed" | "cancelled";

/** Response from POST /projects/{id}/run */
export interface RunCreateResponse {
  run_id: string;
  project_id: string;
  status: RunStatusValue;
  created_at: string;
}

/** Response from GET /runs/{id} */
export interface RunDetail {
  id: string;
  project_id: string;
  status: RunStatusValue;
  trigger: string;
  current_agent: string | null;
  completed_agents: string[];
  artifacts: Artifact[];
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

/** Response from GET /runs/{id}/status */
export interface RunStatusPoll {
  run_id: string;
  status: RunStatusValue;
  current_agent: string | null;
  completed_agents: string[];
  progress_percentage: number;
}

/** Response from GET /runs/{id}/artifacts */
export interface RunArtifactsResponse {
  run_id: string;
  artifacts: Artifact[];
  total: number;
}

/** A single artifact produced by the pipeline */
export interface Artifact {
  id: string;
  project_id: string;
  run_id: string | null;
  step_id: string | null;
  artifact_type: string;
  description: string | null;
  file_path: string;
  language: string | null;
  size_bytes: number;
  created_at: string;
}

/** An SSE event emitted by GET /runs/{id}/stream */
export interface WorkflowEvent {
  type:
    | "run_started"
    | "agent_started"
    | "agent_completed"
    | "progress_updated"
    | "artifact_created"
    | "run_completed"
    | "run_failed"
    | "run_cancelled"
    | string;
  run_id: string;
  timestamp: string;
  agent?: string;
  progress?: number;
  artifact_path?: string;
  artifact_type?: string;
  error?: string;
}

/** Lightweight run record kept in the workflow store for the dashboard */
export interface RunRecord {
  run_id: string;
  project_id: string;
  project_name: string;
  status: RunStatusValue;
  progress_percentage: number;
  artifact_count: number;
  created_at: string;
  completed_at: string | null;
}

// ── Analytics types ────────────────────────────────────────────────────────

export interface AnalyticsOverview {
  total_projects: number;
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  cancelled_runs: number;
  average_runtime_seconds: number;
  total_tokens: number;
  estimated_total_cost: number;
  total_artifacts: number;
  success_rate: number; // 0–100
}

export interface RunHistoryItem {
  run_id: string;
  project_id: string;
  project_name: string;
  status: RunStatusValue;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  tokens: number;
  cost_usd: number;
  artifact_count: number;
}

export interface RunHistoryResponse {
  items: RunHistoryItem[];
  total: number;
  offset: number;
  limit: number;
}
