"""
ForgeState -- the central shared state for every ForgeAI workflow.

Design rationale
----------------
TypedDict is chosen over dataclass for three reasons:
  1. LangGraph StateGraph requires TypedDict state.  The graph is initialised
     with StateGraph(ForgeState) and LangGraph inspects the annotations to
     define state channels.
  2. TypedDict IS a plain dict at runtime: zero-cost JSON serialization
     via json.dumps(state) -- no custom encoder needed.
  3. Every field is a JSON-native type (str, int, float, list, dict, None)
     so ForgeState round-trips through AgentRun.graph_state (JSONB) without
     any transformation layer.

Adding LangGraph channel reducers (future)
------------------------------------------
When list fields need to accumulate across parallel nodes, annotate them:

    from typing import Annotated
    import operator

    errors: Annotated[list[str], operator.add]
    conversation_history: Annotated[list[dict], operator.add]

This is the only change needed; the rest of the file stays identical.

Provider independence
---------------------
No import from OpenAI, FastAPI, SQLAlchemy, or any external service.
ForgeState lives entirely in the Domain layer.

Mutation safety
---------------
create_forge_state() returns a fresh dict on every call (no shared mutable
defaults).  List and dict fields are always brand-new instances.

Serialization contract
----------------------
  - UUIDs are stored as str.
  - datetimes are stored as ISO 8601 UTC strings.
  - Enum values are stored as their str value (e.g. "pending", "architect").
  - forge_state_to_json() / forge_state_from_json() are thin wrappers that
    give future callers a stable API even if the encoding changes.

Logging contract
----------------
Only project_id, current_agent, execution_status, and token fields are
safe to log.  NEVER log conversation_history, raw_requirements,
backend_code_summary, or any field that may contain generated code or user
data (PII risk, log-size risk).  Use forge_state_log_context() at all call
sites.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TypedDict, cast
from uuid import UUID

from app.domain.workflow.types import AgentResult, ArtifactInfo, ExecutionStatus


# ── ForgeState ────────────────────────────────────────────────────────────────


class ForgeState(TypedDict):
    """
    Central shared state passed between every node in the ForgeAI graph.

    Every agent receives a ForgeState, mutates a subset of its fields,
    and returns those changed fields.  LangGraph merges the returned dict
    with the existing state automatically.

    TypedDict is a plain dict at runtime -- isinstance(state, dict) is True.
    LangGraph uses the annotations to define graph channels.
    """

    # ── Project identity ──────────────────────────────────────────────────
    project_id: str            # UUID as str
    project_name: str

    # ── Requirements ──────────────────────────────────────────────────────
    raw_requirements: str
    clarified_requirements: str | None

    # ── Architecture ──────────────────────────────────────────────────────
    architecture_summary: str | None

    # ── Planning ──────────────────────────────────────────────────────────
    task_plan: list[str]       # Ordered task descriptions for the code generator

    # ── Database ──────────────────────────────────────────────────────────
    database_schema: str | None    # DDL or schema description as plain text

    # ── Generation ────────────────────────────────────────────────────────
    backend_code_summary: str | None
    frontend_code_summary: str | None

    # ── Review ────────────────────────────────────────────────────────────
    review_notes: list[str]

    # ── Artifacts ─────────────────────────────────────────────────────────
    artifacts: list[ArtifactInfo]

    # ── Execution control ─────────────────────────────────────────────────
    current_agent: str | None       # AgentType.value; None = not started
    completed_agents: list[str]     # AgentType values in completion order
    execution_status: str           # ExecutionStatus.value
    started_at: str | None          # ISO 8601 UTC; None until first agent runs
    updated_at: str                 # ISO 8601 UTC; refreshed on every mutation

    # ── LLM telemetry ─────────────────────────────────────────────────────
    model_used: str | None          # e.g. "gpt-4o-mini" -- last model active
    total_tokens: int               # Cumulative across all agents
    estimated_cost: float           # USD, cumulative

    # ── Conversation history ───────────────────────────────────────────────
    # Each entry: {"role": "user"|"assistant"|"system", "content": str}
    # Future channel reducer: Annotated[list[dict], operator.add]
    conversation_history: list[dict[str, str]]

    # ── Agent results ──────────────────────────────────────────────────────
    # One AgentResult appended per completed agent -- full audit trail.
    agent_results: list[AgentResult]

    # ── Error tracking ────────────────────────────────────────────────────
    errors: list[str]       # Unrecoverable; agent should set status=FAILED
    warnings: list[str]     # Non-fatal; workflow continues

    # ── Extensibility ─────────────────────────────────────────────────────
    # str -> str only: keeps JSON serialization trivial and avoids nesting
    # surprises.  Agents that need richer data should add typed fields above.
    metadata: dict[str, str]


# ── Factory ───────────────────────────────────────────────────────────────────


def create_forge_state(
    project_id: UUID | str,
    project_name: str,
    raw_requirements: str,
) -> ForgeState:
    """
    Return a fully-initialised ForgeState for a new workflow execution.

    Every call returns a fresh dict with brand-new list/dict instances --
    no shared mutable defaults.

    Args:
        project_id:       UUID (or str) of the project being generated.
        project_name:     Human-readable project name for display / logging.
        raw_requirements: The unprocessed requirements text from the user.

    Returns:
        ForgeState ready to be handed to the first node in the graph.
    """
    now: str = _utcnow()
    return ForgeState(
        # Project
        project_id=str(project_id),
        project_name=project_name,
        # Requirements
        raw_requirements=raw_requirements,
        clarified_requirements=None,
        # Architecture
        architecture_summary=None,
        # Planning
        task_plan=[],
        # Database
        database_schema=None,
        # Generation
        backend_code_summary=None,
        frontend_code_summary=None,
        # Review
        review_notes=[],
        # Artifacts
        artifacts=[],
        # Execution
        current_agent=None,
        completed_agents=[],
        execution_status=ExecutionStatus.PENDING.value,  # plain str: "pending"
        started_at=None,
        updated_at=now,
        # LLM telemetry
        model_used=None,
        total_tokens=0,
        estimated_cost=0.0,
        # Conversation
        conversation_history=[],
        # Agent results
        agent_results=[],
        # Errors
        errors=[],
        warnings=[],
        # Extensibility
        metadata={},
    )


# ── Serialization helpers ─────────────────────────────────────────────────────


def forge_state_to_json(state: ForgeState) -> str:
    """
    Serialise ForgeState to a compact JSON string.

    Suitable for storing in AgentRun.graph_state (passed through json.loads
    on the way out of PostgreSQL JSONB).  All field values are already
    JSON-native types -- no custom encoder is needed.
    """
    return json.dumps(state)


def forge_state_from_json(data: str | dict[str, Any]) -> ForgeState:
    """
    Deserialise ForgeState from a JSON string or a pre-parsed dict.

    The dict form is used when reading AgentRun.graph_state back from
    SQLAlchemy (JSONB is returned as a plain Python dict).
    """
    if isinstance(data, str):
        data = json.loads(data)
    return cast(ForgeState, data)


# ── Logging helpers ───────────────────────────────────────────────────────────


def forge_state_log_context(state: ForgeState) -> dict[str, Any]:
    """
    Return a structlog-safe dict with ONLY fields that are safe to log.

    Large fields (raw_requirements, generated code, conversation history)
    are intentionally excluded to prevent log bloat and accidental PII leaks.
    """
    return {
        "project_id": state["project_id"],
        "current_agent": state["current_agent"],
        "execution_status": state["execution_status"],
        "completed_agents": state["completed_agents"],
        "total_tokens": state["total_tokens"],
        "estimated_cost_usd": state["estimated_cost"],
        "error_count": len(state["errors"]),
        "warning_count": len(state["warnings"]),
    }


# ── Internal helpers ──────────────────────────────────────────────────────────


def _utcnow() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
