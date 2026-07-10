"""
Workflow-layer supporting types for ForgeState.

Design principles:
  - All TypedDicts: naturally JSON-serializable (they are plain dicts)
  - All enum values stored as str in state: JSON-roundtrip safe without custom encoders
  - No imports from FastAPI, SQLAlchemy, or OpenAI
  - ExecutionStatus is WORKFLOW state, intentionally separate from RunStatus
    (RunStatus is the persistence-layer status of an AgentRun DB record;
     ExecutionStatus is the in-memory workflow state visible to agents)

AgentType is NOT redefined here.  Import it from:
    app.domain.value_objects.agent_type.AgentType
ArtifactType is NOT redefined here.  Import it from:
    app.domain.value_objects.artifact_type.ArtifactType
"""
from __future__ import annotations

from enum import StrEnum
from typing import TypedDict


# ── Enums ────────────────────────────────────────────────────────────────────


class ExecutionStatus(StrEnum):
    """
    Lifecycle of a ForgeState workflow execution.

    Distinct from RunStatus (the DB persistence record status) so that
    workflow logic is not coupled to database concerns.

    Transitions:
        PENDING -> RUNNING -> COMPLETED  (happy path)
                           -> FAILED     (unrecoverable error)
        RUNNING -> PAUSED  -> RUNNING    (human-in-the-loop)
        RUNNING -> CANCELLED             (user-initiated)
    """

    PENDING = "pending"      # Workflow initialised; no agent has executed yet
    RUNNING = "running"      # An agent is currently executing
    PAUSED = "paused"        # Workflow suspended pending human input / approval
    COMPLETED = "completed"  # All agents completed successfully.  Terminal.
    FAILED = "failed"        # Unrecoverable error.  Terminal.
    CANCELLED = "cancelled"  # User-initiated cancellation.  Terminal.


# ── Supporting TypedDicts ─────────────────────────────────────────────────────


class ArtifactInfo(TypedDict):
    """
    Lightweight descriptor for a generated artifact.

    'artifact_type' holds an ArtifactType string value so the field is
    JSON-safe without a custom encoder.
    'created_by' holds an AgentType string value for the same reason.
    """

    artifact_id: str       # UUID as str
    artifact_type: str     # ArtifactType.value  e.g. "source_code"
    path: str              # Relative path within the generated project
    description: str       # One-line human-readable description
    size_bytes: int        # 0 if not yet written to disk
    created_by: str        # AgentType.value  e.g. "code_generator"
    content: str           # Full markdown content (for DB storage + download API)


class AgentResult(TypedDict):
    """
    Summary of work completed by a single agent pass.

    One AgentResult is appended to ForgeState.agent_results each time an
    agent finishes (success or failure).  This provides a full audit trail
    of what each agent did without embedding large payloads in the state.
    """

    agent_name: str          # AgentType.value
    status: str              # ExecutionStatus.value at the moment of completion
    summary: str             # Short human-readable description of output
    tokens_used: int         # Prompt + completion tokens consumed
    cost_usd: float          # Estimated cost in USD
    duration_ms: int | None  # Wall-clock time for this agent; None if not measured
    completed_at: str        # ISO 8601 UTC timestamp
    error_message: str | None  # Populated only when status == "failed"
