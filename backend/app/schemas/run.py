from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.artifact import ArtifactResponse

_TOTAL_PIPELINE_AGENTS = 9


class AgentStepResponse(BaseModel):
    id: UUID
    run_id: UUID
    agent_type: str
    sequence: int
    status: str
    tokens_used: int
    cost_usd: float
    duration_ms: int | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class AgentRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    trigger: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunDetailResponse(AgentRunResponse):
    steps: list[AgentStepResponse]


# ── Workflow Execution API schemas ────────────────────────────────────────────


class RunCreateResponse(BaseModel):
    """Returned immediately from POST /projects/{project_id}/run."""

    run_id: UUID
    project_id: UUID
    status: str
    created_at: datetime


class RunDetailResponse(BaseModel):
    """Full run record including graph progress and assembled artifacts."""

    id: UUID
    project_id: UUID
    status: str
    trigger: str
    current_agent: str | None
    completed_agents: list[str]
    artifacts: list[ArtifactResponse]
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class RunStatusResponse(BaseModel):
    """Lightweight status poll response."""

    run_id: UUID
    status: str
    current_agent: str | None
    completed_agents: list[str]
    progress_percentage: float


class RunArtifactsResponse(BaseModel):
    """Artifact list for a completed run."""

    run_id: UUID
    artifacts: list[ArtifactResponse]
    total: int


class CancelRunResponse(BaseModel):
    """
    Returned from POST /runs/{run_id}/cancel.

    ``status`` reflects the run's state at the time the cancel endpoint
    returned:
    - ``"cancelled"``  — QUEUED run cancelled immediately, or RUNNING run
                         cancelled immediately because no active SSE stream
                         was detected.
    - ``"running"``    — Cancellation signal sent to an active SSE stream;
                         the stream will complete the current agent, persist
                         partial state, and transition to CANCELLED
                         asynchronously.  Poll GET /runs/{id}/status to
                         confirm the final status.
    """

    run_id: UUID
    status: str
    message: str
