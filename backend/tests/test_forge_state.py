"""
Tests for ForgeState and its supporting types.

All tests are pure Python — no database, no HTTP, no LLM calls.
The test suite verifies:
  1. Default initialisation via create_forge_state()
  2. JSON serialization round-trip (forge_state_to_json / forge_state_from_json)
  3. Enum values (ExecutionStatus)
  4. Mutation safety (no shared mutable defaults between instances)
  5. JSON compatibility of every field type
  6. forge_state_log_context() only exposes safe fields
  7. ArtifactInfo and AgentResult TypedDict structure
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.domain.workflow import (
    AgentResult,
    ArtifactInfo,
    ExecutionStatus,
    ForgeState,
    create_forge_state,
    forge_state_from_json,
    forge_state_log_context,
    forge_state_to_json,
)
from app.domain.value_objects.agent_type import AgentType
from app.domain.value_objects.artifact_type import ArtifactType


# ── Fixtures ──────────────────────────────────────────────────────────────────


PROJECT_ID = uuid.uuid4()
PROJECT_NAME = "My Forge Project"
REQUIREMENTS = "Build a REST API with JWT auth, project CRUD, and Postgres backend."


def _fresh_state() -> ForgeState:
    return create_forge_state(
        project_id=PROJECT_ID,
        project_name=PROJECT_NAME,
        raw_requirements=REQUIREMENTS,
    )


# ── 1. Default initialisation ─────────────────────────────────────────────────


def test_create_returns_forge_state_instance() -> None:
    state = _fresh_state()
    # TypedDict instances are plain dicts at runtime -- isinstance(x, ForgeState) raises TypeError.
    assert isinstance(state, dict)
    assert "project_id" in state  # structural check: ForgeState keys present


def test_project_id_stored_as_string() -> None:
    state = _fresh_state()
    assert state["project_id"] == str(PROJECT_ID)
    assert isinstance(state["project_id"], str)


def test_project_name_set_correctly() -> None:
    state = _fresh_state()
    assert state["project_name"] == PROJECT_NAME


def test_raw_requirements_set_correctly() -> None:
    state = _fresh_state()
    assert state["raw_requirements"] == REQUIREMENTS


def test_nullable_fields_default_to_none() -> None:
    state = _fresh_state()
    assert state["clarified_requirements"] is None
    assert state["architecture_summary"] is None
    assert state["database_schema"] is None
    assert state["backend_code_summary"] is None
    assert state["frontend_code_summary"] is None
    assert state["current_agent"] is None
    assert state["started_at"] is None
    assert state["model_used"] is None


def test_list_fields_default_to_empty_list() -> None:
    state = _fresh_state()
    assert state["task_plan"] == []
    assert state["review_notes"] == []
    assert state["artifacts"] == []
    assert state["completed_agents"] == []
    assert state["conversation_history"] == []
    assert state["agent_results"] == []
    assert state["errors"] == []
    assert state["warnings"] == []


def test_numeric_fields_default_to_zero() -> None:
    state = _fresh_state()
    assert state["total_tokens"] == 0
    assert state["estimated_cost"] == 0.0


def test_metadata_defaults_to_empty_dict() -> None:
    state = _fresh_state()
    assert state["metadata"] == {}


def test_execution_status_defaults_to_pending() -> None:
    state = _fresh_state()
    assert state["execution_status"] == ExecutionStatus.PENDING
    assert state["execution_status"] == "pending"


def test_updated_at_is_iso_string() -> None:
    state = _fresh_state()
    # Must be parseable as ISO 8601
    dt = datetime.fromisoformat(state["updated_at"])
    assert dt.tzinfo is not None   # timezone-aware


def test_create_accepts_string_project_id() -> None:
    str_id = str(uuid.uuid4())
    state = create_forge_state(
        project_id=str_id,
        project_name="X",
        raw_requirements="Some requirements here.",
    )
    assert state["project_id"] == str_id


# ── 2. JSON serialization round-trip ─────────────────────────────────────────


def test_forge_state_to_json_returns_string() -> None:
    state = _fresh_state()
    result = forge_state_to_json(state)
    assert isinstance(result, str)


def test_forge_state_to_json_is_valid_json() -> None:
    state = _fresh_state()
    parsed = json.loads(forge_state_to_json(state))
    assert isinstance(parsed, dict)


def test_forge_state_round_trip_from_json_string() -> None:
    original = _fresh_state()
    json_str = forge_state_to_json(original)
    restored = forge_state_from_json(json_str)

    assert restored["project_id"] == original["project_id"]
    assert restored["project_name"] == original["project_name"]
    assert restored["execution_status"] == original["execution_status"]
    assert restored["total_tokens"] == original["total_tokens"]


def test_forge_state_round_trip_from_dict() -> None:
    original = _fresh_state()
    as_dict = json.loads(forge_state_to_json(original))
    restored = forge_state_from_json(as_dict)
    assert restored["project_id"] == original["project_id"]


def test_forge_state_with_populated_fields_round_trips() -> None:
    state = _fresh_state()
    state["clarified_requirements"] = "Clarified version."
    state["architecture_summary"] = "Microservices with event sourcing."
    state["task_plan"] = ["task A", "task B"]
    state["total_tokens"] = 1500
    state["estimated_cost"] = 0.003
    state["errors"] = ["Something went wrong"]
    state["metadata"] = {"source": "user-upload", "version": "2"}

    restored = forge_state_from_json(forge_state_to_json(state))
    assert restored["clarified_requirements"] == "Clarified version."
    assert restored["task_plan"] == ["task A", "task B"]
    assert restored["total_tokens"] == 1500
    assert restored["errors"] == ["Something went wrong"]
    assert restored["metadata"]["version"] == "2"


def test_artifact_info_round_trips() -> None:
    state = _fresh_state()
    artifact: ArtifactInfo = {
        "artifact_id": str(uuid.uuid4()),
        "artifact_type": ArtifactType.SOURCE_CODE,
        "path": "backend/app/main.py",
        "description": "FastAPI application entry point",
        "size_bytes": 1024,
        "created_by": AgentType.CODE_GENERATOR,
    }
    state["artifacts"].append(artifact)

    restored = forge_state_from_json(forge_state_to_json(state))
    assert len(restored["artifacts"]) == 1
    assert restored["artifacts"][0]["artifact_type"] == "source_code"
    assert restored["artifacts"][0]["created_by"] == "code_generator"


def test_agent_result_round_trips() -> None:
    state = _fresh_state()
    result: AgentResult = {
        "agent_name": AgentType.REQUIREMENTS_ANALYST,
        "status": ExecutionStatus.COMPLETED,
        "summary": "Extracted 12 functional requirements.",
        "tokens_used": 320,
        "cost_usd": 0.0005,
        "duration_ms": 840,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error_message": None,
    }
    state["agent_results"].append(result)

    restored = forge_state_from_json(forge_state_to_json(state))
    assert len(restored["agent_results"]) == 1
    assert restored["agent_results"][0]["agent_name"] == "requirements_analyst"
    assert restored["agent_results"][0]["tokens_used"] == 320


# ── 3. Enum values ────────────────────────────────────────────────────────────


def test_execution_status_values_are_strings() -> None:
    for member in ExecutionStatus:
        assert isinstance(member.value, str)


def test_execution_status_happy_path_values_exist() -> None:
    assert ExecutionStatus.PENDING == "pending"
    assert ExecutionStatus.RUNNING == "running"
    assert ExecutionStatus.PAUSED == "paused"
    assert ExecutionStatus.COMPLETED == "completed"
    assert ExecutionStatus.FAILED == "failed"
    assert ExecutionStatus.CANCELLED == "cancelled"


def test_execution_status_from_string() -> None:
    assert ExecutionStatus("pending") is ExecutionStatus.PENDING
    assert ExecutionStatus("failed") is ExecutionStatus.FAILED


def test_agent_type_values_match_forge_state_fields() -> None:
    """AgentType strings must survive a ForgeState JSON round-trip."""
    state = _fresh_state()
    state["current_agent"] = AgentType.ARCHITECT
    state["completed_agents"] = [AgentType.REQUIREMENTS_ANALYST]

    restored = forge_state_from_json(forge_state_to_json(state))
    assert restored["current_agent"] == "architect"
    assert restored["completed_agents"] == ["requirements_analyst"]


# ── 4. Mutation safety ────────────────────────────────────────────────────────


def test_two_states_do_not_share_lists() -> None:
    state_a = _fresh_state()
    state_b = _fresh_state()

    state_a["errors"].append("error from A")
    assert state_b["errors"] == [], "state_b.errors must not be polluted by state_a"


def test_two_states_do_not_share_metadata_dict() -> None:
    state_a = _fresh_state()
    state_b = _fresh_state()

    state_a["metadata"]["key"] = "value"
    assert "key" not in state_b["metadata"], "state_b.metadata must be independent"


def test_two_states_do_not_share_task_plan() -> None:
    state_a = _fresh_state()
    state_b = _fresh_state()

    state_a["task_plan"].append("task X")
    assert state_b["task_plan"] == []


def test_two_states_do_not_share_artifacts() -> None:
    state_a = _fresh_state()
    state_b = _fresh_state()

    artifact: ArtifactInfo = {
        "artifact_id": str(uuid.uuid4()),
        "artifact_type": ArtifactType.TEST,
        "path": "tests/test_api.py",
        "description": "API test suite",
        "size_bytes": 512,
        "created_by": AgentType.TEST_WRITER,
    }
    state_a["artifacts"].append(artifact)
    assert state_b["artifacts"] == []


# ── 5. JSON field type compatibility ─────────────────────────────────────────


def test_all_default_values_are_json_native_types() -> None:
    """Every field in a freshly created state must be JSON-serializable."""
    state = _fresh_state()
    # This must not raise
    encoded = json.dumps(state)
    assert isinstance(encoded, str)


def test_none_fields_serialize_to_json_null() -> None:
    state = _fresh_state()
    parsed = json.loads(forge_state_to_json(state))
    assert parsed["clarified_requirements"] is None
    assert parsed["current_agent"] is None
    assert parsed["started_at"] is None


# ── 6. forge_state_log_context — safe fields only ─────────────────────────────


def test_log_context_contains_required_keys() -> None:
    state = _fresh_state()
    ctx = forge_state_log_context(state)
    assert "project_id" in ctx
    assert "current_agent" in ctx
    assert "execution_status" in ctx
    assert "total_tokens" in ctx
    assert "estimated_cost_usd" in ctx
    assert "error_count" in ctx
    assert "warning_count" in ctx


def test_log_context_excludes_sensitive_fields() -> None:
    state = _fresh_state()
    ctx = forge_state_log_context(state)
    assert "raw_requirements" not in ctx
    assert "conversation_history" not in ctx
    assert "backend_code_summary" not in ctx
    assert "frontend_code_summary" not in ctx


def test_log_context_counts_errors_and_warnings() -> None:
    state = _fresh_state()
    state["errors"].append("err1")
    state["errors"].append("err2")
    state["warnings"].append("warn1")

    ctx = forge_state_log_context(state)
    assert ctx["error_count"] == 2
    assert ctx["warning_count"] == 1


# ── 7. ArtifactInfo and AgentResult structure ─────────────────────────────────


def test_artifact_info_all_fields_present() -> None:
    artifact: ArtifactInfo = {
        "artifact_id": str(uuid.uuid4()),
        "artifact_type": ArtifactType.DOCUMENTATION,
        "path": "docs/README.md",
        "description": "Project readme",
        "size_bytes": 2048,
        "created_by": AgentType.DOC_WRITER,
    }
    # All keys accessible
    assert artifact["artifact_type"] == "documentation"
    assert artifact["created_by"] == "doc_writer"


def test_agent_result_all_fields_present() -> None:
    result: AgentResult = {
        "agent_name": AgentType.ARCHITECT,
        "status": ExecutionStatus.COMPLETED,
        "summary": "Generated system architecture.",
        "tokens_used": 500,
        "cost_usd": 0.001,
        "duration_ms": None,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error_message": None,
    }
    assert result["agent_name"] == "architect"
    assert result["status"] == "completed"
    assert result["duration_ms"] is None
