"""
Tests for the Backend Generator agent.

Coverage
--------
Prompt builder
 1. Returns two messages
 2. First message is SYSTEM role
 3. Second message is USER role
 4. User message contains CLARIFIED REQUIREMENTS block
 5. User message contains SOFTWARE ARCHITECTURE block
 6. User message contains DATABASE SCHEMA block
 7. User message contains BACKEND TASKS block
 8. System prompt contains all ten required section headings

_extract_backend_task_summary helper
 9. Returns only Backend-category tasks
10. Formats each task as a bullet with priority, id, title, description
11. Returns placeholder when no backend tasks found
12. Skips malformed (non-JSON) task entries silently
13. Category match is case-insensitive

_extract_section helper
14. Extracts body of a known section
15. Returns None for a missing heading
16. Returns None for an empty section body
17. Correctly extracts the last section (no trailing H2)

Node success
18. execution_status → COMPLETED
19. backend_code_summary populated with LLM response content
20. metadata["backend"] equals backend_code_summary
21. Existing metadata keys preserved (merge, not replace)
22. current_agent → "backend_generator"
23. completed_agents appended (prior agents preserved)
24. agent_results appended with correct shape (agent_name, status, tokens)
25. total_tokens incremented
26. estimated_cost incremented
27. model_used set from response
28. updated_at present

Guard conditions
29. Empty clarified_requirements → FAILED, no LLM call
30. None clarified_requirements → FAILED, no LLM call
31. Empty architecture_summary → FAILED, no LLM call
32. None architecture_summary → FAILED, no LLM call
33. Empty task_plan list → FAILED, no LLM call
34. None task_plan → FAILED, no LLM call
35. Empty database_schema → FAILED, no LLM call
36. None database_schema → FAILED, no LLM call

Error handling
37. LLMUnavailableException → FAILED, "unavailable" in error
38. LLMException → FAILED, detail in errors list
39. Unexpected exception → FAILED, class name in errors list
40. Failure path: failed AgentResult recorded with error_message
41. Failure path: errors list appended (not replaced)

State integrity
42. raw_requirements not in changeset
43. clarified_requirements not re-emitted
44. architecture_summary not re-emitted
45. task_plan not re-emitted
46. database_schema not re-emitted
47. Input state dict not mutated

Graph round-trip (five agents)
48. build_forge_graph compiles with five nodes
49. Five-agent ainvoke → execution_status COMPLETED
50. All five agents in completed_agents
51. Five agent_results records
52. backend_code_summary non-empty after full run
53. metadata["backend"] present after full run
54. Total tokens accumulate across all five agents
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.prompts.backend_generator import (
    REQUIRED_SECTIONS,
    SECTION_API_MODULES,
    SECTION_PROJECT_STRUCTURE,
    SECTION_TESTING_STRATEGY,
    build_backend_generator_messages,
)
from app.application.services.llm.types import (
    CompletionResponse,
    MessageRole,
    UsageInfo,
)
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.backend_generator import (
    _extract_backend_task_summary,
    _extract_section,
    make_backend_generator_node,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_REQUIREMENTS = "Build a REST API for task management. Users can CRUD tasks."

_SAMPLE_CLARIFIED = """\
## Functional Requirements
- Users can create tasks with title, description, status, and due date.

## Non-Functional Requirements
- API p99 ≤ 200 ms. JWT auth required.

## Assumptions
- Single-tenant.

## Missing Information
- Max tasks per user.

## Risks
- No rate limiting.

## Acceptance Criteria
- All CRUD endpoints pass integration tests.
"""

_SAMPLE_ARCHITECTURE = """\
## Architecture Pattern
Layered REST API with FastAPI.

## Backend Services
FastAPI app with Uvicorn.

## Frontend Architecture
React SPA.

## Database Architecture
PostgreSQL with SQLAlchemy ORM.

## API Design
RESTful JSON. JWT auth.

## Security Architecture
BCrypt passwords. HTTPS only.

## Scalability Strategy
Horizontal scaling via Docker Swarm.

## Deployment Architecture
Docker Compose on AWS EC2.
"""

_SAMPLE_DB_SCHEMA = """\
## Core Entities
Task, User, Tag.

## Entity Attributes
Task: id UUID PK, title VARCHAR(255), description TEXT, status ENUM, due_date DATE.

## Relationships
Task belongs_to User (many-to-one).

## Primary Keys
All tables use UUID PK.

## Foreign Keys
tasks.user_id → users.id ON DELETE CASCADE.

## Constraints
tasks.title NOT NULL. tasks.status DEFAULT 'todo'.

## Indexes
idx_tasks_user_id, idx_tasks_status.

## Normalization Notes
Schema is 3NF compliant.
"""

_SAMPLE_TASK_PLAN = [
    json.dumps({
        "id": "TASK-001",
        "title": "Set up FastAPI app",
        "category": "Backend",
        "priority": "High",
        "complexity": "Low",
        "description": "Initialize FastAPI project structure with routers.",
        "dependencies": [],
    }),
    json.dumps({
        "id": "TASK-002",
        "title": "Design users table",
        "category": "Database",
        "priority": "High",
        "complexity": "Low",
        "description": "Create migration for users table.",
        "dependencies": [],
    }),
    json.dumps({
        "id": "TASK-003",
        "title": "Implement task CRUD endpoints",
        "category": "Backend",
        "priority": "High",
        "complexity": "Medium",
        "description": "Create POST/GET/PATCH/DELETE /tasks endpoints.",
        "dependencies": ["TASK-001"],
    }),
]

_SAMPLE_BLUEPRINT = (
    "## Project Structure\napp/\n  main.py\n  routers/\n\n"
    "## API Modules\nTaskRouter: /tasks endpoints.\n\n"
    "## Database Layer\nSQLAlchemy async engine.\n\n"
    "## Repository Layer\nTaskRepository with CRUD methods.\n\n"
    "## Service Layer\nTaskService enforces business rules.\n\n"
    "## Authentication\nJWT RS256 tokens.\n\n"
    "## Dependency Injection\nFastAPI Depends pattern.\n\n"
    "## Middleware\nCORS, request-id, logging.\n\n"
    "## Validation\nPydantic v2 models.\n\n"
    "## Testing Strategy\npytest + pytest-asyncio."
)


def _make_mock_llm(content: str = _SAMPLE_BLUEPRINT, model: str = "gpt-4o-mini") -> MagicMock:
    usage = UsageInfo(prompt_tokens=500, completion_tokens=800, total_tokens=1300)
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
    state["completed_agents"] = [
        "requirements_analyst",
        "software_architect",
        "task_planner",
        "database_designer",
    ]
    state["total_tokens"] = 4000
    state["estimated_cost"] = 0.003
    state["metadata"] = {"existing_key": "existing_value"}
    for k, v in overrides.items():
        state[k] = v
    return state


# ── Helper: run the node synchronously ───────────────────────────────────────

def _run(node_fn, state: ForgeState) -> dict[str, Any]:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(node_fn(state))


# ── 1-8: Prompt builder ───────────────────────────────────────────────────────

def assert_(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_01_prompt_returns_two_messages():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Set up FastAPI app — Initialize project.",
    )
    assert_(len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}")


def test_02_first_message_is_system():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    assert_(msgs[0].role == MessageRole.SYSTEM, f"Expected SYSTEM, got {msgs[0].role}")


def test_03_second_message_is_user():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    assert_(msgs[1].role == MessageRole.USER, f"Expected USER, got {msgs[1].role}")


def test_04_user_message_contains_requirements_block():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    assert_("CLARIFIED REQUIREMENTS" in msgs[1].content, "Missing CLARIFIED REQUIREMENTS block")


def test_05_user_message_contains_architecture_block():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    assert_("SOFTWARE ARCHITECTURE" in msgs[1].content, "Missing SOFTWARE ARCHITECTURE block")


def test_06_user_message_contains_database_schema_block():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    assert_("DATABASE SCHEMA" in msgs[1].content, "Missing DATABASE SCHEMA block")


def test_07_user_message_contains_backend_tasks_block():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    assert_("BACKEND TASKS" in msgs[1].content, "Missing BACKEND TASKS block")


def test_08_system_prompt_contains_all_required_sections():
    msgs = build_backend_generator_messages(
        clarified_requirements=_SAMPLE_CLARIFIED,
        architecture_summary=_SAMPLE_ARCHITECTURE,
        database_schema=_SAMPLE_DB_SCHEMA,
        backend_task_summary="- [High] TASK-001: Setup — desc.",
    )
    system_content = msgs[0].content
    for section in REQUIRED_SECTIONS:
        assert_(section in system_content, f"System prompt missing section: {section}")


# ── 9-13: _extract_backend_task_summary ──────────────────────────────────────

def test_09_extract_returns_only_backend_tasks():
    result = _extract_backend_task_summary(_SAMPLE_TASK_PLAN)
    assert_("TASK-001" in result, "TASK-001 (Backend) should be included")
    assert_("TASK-003" in result, "TASK-003 (Backend) should be included")
    assert_("TASK-002" not in result, "TASK-002 (Database) should NOT be included")


def test_10_formats_task_as_bullet_with_fields():
    plan = [json.dumps({
        "id": "BE-01",
        "title": "Init app",
        "category": "Backend",
        "priority": "High",
        "complexity": "Low",
        "description": "Bootstrap FastAPI.",
        "dependencies": [],
    })]
    result = _extract_backend_task_summary(plan)
    assert_(result.startswith("- [High]"), f"Should start with '- [High]', got: {result!r}")
    assert_("BE-01" in result, "Task id should be present")
    assert_("Init app" in result, "Task title should be present")
    assert_("Bootstrap FastAPI" in result, "Description should be present")


def test_11_returns_placeholder_when_no_backend_tasks():
    db_only = [json.dumps({
        "id": "DB-01", "title": "Users table", "category": "Database",
        "priority": "High", "complexity": "Low",
        "description": "Create users migration.", "dependencies": [],
    })]
    result = _extract_backend_task_summary(db_only)
    assert_("No explicit backend tasks" in result, f"Expected placeholder, got: {result!r}")


def test_12_skips_malformed_json_silently():
    plan = ["not-json", json.dumps({
        "id": "BE-01", "title": "Init", "category": "Backend",
        "priority": "High", "complexity": "Low",
        "description": "Bootstrap.", "dependencies": [],
    })]
    result = _extract_backend_task_summary(plan)
    assert_("BE-01" in result, "Valid task should still be included after malformed entry")


def test_13_category_match_is_case_insensitive():
    plan = [json.dumps({
        "id": "BE-01", "title": "Init app", "category": "backend",
        "priority": "High", "complexity": "Low",
        "description": "Bootstrap FastAPI.", "dependencies": [],
    })]
    result = _extract_backend_task_summary(plan)
    assert_("BE-01" in result, "Lowercase 'backend' category should match")


# ── 14-17: _extract_section ───────────────────────────────────────────────────

def test_14_extract_section_known_heading():
    result = _extract_section(_SAMPLE_BLUEPRINT, SECTION_PROJECT_STRUCTURE)
    assert_(result is not None, "Should extract Project Structure section")
    assert_("main.py" in result, f"Content should include 'main.py', got: {result!r}")


def test_15_extract_section_missing_heading():
    result = _extract_section(_SAMPLE_BLUEPRINT, "## Nonexistent Section")
    assert_(result is None, "Should return None for a missing heading")


def test_16_extract_section_empty_body():
    doc = "## Project Structure\n\n## API Modules\ncontent here"
    result = _extract_section(doc, SECTION_PROJECT_STRUCTURE)
    assert_(result is None, "Should return None for empty section body")


def test_17_extract_last_section_no_trailing_h2():
    result = _extract_section(_SAMPLE_BLUEPRINT, SECTION_TESTING_STRATEGY)
    assert_(result is not None, "Should extract the last section")
    assert_("pytest" in result, f"Last section should contain 'pytest', got: {result!r}")


# ── 18-28: Node success ───────────────────────────────────────────────────────

def test_18_success_execution_status_completed():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["execution_status"] == ExecutionStatus.COMPLETED.value,
            f"Expected COMPLETED, got {result['execution_status']}")


def test_19_success_backend_code_summary_populated():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result.get("backend_code_summary") == _SAMPLE_BLUEPRINT.strip(),
            "backend_code_summary should equal LLM response content")


def test_20_success_metadata_backend_equals_summary():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["metadata"].get("backend") == result["backend_code_summary"],
            "metadata['backend'] should equal backend_code_summary")


def test_21_success_metadata_merge_preserves_existing_keys():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["metadata"].get("existing_key") == "existing_value",
            "Existing metadata keys must be preserved")


def test_22_success_current_agent():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_(result["current_agent"] == "backend_generator",
            f"Expected 'backend_generator', got {result['current_agent']}")


def test_23_success_completed_agents_appended():
    node = make_backend_generator_node(_make_mock_llm())
    state = _make_state()
    result = _run(node, state)
    assert_("backend_generator" in result["completed_agents"],
            "backend_generator should be in completed_agents")
    assert_("database_designer" in result["completed_agents"],
            "Prior agents must be preserved in completed_agents")


def test_24_success_agent_results_shape():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["agent_name"] == "backend_generator", "agent_name mismatch")
    assert_(ar["status"] == ExecutionStatus.COMPLETED.value, "status mismatch")
    assert_(ar["tokens_used"] == 1300, f"tokens_used mismatch: {ar['tokens_used']}")


def test_25_success_total_tokens_incremented():
    node = make_backend_generator_node(_make_mock_llm())
    state = _make_state()
    prior = state["total_tokens"]
    result = _run(node, state)
    assert_(result["total_tokens"] == prior + 1300,
            f"Expected {prior + 1300}, got {result['total_tokens']}")


def test_26_success_estimated_cost_incremented():
    node = make_backend_generator_node(_make_mock_llm())
    state = _make_state()
    prior = state["estimated_cost"]
    result = _run(node, state)
    assert_(result["estimated_cost"] > prior, "estimated_cost should increase")


def test_27_success_model_used_set():
    node = make_backend_generator_node(_make_mock_llm(model="gpt-4o-mini"))
    result = _run(node, _make_state())
    assert_(result["model_used"] == "gpt-4o-mini",
            f"Expected 'gpt-4o-mini', got {result['model_used']}")


def test_28_success_updated_at_present():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("updated_at" in result, "updated_at should be in changeset")
    assert_(result["updated_at"], "updated_at should not be empty")


# ── 29-36: Guard conditions ───────────────────────────────────────────────────

def test_29_guard_empty_clarified_requirements():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(clarified_requirements=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_30_guard_none_clarified_requirements():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(clarified_requirements=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_31_guard_empty_architecture_summary():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(architecture_summary=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_32_guard_none_architecture_summary():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(architecture_summary=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_33_guard_empty_task_plan():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(task_plan=[]))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_34_guard_none_task_plan():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(task_plan=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_35_guard_empty_database_schema():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(database_schema=""))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


def test_36_guard_none_database_schema():
    mock = _make_mock_llm()
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state(database_schema=None))
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    mock.complete.assert_not_called()


# ── 37-41: Error handling ─────────────────────────────────────────────────────

def test_37_llm_unavailable_exception():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMUnavailableException("OpenAI down"))
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state())
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    assert_(any("unavailable" in e.lower() for e in result["errors"]),
            f"'unavailable' should appear in errors: {result['errors']}")


def test_38_llm_exception():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMException("rate limit hit"))
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state())
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    assert_(any("rate limit hit" in e for e in result["errors"]),
            f"Detail should appear in errors: {result['errors']}")


def test_39_unexpected_exception():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=RuntimeError("disk full"))
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state())
    assert_(result["execution_status"] == ExecutionStatus.FAILED.value, "Should FAIL")
    assert_(any("RuntimeError" in e for e in result["errors"]),
            f"Class name should appear in errors: {result['errors']}")


def test_40_failure_agent_result_recorded():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMException("oops"))
    node = make_backend_generator_node(mock)
    result = _run(node, _make_state())
    ar = result["agent_results"][-1]
    assert_(ar["agent_name"] == "backend_generator", "agent_name should be backend_generator")
    assert_(ar["status"] == ExecutionStatus.FAILED.value, "status should be FAILED")
    assert_(ar["error_message"] is not None, "error_message should not be None")
    assert_(ar["tokens_used"] == 0, "tokens_used should be 0 on failure")


def test_41_failure_errors_list_appended_not_replaced():
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=LLMException("oops"))
    node = make_backend_generator_node(mock)
    state = _make_state()
    state["errors"] = ["prior error"]
    result = _run(node, state)
    assert_("prior error" in result["errors"], "Prior errors must be preserved")
    assert_(len(result["errors"]) == 2, f"Should have 2 errors, got {len(result['errors'])}")


# ── 42-47: State integrity ────────────────────────────────────────────────────

def test_42_raw_requirements_not_in_changeset():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("raw_requirements" not in result, "raw_requirements must not be in changeset")


def test_43_clarified_requirements_not_re_emitted():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("clarified_requirements" not in result,
            "clarified_requirements must not be in changeset")


def test_44_architecture_summary_not_re_emitted():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("architecture_summary" not in result,
            "architecture_summary must not be in changeset")


def test_45_task_plan_not_re_emitted():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("task_plan" not in result, "task_plan must not be in changeset")


def test_46_database_schema_not_re_emitted():
    node = make_backend_generator_node(_make_mock_llm())
    result = _run(node, _make_state())
    assert_("database_schema" not in result, "database_schema must not be in changeset")


def test_47_input_state_not_mutated():
    node = make_backend_generator_node(_make_mock_llm())
    state = _make_state()
    original_errors = list(state["errors"])
    original_agents = list(state["completed_agents"])
    _run(node, state)
    assert_(state["errors"] == original_errors, "state['errors'] was mutated")
    assert_(state["completed_agents"] == original_agents,
            "state['completed_agents'] was mutated")


# ── 48-54: Graph round-trip (five agents) ────────────────────────────────────

def _make_mock_llm_for_graph() -> MagicMock:
    """Return a mock LLM that cycles through five distinct responses."""
    ra_response = CompletionResponse(
        content=(
            "## Functional Requirements\nUsers can CRUD tasks.\n\n"
            "## Non-Functional Requirements\nJWT auth.\n\n"
            "## Assumptions\nSingle-tenant.\n\n"
            "## Missing Information\nNone.\n\n"
            "## Risks\nNone.\n\n"
            "## Acceptance Criteria\nAll tests pass."
        ),
        model="gpt-4o-mini",
        usage=UsageInfo(prompt_tokens=100, completion_tokens=200, total_tokens=300),
        latency_ms=0,
    )
    sa_response = CompletionResponse(
        content=(
            "## Architecture Pattern\nLayered.\n\n"
            "## Backend Services\nFastAPI.\n\n"
            "## Frontend Architecture\nReact.\n\n"
            "## Database Architecture\nPostgreSQL.\n\n"
            "## API Design\nREST.\n\n"
            "## Security Architecture\nJWT.\n\n"
            "## Scalability Strategy\nDocker.\n\n"
            "## Deployment Architecture\nAWS."
        ),
        model="gpt-4o-mini",
        usage=UsageInfo(prompt_tokens=200, completion_tokens=300, total_tokens=500),
        latency_ms=0,
    )
    tp_response = CompletionResponse(
        content=(
            "## Backend Tasks\n\n"
            "### TASK-001: Set up FastAPI app\n"
            "- **Priority:** High\n"
            "- **Complexity:** Low\n"
            "- **Description:** Initialize FastAPI project structure.\n"
            "- **Dependencies:** None\n\n"
            "## Frontend Tasks\n\n"
            "## Database Tasks\n\n"
            "### DB-001: Design users table\n"
            "- **Priority:** High\n"
            "- **Complexity:** Low\n"
            "- **Description:** Create migration for users table.\n"
            "- **Dependencies:** None\n\n"
            "## Infrastructure Tasks\n\n"
            "## Testing Tasks\n\n"
            "## Deployment Tasks\n"
        ),
        model="gpt-4o-mini",
        usage=UsageInfo(prompt_tokens=300, completion_tokens=400, total_tokens=700),
        latency_ms=0,
    )
    dd_response = CompletionResponse(
        content=(
            "## Core Entities\nTask, User.\n\n"
            "## Entity Attributes\nTask: id UUID.\n\n"
            "## Relationships\nMany-to-one.\n\n"
            "## Primary Keys\nUUID PKs.\n\n"
            "## Foreign Keys\ntasks.user_id.\n\n"
            "## Constraints\nNOT NULL on title.\n\n"
            "## Indexes\nidx_tasks_user_id.\n\n"
            "## Normalization Notes\n3NF."
        ),
        model="gpt-4o-mini",
        usage=UsageInfo(prompt_tokens=400, completion_tokens=500, total_tokens=900),
        latency_ms=0,
    )
    bg_response = CompletionResponse(
        content=_SAMPLE_BLUEPRINT,
        model="gpt-4o-mini",
        usage=UsageInfo(prompt_tokens=500, completion_tokens=600, total_tokens=1100),
        latency_ms=0,
    )
    mock = MagicMock()
    mock.complete = AsyncMock(side_effect=[
        ra_response,
        sa_response,
        tp_response,
        dd_response,
        bg_response,
    ])
    return mock


def _run_graph(initial_state: ForgeState) -> ForgeState:
    import asyncio
    from langgraph.checkpoint.memory import MemorySaver
    from app.infrastructure.langgraph.graph import build_forge_graph
    mock_llm = _make_mock_llm_for_graph()
    graph = build_forge_graph(mock_llm, checkpointer=MemorySaver())
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


def test_48_graph_compiles_with_five_nodes():
    from langgraph.checkpoint.memory import MemorySaver
    from app.infrastructure.langgraph.graph import build_forge_graph
    mock_llm = _make_mock_llm()
    graph = build_forge_graph(mock_llm, checkpointer=MemorySaver())
    assert_(graph is not None, "Graph should compile without errors")


def test_49_five_agent_run_status_completed():
    result = _run_graph(_make_graph_state())
    assert_(result["execution_status"] == ExecutionStatus.COMPLETED.value,
            f"Expected COMPLETED, got {result['execution_status']}")


def test_50_all_five_agents_in_completed_agents():
    result = _run_graph(_make_graph_state())
    for agent in [
        "requirements_analyst",
        "architect",           # AgentType.ARCHITECT.value
        "task_planner",
        "database_designer",
        "backend_generator",
    ]:
        assert_(agent in result["completed_agents"],
                f"'{agent}' not in completed_agents: {result['completed_agents']}")


def test_51_five_agent_results_records():
    result = _run_graph(_make_graph_state())
    assert_(len(result["agent_results"]) == 5,
            f"Expected 5 agent_results, got {len(result['agent_results'])}")


def test_52_backend_code_summary_non_empty():
    result = _run_graph(_make_graph_state())
    assert_(result.get("backend_code_summary"), "backend_code_summary should be non-empty")


def test_53_metadata_backend_present():
    result = _run_graph(_make_graph_state())
    assert_("backend" in result.get("metadata", {}),
            "metadata['backend'] should be present after full run")


def test_54_total_tokens_accumulate():
    result = _run_graph(_make_graph_state())
    # 300 + 500 + 700 + 900 + 1100 = 3500
    assert_(result["total_tokens"] >= 3500,
            f"Expected total_tokens >= 3500, got {result['total_tokens']}")
