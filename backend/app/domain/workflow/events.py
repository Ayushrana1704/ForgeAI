"""
Workflow SSE event types.

WorkflowEvent is a lightweight dict (not a dataclass) so it serialises to
JSON with ``json.dumps(event)`` and travels cleanly through async generators
without any import-time overhead.

Event types
-----------
run_started       – emitted once when execution begins
agent_started     – emitted when a pipeline node starts
agent_completed   – emitted when a pipeline node finishes successfully
progress_updated  – lightweight progress tick after each agent completes
artifact_created  – emitted for each ArtifactInfo assembled by artifact_packager
run_completed     – terminal success event (progress == 100.0)
run_failed        – terminal failure event (contains error message)

Payload rules
-------------
- Never include prompt text or generated document content.
- Every event carries: type, run_id, timestamp.
- Agent events add: agent.
- Progress events add: progress (0.0 – 100.0).
- Artifact events add: artifact_path, artifact_type.
- Failure events add: error.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict


class WorkflowEvent(TypedDict, total=False):
    """Lightweight SSE payload.  Only ``type``, ``run_id``, and ``timestamp``
    are always present; all other keys are optional."""

    type: str           # required — WorkflowEventType string value
    run_id: str         # required — UUID as str
    timestamp: str      # required — ISO 8601 UTC

    agent: str          # agent_started / agent_completed
    progress: float     # 0.0 – 100.0; present in progress events
    artifact_path: str  # relative path; artifact_created only
    artifact_type: str  # ArtifactType.value; artifact_created only
    error: str          # run_failed only


def make_event(
    event_type: str,
    run_id: str,
    *,
    agent: str | None = None,
    progress: float | None = None,
    artifact_path: str | None = None,
    artifact_type: str | None = None,
    error: str | None = None,
) -> WorkflowEvent:
    """
    Build a ``WorkflowEvent`` dict, including only non-None optional fields.

    Args:
        event_type:     One of the WorkflowEventType string values.
        run_id:         AgentRun.id as str.
        agent:          AgentType.value for agent_started / agent_completed.
        progress:       0.0 – 100.0 percentage.
        artifact_path:  Relative file path for artifact_created events.
        artifact_type:  ArtifactType.value for artifact_created events.
        error:          Human-readable error message for run_failed events.

    Returns:
        A plain dict that is safe to ``json.dumps()``.
    """
    event: dict[str, Any] = {
        "type": event_type,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if agent is not None:
        event["agent"] = agent
    if progress is not None:
        event["progress"] = progress
    if artifact_path is not None:
        event["artifact_path"] = artifact_path
    if artifact_type is not None:
        event["artifact_type"] = artifact_type
    if error is not None:
        event["error"] = error
    return event  # type: ignore[return-value]
