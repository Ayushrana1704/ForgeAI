"""
Tests for the Reviewer agent.

Coverage
--------
Prompt builder
 1. Returns two messages
 2. First message is SYSTEM role
 3. Second message is USER role
 4. User message contains CLARIFIED REQUIREMENTS block
 5. User message contains SOFTWARE ARCHITECTURE block
 6. User message contains TASK PLAN SUMMARY block
 7. User message contains DATABASE SCHEMA block
 8. User message contains BACKEND BLUEPRINT block
 9. User message contains FRONTEND BLUEPRINT block
10. System prompt contains all nine required section headings

_format_task_plan_summary helper
11. Groups tasks by category
12. Includes task id, title, priority in output
13. Skips malformed JSON entries silently
14. Returns placeholder when task_plan is empty
15. Multiple categories appear in sorted order

_parse_review_sections helper
16. Returns a list with one element per REQUIRED_SECTIONS entry
17. Each element begins with the correct H2 heading
18. Missing section replaced with "No issues found." placeholder
19. Section body is correctly extracted (no next-heading bleed)
20. Last section (no trailing H2) extracted correctly

Node success
21. execution_status → COMPLETED
22. review_notes is a non-empty list
23. len(review_notes) equals len(REQUIRED_SECTIONS)
24. metadata["review"] equals the full raw LLM content
25. Existing metadata keys preserved (merge, not replace)
26. current_agent → "reviewer"
27. completed_agents appended (prior agents preserved)
28. agent_results appended with correct shape (agent_name, status, tokens)
29. total_tokens incremented
30. estimated_cost incremented
31. model_used set from response
32. updated_at present

Read-only contract — prior fields NOT in changeset
33. clarified_requirements not re-emitted
34. architecture_summary not re-emitted
35. task_plan not re-emitted
36. database_schema not re-emitted
37. backend_code_summary not re-emitted
38. frontend_code_summary not re-emitted
39. raw_requirements not in changeset

Guard conditions
40. Empty clarified_requirements → FAILED, no LLM call
41. None clarified_requirements → FAILED, no LLM call
42. Empty architecture_summary → FAILED, no LLM call
43. None architecture_summary → FAILED, no LLM call
44. Empty task_plan list → FAILED, no LLM call
45. None task_plan → FAILED, no LLM call
46. Empty database_schema → FAILED, no LLM call
47. None database_schema → FAILED, no LLM call
48. Empty backend_code_summary → FAILED, no LLM call
49. None backend_code_summary → FAILED, no LLM call
50. Empty frontend_code_summary → FAILED, no LLM call
51. None frontend_code_summary → FAILED, no LLM call

Error handling
52. LLMUnavailableException → FAILED, "unavailable" in error
53. LLMException → FAILED, detail in errors list
54. Unexpected exception → FAILED, class name in errors list
55. Failure path: failed AgentResult recorded with error_message
56. Failure path: errors list appended (not replaced)

State integrity
57. Input state dict not mutated

Graph round-trip (seven agents)
58. build_forge_graph compiles with seven nodes
59. Seven-agent ainvoke → execution_status COMPLETED
60. All seven agents in completed_agents
61. Seven agent_results records
62. review_notes non-empty after full run
63. metadata["review"] present after full run
64. Total tokens accumulate across all seven agents
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.prompts.reviewer import (
    REQUIRED_SECTIONS,
    SECTION_ARCH_INCONSISTENCIES,
    SECTION_DEPLOYMENT_CONCERNS,
    SECTION_MISSING_REQUIREMENTS,
    SECTION_SECURITY_CONCERNS,
    build_reviewer_messages,
)
from app.application.services.llm.types import (
    CompletionResponse,
    MessageRole,
    UsageInfo,
)
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.reviewer import (
    _extract_section,
    _format_task_plan_summary,
    _parse_review_sections,
    make_reviewer_node,
)

# ── Sample fixtures ───────────────────────────────────────────────────────────

_SAMPLE_REQUIREMENTS = "Build a task management REST API with React frontend."

_SAMPLE_CLARIFIED = (
    "## Functional Requirements\nCRUD tasks.\n\n"
    "## Non-Functional Requirements\nJWT auth, < 200ms p99.\n\n"
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
    "## Entity Attributes\nTask: id UUID PK, title VARCHAR(255).\n\n"
    "## Relationships\nMany-to-one.\n\n"
    "## Primary Keys\nUUID PKs.\n\n"
    "## Foreign Keys\ntasks.user_id → users.id.\n\n"
    "## Constraints\nNOT NULL on title.\n\n"
    "## Indexes\nidx_tasks_user_id.\n\n"
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
                "description": "Create migration.", "dependencies": []}),
]

# Build a valid review document with all 9 sections
_REVIEW_SECTIONS_CONTENT = {
    "## Missing Requirements": "- [MISSING] Rate limiting spec — security risk.",
    "## Architectural Inconsistencies": "- No issues found.",
    "## Database Issues": "- [DB] tasks: missing soft-delete column.",
    "## Backend Gaps": "- [BE] /tasks: missing pagination.",
    "## Frontend Gaps": "- [FE] TaskList: missing empty-state component.",
    "## Security Concerns": "- [SEC] API: no rate limiting — add Redis throttle.",
    "## Performance Concerns": "- [PERF] tasks query: N+1 risk on user join.",
    "## Testing Gaps": "- [TEST] Backend: no contract tests.",
    "## Deployment Concerns": "- [DEPLOY] DB: no migration rollback plan.",
}

_SAMPLE_REVIEW = "\n\n".join(
    f"{heading}\n{body}"
    for heading, body in _REVIEW_SECTIONS_CONTENT.items()
)


def assert_(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _make_mock_llm(content: str = _SAMPLE_REVIEW, model: str = "gpt-4o-mini") -> MagicMock:
    usage = UsageInfo(prompt_tokens=800, completion_tokens=600, total_tokens=1400)
    response = CompletionResponse(content=content, model=model, usage=usage, latency_ms=0)
    mock = MagicMock()
    mock.complete = AsyncMock(return_value=response)
    return mock


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
    state["completed_agents"] = [
        "requirements_analyst", "architect", "task_planner",
        "database_designer", "backend_generator", "frontend_generator",
    ]
    state["total_tokens"] = 6000
    state["estimated_cost"] = 0.005
    state["metadata"] = {"existing_key": "existing_value"}
    for k, v in overrides.items():
        state[k] = v
    return state


def _run(node_fn: Any, state: ForgeState) -> dict[str, Any]:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(node_fn(state))


# ── 1-10: Prompt builder ──────────────────────────────────────────────────────

def test_01_prompt_returns_two_messages():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "tasks here",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_(len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}")


def test_02_first_message_is_system():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_(msgs[0].role == MessageRole.SYSTEM, f"Expected SYSTEM, got {msgs[0].role}")


def test_03_second_message_is_user():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_(msgs[1].role == MessageRole.USER, f"Expected USER, got {msgs[1].role}")


def test_04_user_message_contains_requirements_block():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_("CLARIFIED REQUIREMENTS" in msgs[1].content, "Missing CLARIFIED REQUIREMENTS")


def test_05_user_message_contains_architecture_block():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_("SOFTWARE ARCHITECTURE" in msgs[1].content, "Missing SOFTWARE ARCHITECTURE")


def test_06_user_message_contains_task_plan_block():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "- [High] BE-001: FastAPI setup",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_("TASK PLAN SUMMARY" in msgs[1].content, "Missing TASK PLAN SUMMARY")


def test_07_user_message_contains_database_schema_block():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_("DATABASE SCHEMA" in msgs[1].content, "Missing DATABASE SCHEMA")


def test_08_user_message_contains_backend_blueprint_block():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_("BACKEND BLUEPRINT" in msgs[1].content, "Missing BACKEND BLUEPRINT")


def test_09_user_message_contains_frontend_blueprint_block():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    assert_("FRONTEND BLUEPRINT" in msgs[1].content, "Missing FRONTEND BLUEPRINT")


def test_10_system_prompt_contains_all_required_sections():
    msgs = build_reviewer_messages(
        _SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x",
        _SAMPLE_DB_SCHEMA, _SAMPLE_BACKEND, _SAMPLE_FRONTEND,
    )
    system_content = msgs[0].content
    for section in REQUIRED_SECTIONS:
        assert_(section in system_content, f"System prompt missing section: {section}")


# ── 11-15: _format_task_plan_summary ─────────────────────────────────────────

def test_11_groups_tasks_by_category():
    result = _format_task_plan_summary(_SAMPLE_TASK_PLAN)
    assert_("Backend" in result, "Backend category missing")
    assert_("Frontend" in result, "Frontend category missing")
    assert_("Database" in result, "Database category missing")


def test_12_includes_task_id_title_priority():
    plan = [json.dumps({"id": "BE-001", "title": "FastAPI setup", "category": "Backend",
                        "priority": "High", "complexity": "Low",
                        "description": "Init.", "dependencies": []})]
    result = _format_task_plan_summary(plan)
    assert_("BE-001" in result, "Task id missing")
    assert_("FastAPI setup" in result, "Task title missing")
    assert_("High" in result, "Priority missing")


def test_13_skips_malformed_json_silently():
    plan = ["not-json"] + _SAMPLE_TASK_PLAN
    result = _format_task_plan_summary(plan)
    assert_("BE-001" in result, "Valid tasks should still appear after malformed entry")


def test_14_returns_placeholder_when_task_plan_empty():
    result = _format_task_plan_summary([])
    assert_("No task plan available" in result, f"Expected placeholder, got: {result!r}")


def test_15_categories_appear_in_sorted_order():
    result = _format_task_plan_summary(_SAMPLE_TASK_PLAN)
    # Backend < Database < Frontend alphabetically
    be_pos = result.index("Backend")
    db_pos = result.index("Database")
    fe_pos = result.index("Frontend")
    assert_(be_pos < db_pos < fe_pos,
            f"Expected sorted order: Backend({be_pos}) < Database({db_pos}) < Frontend({fe_pos})")


# ── 16-20: _parse_review_sections ────────────────────────────────────────────

def test_16_returns_list_with_one_element_per_required_section():
    result = _parse_review_sections(_SAMPLE_REVIEW)
    assert_(len(result) == len(REQUIRED_SECTIONS),
            f"Expected {len(REQUIRED_SECTIONS)} sections, got {len(result)}")


def test_17_each_element_begins_with_correct_h2_heading():
    result = _parse_review_sections(_SAMPLE_REVIEW)
    for i, section in enumerate(REQUIRED_SECTIONS):
        assert_(result[i].startswith(section),
                f"Section {i} should start with '{section}', got: {result[i][:40]!r}")


def test_18_missing_section_gets_placeholder():
    # Only include one section in the doc
    partial = "## Missing Requirements\n- [MISSING] Something important."
    result = _parse_review_sections(partial)
    # All other sections should have the placeholder
    for i, section in enumerate(REQUIRED_SECTIONS[1:], start=1):
        assert_("No issues found." in result[i],
                f"Section {i} ({section}) should have placeholder, got: {result[i]!r}")


def test_19_section_body_does_not_bleed_into_next():
    result = _parse_review_sections(_SAMPLE_REVIEW)
    # The "Missing Requirements" section should not contain content from "Architectural Inconsistencies"
    mr_section = result[0]
    assert_("Architectural Inconsistencies" not in mr_section,
            "Section body bleeds into next section")


def test_20_last_section_extracted_correctly():
    result = _parse_review_sections(_SAMPLE_REVIEW)
    last = result[-1]
    assert_(SECTION_DEPLOYMENT_CONCERNS in last, "Last section heading missing")
    assert_("No migration rollback" in last or "DEPLOY" in last,
            f"Last section content missing, got: {last!r}")


# ── 21-32: Node success ───────────────────────────────────────────────────────

def test_21_success_execution_status_completed():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["execution_status"] == ExecutionStatus.COMPLETED.value,
            f"Expected COMPLETED, got {result['execution_status']}")


def test_22_review_notes_is_nonempty_list():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    rn = result.get("review_notes")
    assert_(isinstance(rn, list) and len(rn) > 0,
            f"review_notes should be a non-empty list, got: {rn!r}")


def test_23_review_notes_length_equals_required_sections():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(len(result["review_notes"]) == len(REQUIRED_SECTIONS),
            f"Expected {len(REQUIRED_SECTIONS)} review_notes, got {len(result['review_notes'])}")


def test_24_metadata_review_equals_full_raw_content():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["metadata"].get("review") == _SAMPLE_REVIEW.strip(),
            "metadata['review'] should equal full raw LLM response")


def test_25_metadata_merge_preserves_existing_keys():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["metadata"].get("existing_key") == "existing_value",
            "Existing metadata keys must be preserved")


def test_26_current_agent():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["current_agent"] == "reviewer",
            f"Expected 'reviewer', got {result['current_agent']}")


def test_27_completed_agents_appended():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("reviewer" in result["completed_agents"],
            "reviewer should be in completed_agents")
    assert_("frontend_generator" in result["completed_agents"],
            "Prior agents must be preserved")


def test_28_agent_results_shape():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["agent_name"] == "reviewer", "agent_name mismatch")
    assert_(ar["status"] == ExecutionStatus.COMPLETED.value, "status mismatch")
    assert_(ar["tokens_used"] == 1400, f"tokens_used mismatch: {ar['tokens_used']}")


def test_29_total_tokens_incremented():
    node = make_reviewer_node(_make_mock_llm())
    state = _make_state()
    prior = state["total_tokens"]
    result = _run(node, state)
    assert_(result["total_tokens"] == prior + 1400,
            f"Expected {prior + 1400}, got {result['total_tokens']}")


def test_30_estimated_cost_incremented():
    node = make_reviewer_node(_make_mock_llm())
    state = _make_state()
    prior = state["estimated_cost"]
    result = _run(node, state)
    assert_(result["estimated_cost"] > prior, "estimated_cost should increase")


def test_31_model_used_set():
    node = make_reviewer_node(_make_mock_llm(model="gpt-4o-mini"))
    result = _run(node, _make_state())
    assert_(result["model_used"] == "gpt-4o-mini",
            f"Expected 'gpt-4o-mini', got {result['model_used']}")


def test_32_updated_at_present():
    node = make_reviewer_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("updated_at" in result and result["updated_at"],
            "updated_at should be present and non-empty")


# ── 33-39: Read-only contract ─────────────────────────────────────────────────

def test_33_clarified_requirements_not_re_emitted():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("clarified_requirements" not in result, "clarified_requirements must not be re-emitted")


def test_34_architecture_summary_not_re_emitted():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("architecture_summary" not in result, "architecture_summary must not be re-emitted")


def test_35_task_plan_not_re_emitted():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("task_plan" not in result, "task_plan must not be re-emitted")


def test_36_database_schema_not_re_emitted():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("database_schema" not in result, "database_schema must not be re-emitted")


def test_37_backend_code_summary_not_re_emitted():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("backend_code_summary" not in result, "backend_code_summary must not be re-emitted")


def test_38_frontend_code_summary_not_re_emitted():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("frontend_code_summary" not in result, "frontend_code_summary must not be re-emitted")


def test_39_raw_requirements_not_in_changeset():
    result = _run(make_reviewer_node(_make_mock_llm()), _make_state())
    assert_("raw_requirements" not in result, "raw_requirements must not be in changeset")


# ── 40-51: Guard conditions ───────────────────────────────────────────────────

def test_40_guard_empty_clarified_requirements():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(clarified_requirements=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_41_guard_none_clarified_requirements():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(clarified_requirements=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_42_guard_empty_architecture_summary():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(architecture_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_43_guard_none_architecture_summary():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(architecture_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_44_guard_empty_task_plan():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(task_plan=[]))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_45_guard_none_task_plan():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(task_plan=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_46_guard_empty_database_schema():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(database_schema=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_47_guard_none_database_schema():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(database_schema=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_48_guard_empty_backend_code_summary():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(backend_code_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_49_guard_none_backend_code_summary():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(backend_code_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_50_guard_empty_frontend_code_summary():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(frontend_code_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_51_guard_none_frontend_code_summary():
    mock = _make_mock_llm()
    node = make_reviewer_node(mock)
    result = _run(node, _make_state(frontend_code_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


# ── 52-56: Error handling ─────────────────────────────────────────────────────

def test_52_llm_unavailable_exception():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMUnavailableException("OpenAI down"))
    result = _run(make_reviewer_node(mock), _make_state())
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    assert_(any("unavailable" in e.lower() for e in result["errors"]),
            f"'unavailable' should appear in errors: {result['errors']}")


def test_53_llm_exception():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMException("rate limit hit"))
    result = _run(make_reviewer_node(mock), _make_state())
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    assert_(any("rate limit hit" in e for e in result["errors"]),
            f"Detail should appear in errors: {result['errors']}")


def test_54_unexpected_exception():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=RuntimeError("disk full"))
    result = _run(make_reviewer_node(mock), _make_state())
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    assert_(any("RuntimeError" in e for e in result["errors"]),
            f"Class name should appear in errors: {result['errors']}")


def test_55_failure_agent_result_recorded():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMException("oops"))
    result = _run(make_reviewer_node(mock), _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["agent_name"] == "reviewer", "agent_name should be reviewer")
    assert_(ar["status"] == ExecutionStatus.FAILED.value, "status should be FAILED")
    assert_(ar["error_message"] is not None, "error_message should not be None")
    assert_(ar["tokens_used"] == 0, "tokens_used should be 0 on failure")


def test_56_failure_errors_list_appended_not_replaced():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMException("oops"))
    state = _make_state()
    state["errors"] = ["prior error"]
    result = _run(make_reviewer_node(mock), state)
    assert_("prior error" in result["errors"], "Prior errors must be preserved")
    assert_(len(result["errors"]) == 2, f"Should have 2 errors, got {len(result['errors'])}")


# ── 57: State integrity ───────────────────────────────────────────────────────

def test_57_input_state_not_mutated():
    node = make_reviewer_node(_make_mock_llm())
    state = _make_state()
    original_errors = list(state["errors"])
    original_agents = list(state["completed_agents"])
    original_review_notes = list(state["review_notes"])
    _run(node, state)
    assert_(state["errors"] == original_errors, "state['errors'] was mutated")
    assert_(state["completed_agents"] == original_agents, "state['completed_agents'] was mutated")
    assert_(state["review_notes"] == original_review_notes, "state['review_notes'] was mutated")


# ── 58-64: Graph round-trip (seven agents) ────────────────────────────────────

def _make_mock_llm_for_graph() -> MagicMock:
    def mk(content: str, pt: int, ct: int) -> CompletionResponse:
        return CompletionResponse(
            content=content, model="gpt-4o-mini", latency_ms=0,
            usage=UsageInfo(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
        )

    ra = mk(
        "## Functional Requirements\nCRUD tasks.\n\n"
        "## Non-Functional Requirements\nJWT.\n\n"
        "## Assumptions\nSingle-tenant.\n\n"
        "## Missing Information\nNone.\n\n"
        "## Risks\nNone.\n\n"
        "## Acceptance Criteria\nAll pass.",
        100, 200,
    )
    sa = mk(
        "## Architecture Pattern\nLayered.\n\n## Backend Services\nFastAPI.\n\n"
        "## Frontend Architecture\nReact.\n\n## Database Architecture\nPG.\n\n"
        "## API Design\nREST.\n\n## Security Architecture\nJWT.\n\n"
        "## Scalability Strategy\nDocker.\n\n## Deployment Architecture\nAWS.",
        200, 300,
    )
    tp = mk(
        "## Backend Tasks\n\n### BE-001: FastAPI\n- **Priority:** High\n"
        "- **Complexity:** Low\n- **Description:** Init.\n- **Dependencies:** None\n\n"
        "## Frontend Tasks\n\n### FE-001: React\n- **Priority:** High\n"
        "- **Complexity:** Low\n- **Description:** Init Vite.\n- **Dependencies:** None\n\n"
        "## Database Tasks\n\n### DB-001: Users\n- **Priority:** High\n"
        "- **Complexity:** Low\n- **Description:** Migration.\n- **Dependencies:** None\n\n"
        "## Infrastructure Tasks\n\n## Testing Tasks\n\n## Deployment Tasks\n",
        300, 400,
    )
    dd = mk(
        "## Core Entities\nTask.\n\n## Entity Attributes\nTask: id UUID.\n\n"
        "## Relationships\nMany-to-one.\n\n## Primary Keys\nUUID.\n\n"
        "## Foreign Keys\ntasks.user_id.\n\n## Constraints\nNOT NULL.\n\n"
        "## Indexes\nidx.\n\n## Normalization Notes\n3NF.",
        400, 500,
    )
    bg = mk(_SAMPLE_BACKEND, 500, 600)
    fg = mk(_SAMPLE_FRONTEND, 600, 700)
    rv = mk(_SAMPLE_REVIEW, 700, 800)

    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=[ra, sa, tp, dd, bg, fg, rv])
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


def test_58_graph_compiles_with_seven_nodes():
    from langgraph.checkpoint.memory import MemorySaver
    from app.infrastructure.langgraph.graph import build_forge_graph
    graph = build_forge_graph(_make_mock_llm(), checkpointer=MemorySaver())
    assert_(graph is not None, "Graph should compile without errors")


def test_59_seven_agent_run_status_completed():
    result = _run_graph(_make_graph_state())
    assert_(result["execution_status"] == ExecutionStatus.COMPLETED.value,
            f"Expected COMPLETED, got {result['execution_status']}")


def test_60_all_seven_agents_in_completed_agents():
    result = _run_graph(_make_graph_state())
    for agent in [
        "requirements_analyst", "architect", "task_planner",
        "database_designer", "backend_generator", "frontend_generator",
        "reviewer",
    ]:
        assert_(agent in result["completed_agents"],
                f"'{agent}' not in completed_agents: {result['completed_agents']}")


def test_61_seven_agent_results_records():
    result = _run_graph(_make_graph_state())
    assert_(len(result["agent_results"]) == 7,
            f"Expected 7 agent_results, got {len(result['agent_results'])}")


def test_62_review_notes_nonempty_after_full_run():
    result = _run_graph(_make_graph_state())
    rn = result.get("review_notes")
    assert_(isinstance(rn, list) and len(rn) > 0,
            f"review_notes should be a non-empty list, got: {rn!r}")


def test_63_metadata_review_present_after_full_run():
    result = _run_graph(_make_graph_state())
    assert_("review" in result.get("metadata", {}),
            "metadata['review'] should be present after full run")


def test_64_total_tokens_accumulate():
    result = _run_graph(_make_graph_state())
    # 300+500+700+900+1100+1300+1500 = 6300
    assert_(result["total_tokens"] >= 6300,
            f"Expected total_tokens >= 6300, got {result['total_tokens']}")
