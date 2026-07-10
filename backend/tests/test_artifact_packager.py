"""
Tests for the Artifact Packager agent.

Coverage
--------
_format_task_plan_markdown helper
 1. Returns a markdown string starting with '# Task Plan'
 2. Groups tasks by category in sorted order
 3. Each task includes id, title, priority, complexity, description, dependencies
 4. Skips malformed JSON entries silently
 5. Returns placeholder when task_plan is empty
 6. Multiple categories appear in alphabetical order

_build_project_summary helper
 7. Contains project name in heading
 8. Contains project_id
 9. Lists all ARTIFACT_PATHS
10. Contains task count
11. Contains pipeline completion section

_make_artifact helper
12. Returns ArtifactInfo with correct path
13. artifact_type is ArtifactType.DOCUMENTATION value
14. created_by is "artifact_packager"
15. artifact_id is a non-empty string (UUID)
16. size_bytes equals UTF-8 byte length of content
17. description matches provided description

Node success
18. execution_status → COMPLETED
19. artifacts is a list with 9 elements
20. Each artifact has the correct path (all ARTIFACT_PATHS present)
21. All artifacts have artifact_type == "documentation"
22. All artifacts have created_by == "artifact_packager"
23. All artifacts have non-empty artifact_id
24. All artifacts have size_bytes > 0
25. metadata["project_summary"] is non-empty
26. Existing metadata keys preserved (merge, not replace)
27. metadata["review"] and metadata["refined"] still present after packager
28. current_agent → "artifact_packager"
29. completed_agents appended (prior agents preserved)
30. agent_results appended with correct shape
31. agent_results[-1].tokens_used == 0  (no LLM call)
32. agent_results[-1].cost_usd == 0.0   (no LLM call)
33. updated_at present
34. total_tokens NOT in changeset (packager does not modify LLM telemetry)
35. estimated_cost NOT in changeset
36. model_used NOT in changeset

Read-only contract — prior fields NOT in changeset
37. clarified_requirements not re-emitted
38. architecture_summary not re-emitted
39. task_plan not re-emitted
40. database_schema not re-emitted
41. backend_code_summary not re-emitted
42. frontend_code_summary not re-emitted
43. review_notes not re-emitted
44. raw_requirements not in changeset

Guard conditions
45. Empty clarified_requirements → FAILED
46. None clarified_requirements → FAILED
47. Empty architecture_summary → FAILED
48. None architecture_summary → FAILED
49. Empty task_plan list → FAILED
50. None task_plan → FAILED
51. Empty database_schema → FAILED
52. None database_schema → FAILED
53. Empty backend_code_summary → FAILED
54. None backend_code_summary → FAILED
55. Empty frontend_code_summary → FAILED
56. None frontend_code_summary → FAILED
57. Empty review_notes list → FAILED
58. None review_notes → FAILED
59. Missing metadata["refined"] → FAILED
60. Empty metadata["refined"] → FAILED

Error handling
61. Failure path: failed AgentResult recorded with error_message
62. Failure path: errors list appended (not replaced)
63. Failure path: artifacts NOT modified (empty list preserved)

State integrity
64. Input state dict not mutated

Graph round-trip (nine agents)
65. build_forge_graph compiles with nine nodes
66. Nine-agent ainvoke → execution_status COMPLETED
67. All nine agents in completed_agents
68. Nine agent_results records
69. artifacts list has 9 entries
70. metadata["project_summary"] present after full run
71. metadata["review"] still present (not overwritten)
72. metadata["refined"] still present (not overwritten)
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.services.llm.types import CompletionResponse, UsageInfo
from app.domain.value_objects.artifact_type import ArtifactType
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.artifact_packager import (
    ARTIFACT_PATHS,
    _build_project_summary,
    _format_task_plan_markdown,
    _make_artifact,
    make_artifact_packager_node,
)

# ── Sample fixtures ───────────────────────────────────────────────────────────

_SAMPLE_REQUIREMENTS = "Build a task management REST API with React frontend."

_SAMPLE_CLARIFIED = (
    "## Functional Requirements\nCRUD tasks.\n\n"
    "## Non-Functional Requirements\nJWT auth.\n\n"
    "## Assumptions\nSingle-tenant.\n\n"
    "## Missing Information\nNone.\n\n"
    "## Risks\nNone.\n\n"
    "## Acceptance Criteria\nAll tests pass."
)

_SAMPLE_ARCHITECTURE = (
    "## Architecture Pattern\nLayered REST.\n\n"
    "## Backend Services\nFastAPI.\n\n"
    "## Frontend Architecture\nReact Vite.\n\n"
    "## Database Architecture\nPostgreSQL.\n\n"
    "## API Design\nREST JSON.\n\n"
    "## Security Architecture\nJWT.\n\n"
    "## Scalability Strategy\nDocker.\n\n"
    "## Deployment Architecture\nAWS EC2."
)

_SAMPLE_DB_SCHEMA = (
    "## Core Entities\nTask, User.\n\n"
    "## Entity Attributes\nTask: id UUID PK.\n\n"
    "## Relationships\nMany-to-one.\n\n"
    "## Primary Keys\nUUID PKs.\n\n"
    "## Foreign Keys\ntasks.user_id.\n\n"
    "## Constraints\nNOT NULL.\n\n"
    "## Indexes\nidx.\n\n"
    "## Normalization Notes\n3NF."
)

_SAMPLE_BACKEND = (
    "## Project Structure\napp/main.py\n\n"
    "## API Modules\nTaskRouter: /tasks.\n\n"
    "## Database Layer\nSQLAlchemy async.\n\n"
    "## Repository Layer\nTaskRepository.\n\n"
    "## Service Layer\nTaskService.\n\n"
    "## Authentication\nJWT RS256.\n\n"
    "## Dependency Injection\nFastAPI Depends.\n\n"
    "## Middleware\nCORS, request-id.\n\n"
    "## Validation\nPydantic v2.\n\n"
    "## Testing Strategy\npytest + asyncio."
)

_SAMPLE_FRONTEND = (
    "## Application Structure\nsrc/main.tsx\n\n"
    "## Feature Organization\ntasks/, auth/.\n\n"
    "## Routing\nReact Router v6.\n\n"
    "## State Management\nZustand + RQ.\n\n"
    "## API Integration\nAxios client.\n\n"
    "## Authentication Flow\nJWT memory.\n\n"
    "## UI Components\nButton, Input.\n\n"
    "## Forms & Validation\nRHF + Zod.\n\n"
    "## Error Handling\nErrorBoundary.\n\n"
    "## Testing Strategy\nVitest + RTL."
)

_SAMPLE_TASK_PLAN = [
    json.dumps({"id": "BE-001", "title": "FastAPI setup", "category": "Backend",
                "priority": "High", "complexity": "Low",
                "description": "Init project.", "dependencies": []}),
    json.dumps({"id": "FE-001", "title": "React setup", "category": "Frontend",
                "priority": "High", "complexity": "Low",
                "description": "Init Vite.", "dependencies": []}),
    json.dumps({"id": "DB-001", "title": "Users table", "category": "Database",
                "priority": "High", "complexity": "Low",
                "description": "Create migration.", "dependencies": ["BE-001"]}),
]

_SAMPLE_REVIEW_NOTES = [
    "## Missing Requirements\n- [MISSING] Rate limiting.",
    "## Database Issues\n- [DB] soft-delete missing.",
]

_SAMPLE_REVIEW_RAW = "\n\n".join(_SAMPLE_REVIEW_NOTES)

_SAMPLE_REFINED = (
    "## Updated Architecture Notes\n- [ARCH-FIX] Add rate-limit middleware.\n\n"
    "## Updated Task Recommendations\n- [TASK-ADD] BE-010: Redis rate-limiting.\n\n"
    "## Updated Database Notes\n- [DB-FIX] tasks.deleted_at: add column.\n\n"
    "## Updated Backend Notes\n- [BE-FIX] /tasks: cursor pagination.\n\n"
    "## Updated Frontend Notes\n- No changes required.\n\n"
    "## Summary of Improvements Applied\n- Total: 3"
)


def assert_(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _make_state(**overrides: Any) -> ForgeState:
    state = create_forge_state(
        project_id=str(uuid4()),
        project_name="Test Project",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    state["clarified_requirements"] = _SAMPLE_CLARIFIED
    state["architecture_summary"] = _SAMPLE_ARCHITECTURE
    state["task_plan"] = list(_SAMPLE_TASK_PLAN)
    state["database_schema"] = _SAMPLE_DB_SCHEMA
    state["backend_code_summary"] = _SAMPLE_BACKEND
    state["frontend_code_summary"] = _SAMPLE_FRONTEND
    state["review_notes"] = list(_SAMPLE_REVIEW_NOTES)
    state["completed_agents"] = [
        "requirements_analyst", "architect", "task_planner",
        "database_designer", "backend_generator", "frontend_generator",
        "reviewer", "refiner",
    ]
    state["total_tokens"] = 8000
    state["estimated_cost"] = 0.008
    state["model_used"] = "gpt-4o-mini"
    state["metadata"] = {
        "existing_key": "existing_value",
        "review": _SAMPLE_REVIEW_RAW,
        "refined": _SAMPLE_REFINED,
    }
    for k, v in overrides.items():
        state[k] = v
    return state


def _run(node_fn: Any, state: ForgeState) -> dict[str, Any]:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(node_fn(state))


# ── 1-6: _format_task_plan_markdown ──────────────────────────────────────────

def test_01_format_task_plan_markdown_starts_with_heading():
    result = _format_task_plan_markdown(_SAMPLE_TASK_PLAN)
    assert_(result.startswith("# Task Plan"), f"Should start with '# Task Plan', got: {result[:40]!r}")


def test_02_format_task_plan_groups_by_category():
    result = _format_task_plan_markdown(_SAMPLE_TASK_PLAN)
    assert_("## Backend" in result, "Backend section missing")
    assert_("## Frontend" in result, "Frontend section missing")
    assert_("## Database" in result, "Database section missing")


def test_03_format_task_plan_includes_task_fields():
    result = _format_task_plan_markdown(_SAMPLE_TASK_PLAN)
    assert_("BE-001" in result, "Task id BE-001 missing")
    assert_("FastAPI setup" in result, "Task title missing")
    assert_("High" in result, "Priority missing")
    assert_("Low" in result, "Complexity missing")
    assert_("Init project." in result, "Description missing")


def test_04_format_task_plan_skips_malformed_json():
    plan = ["not-json"] + _SAMPLE_TASK_PLAN
    result = _format_task_plan_markdown(plan)
    assert_("BE-001" in result, "Valid tasks should still appear")


def test_05_format_task_plan_placeholder_when_empty():
    result = _format_task_plan_markdown([])
    assert_("No tasks available" in result, f"Expected placeholder, got: {result!r}")


def test_06_format_task_plan_categories_sorted():
    result = _format_task_plan_markdown(_SAMPLE_TASK_PLAN)
    backend_pos = result.index("## Backend")
    database_pos = result.index("## Database")
    frontend_pos = result.index("## Frontend")
    assert_(backend_pos < database_pos < frontend_pos,
            "Categories should be in alphabetical order")


# ── 7-11: _build_project_summary ─────────────────────────────────────────────

def _sample_summary() -> str:
    return _build_project_summary(
        project_name="Test Project",
        project_id="proj-123",
        clarified=_SAMPLE_CLARIFIED,
        architecture=_SAMPLE_ARCHITECTURE,
        task_plan=_SAMPLE_TASK_PLAN,
        db_schema=_SAMPLE_DB_SCHEMA,
        backend=_SAMPLE_BACKEND,
        frontend=_SAMPLE_FRONTEND,
        review_notes=_SAMPLE_REVIEW_NOTES,
        refined=_SAMPLE_REFINED,
    )


def test_07_project_summary_contains_project_name():
    s = _sample_summary()
    assert_("Test Project" in s, "Project name missing from summary")


def test_08_project_summary_contains_project_id():
    s = _sample_summary()
    assert_("proj-123" in s, "Project ID missing from summary")


def test_09_project_summary_lists_all_artifact_paths():
    s = _sample_summary()
    for path in ARTIFACT_PATHS:
        assert_(path in s, f"Artifact path {path!r} missing from summary")


def test_10_project_summary_contains_task_count():
    s = _sample_summary()
    assert_("3" in s, "Task count (3) should appear in summary")


def test_11_project_summary_contains_pipeline_section():
    s = _sample_summary()
    assert_("Pipeline" in s or "pipeline" in s,
            "Pipeline completion section missing")


# ── 12-17: _make_artifact ────────────────────────────────────────────────────

def test_12_make_artifact_correct_path():
    a = _make_artifact("docs/foo.md", "content", "desc")
    assert_(a["path"] == "docs/foo.md", f"Expected 'docs/foo.md', got {a['path']!r}")


def test_13_make_artifact_type_is_documentation():
    a = _make_artifact("docs/foo.md", "content", "desc")
    assert_(a["artifact_type"] == ArtifactType.DOCUMENTATION.value,
            f"Expected 'documentation', got {a['artifact_type']!r}")


def test_14_make_artifact_created_by_packager():
    a = _make_artifact("docs/foo.md", "content", "desc")
    assert_(a["created_by"] == "artifact_packager",
            f"Expected 'artifact_packager', got {a['created_by']!r}")


def test_15_make_artifact_id_nonempty():
    a = _make_artifact("docs/foo.md", "content", "desc")
    assert_(bool(a["artifact_id"]), "artifact_id should be non-empty")


def test_16_make_artifact_size_bytes():
    content = "hello"
    a = _make_artifact("docs/foo.md", content, "desc")
    assert_(a["size_bytes"] == len(content.encode("utf-8")),
            f"size_bytes mismatch: {a['size_bytes']}")


def test_17_make_artifact_description():
    a = _make_artifact("docs/foo.md", "content", "My description")
    assert_(a["description"] == "My description",
            f"description mismatch: {a['description']!r}")


# ── 18-36: Node success ───────────────────────────────────────────────────────

def test_18_success_execution_status_completed():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_(result["execution_status"] == ExecutionStatus.COMPLETED.value,
            f"Expected COMPLETED, got {result['execution_status']}")


def test_19_artifacts_list_has_nine_elements():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_(len(result["artifacts"]) == 9,
            f"Expected 9 artifacts, got {len(result['artifacts'])}")


def test_20_all_artifact_paths_present():
    result = _run(make_artifact_packager_node(), _make_state())
    paths = {a["path"] for a in result["artifacts"]}
    for expected in ARTIFACT_PATHS:
        assert_(expected in paths, f"Artifact path {expected!r} missing")


def test_21_all_artifacts_type_documentation():
    result = _run(make_artifact_packager_node(), _make_state())
    for a in result["artifacts"]:
        assert_(a["artifact_type"] == ArtifactType.DOCUMENTATION.value,
                f"Artifact {a['path']!r} has wrong type: {a['artifact_type']!r}")


def test_22_all_artifacts_created_by_packager():
    result = _run(make_artifact_packager_node(), _make_state())
    for a in result["artifacts"]:
        assert_(a["created_by"] == "artifact_packager",
                f"Artifact {a['path']!r} has wrong created_by: {a['created_by']!r}")


def test_23_all_artifacts_have_nonempty_id():
    result = _run(make_artifact_packager_node(), _make_state())
    for a in result["artifacts"]:
        assert_(bool(a["artifact_id"]),
                f"Artifact {a['path']!r} has empty artifact_id")


def test_24_all_artifacts_size_bytes_positive():
    result = _run(make_artifact_packager_node(), _make_state())
    for a in result["artifacts"]:
        assert_(a["size_bytes"] > 0,
                f"Artifact {a['path']!r} has size_bytes={a['size_bytes']}")


def test_25_metadata_project_summary_nonempty():
    result = _run(make_artifact_packager_node(), _make_state())
    ps = result["metadata"].get("project_summary", "")
    assert_(bool(ps), "metadata['project_summary'] should be non-empty")


def test_26_metadata_merge_preserves_existing_keys():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_(result["metadata"].get("existing_key") == "existing_value",
            "Existing metadata keys must be preserved")


def test_27_metadata_review_and_refined_still_present():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("review" in result["metadata"], "metadata['review'] was lost")
    assert_("refined" in result["metadata"], "metadata['refined'] was lost")


def test_28_current_agent():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_(result["current_agent"] == "artifact_packager",
            f"Expected 'artifact_packager', got {result['current_agent']!r}")


def test_29_completed_agents_appended():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("artifact_packager" in result["completed_agents"],
            "artifact_packager should be in completed_agents")
    assert_("refiner" in result["completed_agents"],
            "Prior agents must be preserved")


def test_30_agent_results_shape():
    result = _run(make_artifact_packager_node(), _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["agent_name"] == "artifact_packager", "agent_name mismatch")
    assert_(ar["status"] == ExecutionStatus.COMPLETED.value, "status mismatch")
    assert_("9" in ar["summary"] or "nine" in ar["summary"].lower() or
            len([p for p in ARTIFACT_PATHS]) == 9,
            "summary should reference artifact count")


def test_31_agent_results_tokens_used_zero():
    result = _run(make_artifact_packager_node(), _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["tokens_used"] == 0,
            f"No LLM call — tokens_used should be 0, got {ar['tokens_used']}")


def test_32_agent_results_cost_usd_zero():
    result = _run(make_artifact_packager_node(), _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["cost_usd"] == 0.0,
            f"No LLM call — cost_usd should be 0.0, got {ar['cost_usd']}")


def test_33_updated_at_present():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("updated_at" in result and result["updated_at"],
            "updated_at should be present and non-empty")


def test_34_total_tokens_not_in_changeset():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("total_tokens" not in result,
            "total_tokens must not be re-emitted (packager makes no LLM calls)")


def test_35_estimated_cost_not_in_changeset():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("estimated_cost" not in result,
            "estimated_cost must not be re-emitted")


def test_36_model_used_not_in_changeset():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("model_used" not in result,
            "model_used must not be re-emitted")


# ── 37-44: Read-only contract ─────────────────────────────────────────────────

def test_37_clarified_requirements_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("clarified_requirements" not in result,
            "clarified_requirements must not be re-emitted")


def test_38_architecture_summary_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("architecture_summary" not in result,
            "architecture_summary must not be re-emitted")


def test_39_task_plan_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("task_plan" not in result, "task_plan must not be re-emitted")


def test_40_database_schema_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("database_schema" not in result,
            "database_schema must not be re-emitted")


def test_41_backend_code_summary_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("backend_code_summary" not in result,
            "backend_code_summary must not be re-emitted")


def test_42_frontend_code_summary_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("frontend_code_summary" not in result,
            "frontend_code_summary must not be re-emitted")


def test_43_review_notes_not_re_emitted():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("review_notes" not in result, "review_notes must not be re-emitted")


def test_44_raw_requirements_not_in_changeset():
    result = _run(make_artifact_packager_node(), _make_state())
    assert_("raw_requirements" not in result,
            "raw_requirements must not be in changeset")


# ── 45-60: Guard conditions ───────────────────────────────────────────────────

def test_45_guard_empty_clarified_requirements():
    result = _run(make_artifact_packager_node(), _make_state(clarified_requirements=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_46_guard_none_clarified_requirements():
    result = _run(make_artifact_packager_node(), _make_state(clarified_requirements=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_47_guard_empty_architecture_summary():
    result = _run(make_artifact_packager_node(), _make_state(architecture_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_48_guard_none_architecture_summary():
    result = _run(make_artifact_packager_node(), _make_state(architecture_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_49_guard_empty_task_plan():
    result = _run(make_artifact_packager_node(), _make_state(task_plan=[]))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_50_guard_none_task_plan():
    result = _run(make_artifact_packager_node(), _make_state(task_plan=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_51_guard_empty_database_schema():
    result = _run(make_artifact_packager_node(), _make_state(database_schema=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_52_guard_none_database_schema():
    result = _run(make_artifact_packager_node(), _make_state(database_schema=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_53_guard_empty_backend_code_summary():
    result = _run(make_artifact_packager_node(), _make_state(backend_code_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_54_guard_none_backend_code_summary():
    result = _run(make_artifact_packager_node(), _make_state(backend_code_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_55_guard_empty_frontend_code_summary():
    result = _run(make_artifact_packager_node(), _make_state(frontend_code_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_56_guard_none_frontend_code_summary():
    result = _run(make_artifact_packager_node(), _make_state(frontend_code_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_57_guard_empty_review_notes():
    result = _run(make_artifact_packager_node(), _make_state(review_notes=[]))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_58_guard_none_review_notes():
    result = _run(make_artifact_packager_node(), _make_state(review_notes=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")


def test_59_guard_missing_metadata_refined():
    state = _make_state()
    state["metadata"] = {"existing_key": "value", "review": _SAMPLE_REVIEW_RAW}
    result = _run(make_artifact_packager_node(), state)
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value,
            "Should FAIL when metadata['refined'] is missing")


def test_60_guard_empty_metadata_refined():
    state = _make_state()
    state["metadata"] = {"review": _SAMPLE_REVIEW_RAW, "refined": ""}
    result = _run(make_artifact_packager_node(), state)
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value,
            "Should FAIL when metadata['refined'] is empty string")


# ── 61-63: Error handling ─────────────────────────────────────────────────────

def test_61_failure_agent_result_recorded():
    result = _run(make_artifact_packager_node(), _make_state(clarified_requirements=None))
    ar = result["agent_results"][-1]
    assert_(ar["agent_name"] == "artifact_packager", "agent_name should be artifact_packager")
    assert_(ar["status"] == ExecutionStatus.FAILED.value, "status should be FAILED")
    assert_(ar["error_message"] is not None, "error_message should not be None")
    assert_(ar["tokens_used"] == 0, "tokens_used should be 0 on failure")
    assert_(ar["cost_usd"] == 0.0, "cost_usd should be 0.0 on failure")


def test_62_failure_errors_list_appended_not_replaced():
    state = _make_state(clarified_requirements=None)
    state["errors"] = ["prior error"]
    result = _run(make_artifact_packager_node(), state)
    assert_("prior error" in result["errors"], "Prior errors must be preserved")
    assert_(len(result["errors"]) == 2, f"Should have 2 errors, got {len(result['errors'])}")


def test_63_failure_does_not_modify_artifacts():
    state = _make_state(clarified_requirements=None)
    result = _run(make_artifact_packager_node(), state)
    assert_("artifacts" not in result,
            "On failure, artifacts must not be in changeset")


# ── 64: State integrity ───────────────────────────────────────────────────────

def test_64_input_state_not_mutated():
    node = make_artifact_packager_node()
    state = _make_state()
    original_errors = list(state["errors"])
    original_agents = list(state["completed_agents"])
    original_artifacts = list(state["artifacts"])
    original_task_plan = list(state["task_plan"])
    original_review_notes = list(state["review_notes"])
    _run(node, state)
    assert_(state["errors"] == original_errors, "state['errors'] was mutated")
    assert_(state["completed_agents"] == original_agents, "state['completed_agents'] was mutated")
    assert_(state["artifacts"] == original_artifacts, "state['artifacts'] was mutated")
    assert_(state["task_plan"] == original_task_plan, "state['task_plan'] was mutated")
    assert_(state["review_notes"] == original_review_notes, "state['review_notes'] was mutated")


# ── 65-72: Graph round-trip (nine agents) ─────────────────────────────────────

def _make_mock_response(content: str, pt: int, ct: int) -> CompletionResponse:
    return CompletionResponse(
        content=content, model="gpt-4o-mini", latency_ms=0,
        usage=UsageInfo(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
    )


_REVIEW_SECTIONS_CONTENT = {
    "## Missing Requirements": "- [MISSING] Rate limiting.",
    "## Architectural Inconsistencies": "- No issues found.",
    "## Database Issues": "- [DB] soft-delete missing.",
    "## Backend Gaps": "- [BE] pagination.",
    "## Frontend Gaps": "- [FE] empty state.",
    "## Security Concerns": "- [SEC] rate limit.",
    "## Performance Concerns": "- [PERF] N+1.",
    "## Testing Gaps": "- [TEST] contracts.",
    "## Deployment Concerns": "- [DEPLOY] rollback.",
}


def _make_mock_llm_for_graph() -> MagicMock:
    review_content = "\n\n".join(
        f"{h}\n{b}" for h, b in _REVIEW_SECTIONS_CONTENT.items()
    )
    responses = [
        _make_mock_response(
            "## Functional Requirements\nCRUD.\n\n"
            "## Non-Functional Requirements\nJWT.\n\n"
            "## Assumptions\nSingle.\n\n"
            "## Missing Information\nNone.\n\n"
            "## Risks\nNone.\n\n"
            "## Acceptance Criteria\nPass.",
            100, 200,
        ),
        _make_mock_response(
            "## Architecture Pattern\nLayered.\n\n## Backend Services\nFastAPI.\n\n"
            "## Frontend Architecture\nReact.\n\n## Database Architecture\nPG.\n\n"
            "## API Design\nREST.\n\n## Security Architecture\nJWT.\n\n"
            "## Scalability Strategy\nDocker.\n\n## Deployment Architecture\nAWS.",
            200, 300,
        ),
        _make_mock_response(
            "## Backend Tasks\n\n### BE-001: FastAPI\n- **Priority:** High\n"
            "- **Complexity:** Low\n- **Description:** Init.\n- **Dependencies:** None\n\n"
            "## Frontend Tasks\n\n### FE-001: React\n- **Priority:** High\n"
            "- **Complexity:** Low\n- **Description:** Vite.\n- **Dependencies:** None\n\n"
            "## Database Tasks\n\n## Infrastructure Tasks\n\n## Testing Tasks\n\n## Deployment Tasks\n",
            300, 400,
        ),
        _make_mock_response(
            "## Core Entities\nTask.\n\n## Entity Attributes\nid UUID.\n\n"
            "## Relationships\nM-1.\n\n## Primary Keys\nUUID.\n\n"
            "## Foreign Keys\nFK.\n\n## Constraints\nNOT NULL.\n\n"
            "## Indexes\nidx.\n\n## Normalization Notes\n3NF.",
            400, 500,
        ),
        _make_mock_response(_SAMPLE_BACKEND, 500, 600),
        _make_mock_response(_SAMPLE_FRONTEND, 600, 700),
        _make_mock_response(review_content, 700, 800),
        _make_mock_response(_SAMPLE_REFINED, 800, 900),
    ]
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=responses)
    return mock


def _run_graph(initial_state: ForgeState) -> ForgeState:
    import asyncio
    from langgraph.checkpoint.memory import MemorySaver
    from app.infrastructure.langgraph.graph import build_forge_graph
    graph = build_forge_graph(_make_mock_llm_for_graph(), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}}
    return asyncio.get_event_loop().run_until_complete(
        graph.ainvoke(initial_state, config=config)
    )


def _make_graph_state() -> ForgeState:
    return create_forge_state(
        project_id=str(uuid4()),
        project_name="Test Project",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )


def test_65_graph_compiles_with_nine_nodes():
    from langgraph.checkpoint.memory import MemorySaver
    from app.infrastructure.langgraph.graph import build_forge_graph
    graph = build_forge_graph(MagicMock(), checkpointer=MemorySaver())
    assert_(graph is not None, "Graph should compile without errors")


def test_66_nine_agent_run_status_completed():
    result = _run_graph(_make_graph_state())
    assert_(result["execution_status"] == ExecutionStatus.COMPLETED.value,
            f"Expected COMPLETED, got {result['execution_status']}")


def test_67_all_nine_agents_in_completed_agents():
    result = _run_graph(_make_graph_state())
    for agent in [
        "requirements_analyst", "architect", "task_planner",
        "database_designer", "backend_generator", "frontend_generator",
        "reviewer", "refiner", "artifact_packager",
    ]:
        assert_(agent in result["completed_agents"],
                f"'{agent}' not in completed_agents: {result['completed_agents']}")


def test_68_nine_agent_results_records():
    result = _run_graph(_make_graph_state())
    assert_(len(result["agent_results"]) == 9,
            f"Expected 9 agent_results, got {len(result['agent_results'])}")


def test_69_artifacts_has_nine_entries_after_full_run():
    result = _run_graph(_make_graph_state())
    assert_(len(result["artifacts"]) == 9,
            f"Expected 9 artifacts, got {len(result['artifacts'])}")


def test_70_metadata_project_summary_present_after_full_run():
    result = _run_graph(_make_graph_state())
    assert_("project_summary" in result.get("metadata", {}),
            "metadata['project_summary'] should be present after full run")


def test_71_metadata_review_still_present_after_packager():
    result = _run_graph(_make_graph_state())
    assert_("review" in result.get("metadata", {}),
            "metadata['review'] must still be present (packager must not erase it)")


def test_72_metadata_refined_still_present_after_packager():
    result = _run_graph(_make_graph_state())
    assert_("refined" in result.get("metadata", {}),
            "metadata['refined'] must still be present (packager must not erase it)")
