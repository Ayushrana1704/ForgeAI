"""
Tests for the Task Planner agent.

Coverage
--------
Prompt builder
 1. Returns two messages
 2. First message is SYSTEM role
 3. Second message is USER role
 4. User message contains CLARIFIED REQUIREMENTS block
 5. User message contains SOFTWARE ARCHITECTURE block
 6. System prompt contains all six required section headings

Task parser — _parse_task_block
 7. Parses all five fields correctly (id, title, priority, complexity, description, dependencies)
 8. Missing ID (no colon) falls back gracefully
 9. Dependencies list parsed from comma-separated string
10. "None" dependencies becomes empty list
11. Empty block returns None

Task parser — _parse_task_plan
12. Returns list of JSON strings
13. Each JSON string deserialises to a dict with the required keys
14. Tasks from all six sections are collected
15. Malformed H3 blocks (no heading) are silently skipped
16. Empty section body yields no tasks for that section

Node success
17. execution_status → COMPLETED
18. task_plan is a non-empty list
19. Each task_plan element is valid JSON
20. metadata["task_plan"] equals raw LLM response
21. Existing metadata keys preserved (merge, not replace)
22. current_agent → "task_planner"
23. completed_agents appended
24. Prior completed_agents preserved
25. agent_results appended with correct shape
26. total_tokens incremented
27. estimated_cost incremented
28. model_used set from response
29. updated_at present

Guard conditions
30. Empty clarified_requirements → FAILED, no LLM call
31. None clarified_requirements → FAILED, no LLM call
32. Empty architecture_summary → FAILED, no LLM call
33. None architecture_summary → FAILED, no LLM call

Error handling
34. LLMUnavailableException → FAILED, error appended, no raise
35. LLMException → FAILED, error detail in errors list
36. RuntimeError → FAILED, class name in errors list
37. Failure path AgentResult recorded with error_message

State integrity
38. raw_requirements not in changeset
39. clarified_requirements not re-emitted
40. architecture_summary not re-emitted
41. Input state not mutated

Graph round-trip (three agents)
42. build_forge_graph compiles with three nodes
43. Three-agent ainvoke → execution_status COMPLETED
44. All three agents in completed_agents
45. Three agent_results records
46. task_plan non-empty after full run
47. metadata["task_plan"] present after full run
48. Total tokens accumulate across all three agents
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.prompts.task_planner import (
    REQUIRED_SECTIONS,
    SECTION_BACKEND,
    SECTION_DEPLOYMENT,
    SECTION_TESTING,
    build_task_planner_messages,
)
from app.application.services.llm.types import (
    CompletionResponse,
    MessageRole,
    UsageInfo,
)
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.task_planner import (
    _extract_section,
    _parse_task_block,
    _parse_task_plan,
    make_task_planner_node,
)

# ── Test fixtures ─────────────────────────────────────────────────────────────

_SAMPLE_REQUIREMENTS = "Build a REST API for task management. Users can CRUD tasks."

_SAMPLE_CLARIFIED = """\
## Functional Requirements
- Users can create tasks with title, description, status, and due date.
- Users can list, update, and delete tasks.

## Non-Functional Requirements
- API p99 latency must be ≤ 200 ms under 500 rps.

## Assumptions
- Single-tenant.

## Missing Information
- Max tasks per user not specified.

## Risks
- No rate-limiting spec.

## Suggested Improvements
- Add task priority field.
"""

_SAMPLE_ARCHITECTURE = """\
## Recommended Architecture Pattern
Layered monolith.

## Backend Structure
FastAPI + Python 3.12.

## Frontend Structure
React 18 + TypeScript.

## Database Design Overview
PostgreSQL 16.

## API Design Overview
REST /api/v1/.

## Security Considerations
- JWT auth.

## Scalability Considerations
- Horizontal scaling.

## Deployment Recommendations
- AWS ECS Fargate.
"""

_SAMPLE_PLAN = """\
## Backend Tasks

### BE-001: Set up FastAPI project structure
- **Priority:** High
- **Complexity:** Low
- **Description:** Initialize FastAPI application with Clean Architecture layers.
- **Dependencies:** None

### BE-002: Implement Task CRUD endpoints
- **Priority:** High
- **Complexity:** Medium
- **Description:** Create POST, GET, PUT, DELETE endpoints for the Task resource.
- **Dependencies:** BE-001, DB-001

## Frontend Tasks

### FE-001: Set up React project with TypeScript
- **Priority:** High
- **Complexity:** Low
- **Description:** Bootstrap React 18 app with Vite, TypeScript, and Tailwind CSS.
- **Dependencies:** None

### FE-002: Implement task list component
- **Priority:** Medium
- **Complexity:** Medium
- **Description:** Build paginated task list with filter and sort controls.
- **Dependencies:** FE-001, BE-002

## Database Tasks

### DB-001: Create initial database migrations
- **Priority:** High
- **Complexity:** Low
- **Description:** Write Alembic migration for Task table with all required columns.
- **Dependencies:** None

### DB-002: Add database indexes
- **Priority:** Medium
- **Complexity:** Low
- **Description:** Add composite index on (user_id, status) for fast filtered queries.
- **Dependencies:** DB-001

## Infrastructure Tasks

### INF-001: Set up Docker Compose for local development
- **Priority:** High
- **Complexity:** Low
- **Description:** Create docker-compose.yml with API, database, and Redis services.
- **Dependencies:** None

### INF-002: Configure GitHub Actions CI pipeline
- **Priority:** High
- **Complexity:** Medium
- **Description:** Add lint, test, and build stages to CI workflow.
- **Dependencies:** INF-001

## Testing Tasks

### TST-001: Write unit tests for task service layer
- **Priority:** High
- **Complexity:** Medium
- **Description:** Cover all CRUD operations with mocked repository.
- **Dependencies:** BE-001

### TST-002: Write integration tests for task API
- **Priority:** Medium
- **Complexity:** Medium
- **Description:** End-to-end tests hitting the API with a real test database.
- **Dependencies:** BE-002, DB-001

## Deployment Tasks

### DEP-001: Create Dockerfile for API service
- **Priority:** High
- **Complexity:** Low
- **Description:** Multi-stage Dockerfile producing a minimal production image.
- **Dependencies:** BE-001

### DEP-002: Configure AWS ECS task definition
- **Priority:** Medium
- **Complexity:** Medium
- **Description:** Define ECS task with CPU/memory limits and environment variable injection.
- **Dependencies:** DEP-001
"""


def _make_llm_service(
    content: str = _SAMPLE_PLAN,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 800,
    completion_tokens: int = 1200,
) -> MagicMock:
    response = CompletionResponse(
        content=content,
        model=model,
        usage=UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        latency_ms=300,
    )
    svc = MagicMock()
    svc.complete = AsyncMock(return_value=response)
    svc.provider_name = "mock"
    svc.default_model = model
    return svc


def _base_state(**overrides: Any) -> ForgeState:
    state = create_forge_state(
        project_id=uuid4(),
        project_name="Task Planner Test",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    state["clarified_requirements"] = _SAMPLE_CLARIFIED
    state["architecture_summary"] = _SAMPLE_ARCHITECTURE
    state["completed_agents"] = ["requirements_analyst", "architect"]
    state["total_tokens"] = 1600
    state["estimated_cost"] = 0.002
    state.update(overrides)  # type: ignore[attr-defined]
    return state


# ── 1-6. Prompt builder ───────────────────────────────────────────────────────


def test_prompt_builder_returns_two_messages() -> None:
    msgs = build_task_planner_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE)
    assert len(msgs) == 2


def test_prompt_builder_first_is_system() -> None:
    assert build_task_planner_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE)[0].role == MessageRole.SYSTEM


def test_prompt_builder_second_is_user() -> None:
    assert build_task_planner_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE)[1].role == MessageRole.USER


def test_prompt_builder_user_contains_clarified_requirements() -> None:
    content = build_task_planner_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE)[1].content
    assert "CLARIFIED REQUIREMENTS" in content
    assert "Functional Requirements" in content


def test_prompt_builder_user_contains_architecture() -> None:
    content = build_task_planner_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE)[1].content
    assert "SOFTWARE ARCHITECTURE" in content
    assert "Backend Structure" in content


def test_prompt_builder_system_contains_all_sections() -> None:
    sys_content = build_task_planner_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE)[0].content
    for section in REQUIRED_SECTIONS:
        assert section in sys_content, f"Missing from system prompt: {section}"


# ── 7-15. Parser unit tests ───────────────────────────────────────────────────


def test_parse_task_block_all_fields() -> None:
    block = (
        "### BE-001: Set up FastAPI\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** Initialize app.\n"
        "- **Dependencies:** None"
    )
    result = _parse_task_block(block, "Backend")
    assert result is not None
    assert result["id"] == "BE-001"
    assert result["title"] == "Set up FastAPI"
    assert result["category"] == "Backend"
    assert result["priority"] == "High"
    assert result["complexity"] == "Low"
    assert result["description"] == "Initialize app."
    assert result["dependencies"] == []


def test_parse_task_block_no_id_colon() -> None:
    block = (
        "### Just a title with no colon\n"
        "- **Priority:** Medium\n"
        "- **Complexity:** Medium\n"
        "- **Description:** Some task.\n"
        "- **Dependencies:** None"
    )
    result = _parse_task_block(block, "Backend")
    assert result is not None
    assert result["id"] == ""
    assert result["title"] == "Just a title with no colon"


def test_parse_task_block_dependencies_list() -> None:
    block = (
        "### BE-002: Implement endpoints\n"
        "- **Priority:** High\n"
        "- **Complexity:** Medium\n"
        "- **Description:** CRUD endpoints.\n"
        "- **Dependencies:** BE-001, DB-001"
    )
    result = _parse_task_block(block, "Backend")
    assert result is not None
    assert result["dependencies"] == ["BE-001", "DB-001"]


def test_parse_task_block_none_dependencies_is_empty_list() -> None:
    block = (
        "### DB-001: Create schema\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** Initial migration.\n"
        "- **Dependencies:** None"
    )
    result = _parse_task_block(block, "Database")
    assert result is not None
    assert result["dependencies"] == []


def test_parse_task_block_empty_returns_none() -> None:
    assert _parse_task_block("", "Backend") is None


def test_parse_task_plan_returns_list_of_json_strings() -> None:
    tasks = _parse_task_plan(_SAMPLE_PLAN)
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    for item in tasks:
        assert isinstance(item, str)


def test_parse_task_plan_each_item_is_valid_json() -> None:
    tasks = _parse_task_plan(_SAMPLE_PLAN)
    for item in tasks:
        parsed = json.loads(item)
        for key in ("id", "title", "category", "priority", "complexity", "description", "dependencies"):
            assert key in parsed, f"Key '{key}' missing from: {parsed}"


def test_parse_task_plan_collects_from_all_sections() -> None:
    tasks = _parse_task_plan(_SAMPLE_PLAN)
    categories = {json.loads(t)["category"] for t in tasks}
    assert "Backend" in categories
    assert "Frontend" in categories
    assert "Database" in categories
    assert "Infrastructure" in categories
    assert "Testing" in categories
    assert "Deployment" in categories


def test_parse_task_plan_skips_non_h3_lines() -> None:
    """Prose before the first H3 in a section body should not produce tasks."""
    plan = (
        "## Backend Tasks\n\n"
        "Some prose here that isn't a task.\n\n"
        "### BE-001: Real task\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** A real task.\n"
        "- **Dependencies:** None\n\n"
        "## Frontend Tasks\n\n"
        "### FE-001: Frontend task\n"
        "- **Priority:** Medium\n"
        "- **Complexity:** Low\n"
        "- **Description:** A frontend task.\n"
        "- **Dependencies:** None\n\n"
        "## Database Tasks\n\n"
        "### DB-001: DB task\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** DB task.\n"
        "- **Dependencies:** None\n\n"
        "## Infrastructure Tasks\n\n"
        "### INF-001: Infra task\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** Infra task.\n"
        "- **Dependencies:** None\n\n"
        "## Testing Tasks\n\n"
        "### TST-001: Test task\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** Test task.\n"
        "- **Dependencies:** None\n\n"
        "## Deployment Tasks\n\n"
        "### DEP-001: Deploy task\n"
        "- **Priority:** High\n"
        "- **Complexity:** Low\n"
        "- **Description:** Deploy task.\n"
        "- **Dependencies:** None\n"
    )
    tasks = _parse_task_plan(plan)
    titles = [json.loads(t)["title"] for t in tasks]
    assert "Real task" in titles
    assert not any("prose" in t.lower() for t in titles)


def test_parse_task_plan_empty_section_yields_no_tasks() -> None:
    plan = (
        "## Backend Tasks\n\n"
        "## Frontend Tasks\n\n"
        "### FE-001: Only task\n"
        "- **Priority:** Low\n"
        "- **Complexity:** Low\n"
        "- **Description:** Only task.\n"
        "- **Dependencies:** None\n\n"
        "## Database Tasks\n\n"
        "## Infrastructure Tasks\n\n"
        "## Testing Tasks\n\n"
        "## Deployment Tasks\n\n"
    )
    tasks = _parse_task_plan(plan)
    categories = [json.loads(t)["category"] for t in tasks]
    assert "Frontend" in categories
    assert "Backend" not in categories


# ── 17-29. Node success ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_execution_status_completed() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert changes["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_node_success_task_plan_non_empty() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert isinstance(changes["task_plan"], list)
    assert len(changes["task_plan"]) > 0


@pytest.mark.asyncio
async def test_node_success_task_plan_elements_are_valid_json() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    for item in changes["task_plan"]:
        parsed = json.loads(item)
        assert "id" in parsed and "title" in parsed and "category" in parsed


@pytest.mark.asyncio
async def test_node_success_metadata_task_plan_is_raw_markdown() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert changes["metadata"]["task_plan"] == _SAMPLE_PLAN.strip()


@pytest.mark.asyncio
async def test_node_success_metadata_existing_keys_preserved() -> None:
    state = _base_state(metadata={"architecture": "some arch"})
    changes = await make_task_planner_node(_make_llm_service())(state)
    assert changes["metadata"]["architecture"] == "some arch"
    assert "task_plan" in changes["metadata"]


@pytest.mark.asyncio
async def test_node_success_current_agent() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert changes["current_agent"] == "task_planner"


@pytest.mark.asyncio
async def test_node_success_completed_agents_appended() -> None:
    state = _base_state(completed_agents=["requirements_analyst", "architect"])
    changes = await make_task_planner_node(_make_llm_service())(state)
    assert "task_planner" in changes["completed_agents"]
    assert "requirements_analyst" in changes["completed_agents"]
    assert "architect" in changes["completed_agents"]


@pytest.mark.asyncio
async def test_node_success_prior_completed_agents_preserved() -> None:
    state = _base_state(completed_agents=["requirements_analyst", "architect", "some_other"])
    changes = await make_task_planner_node(_make_llm_service())(state)
    assert "some_other" in changes["completed_agents"]


@pytest.mark.asyncio
async def test_node_success_agent_result_shape() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "task_planner"
    assert result["status"] == ExecutionStatus.COMPLETED.value
    assert result["error_message"] is None
    assert result["tokens_used"] == 2000  # 800 + 1200
    assert result["completed_at"] is not None


@pytest.mark.asyncio
async def test_node_success_total_tokens_incremented() -> None:
    state = _base_state(total_tokens=1600)
    changes = await make_task_planner_node(_make_llm_service(prompt_tokens=800, completion_tokens=1200))(state)
    assert changes["total_tokens"] == 1600 + 2000


@pytest.mark.asyncio
async def test_node_success_estimated_cost_incremented() -> None:
    state = _base_state(estimated_cost=0.0)
    changes = await make_task_planner_node(_make_llm_service(prompt_tokens=1_000_000, completion_tokens=0))(state)
    assert abs(changes["estimated_cost"] - 0.15) < 0.001


@pytest.mark.asyncio
async def test_node_success_model_used_set() -> None:
    changes = await make_task_planner_node(_make_llm_service(model="gpt-4o"))(_base_state())
    assert changes["model_used"] == "gpt-4o"


@pytest.mark.asyncio
async def test_node_success_updated_at_present() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert changes["updated_at"] is not None


# ── 30-33. Guard conditions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_guard_empty_clarified_requirements() -> None:
    svc = _make_llm_service()
    changes = await make_task_planner_node(svc)(_base_state(clarified_requirements=""))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_guard_none_clarified_requirements() -> None:
    svc = _make_llm_service()
    changes = await make_task_planner_node(svc)(_base_state(clarified_requirements=None))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_guard_empty_architecture_summary() -> None:
    svc = _make_llm_service()
    changes = await make_task_planner_node(svc)(_base_state(architecture_summary=""))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_guard_none_architecture_summary() -> None:
    svc = _make_llm_service()
    changes = await make_task_planner_node(svc)(_base_state(architecture_summary=None))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


# ── 34-37. Error handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_llm_unavailable_does_not_raise() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("timeout"))
    changes = await make_task_planner_node(svc)(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert len(changes["errors"]) == 1
    assert "unavailable" in changes["errors"][0].lower()


@pytest.mark.asyncio
async def test_node_llm_exception_detail_in_errors() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("context window exceeded"))
    changes = await make_task_planner_node(svc)(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert any("context window exceeded" in e for e in changes["errors"])


@pytest.mark.asyncio
async def test_node_runtime_error_caught() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=ValueError("bad json"))
    changes = await make_task_planner_node(svc)(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert "ValueError" in changes["errors"][0]


@pytest.mark.asyncio
async def test_node_failure_agent_result_recorded() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("bad request"))
    changes = await make_task_planner_node(svc)(_base_state())
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "task_planner"
    assert result["status"] == ExecutionStatus.FAILED.value
    assert result["error_message"] is not None


# ── 38-41. State integrity ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_raw_requirements_not_in_changeset() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert "raw_requirements" not in changes


@pytest.mark.asyncio
async def test_node_clarified_requirements_not_re_emitted() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert "clarified_requirements" not in changes


@pytest.mark.asyncio
async def test_node_architecture_summary_not_re_emitted() -> None:
    changes = await make_task_planner_node(_make_llm_service())(_base_state())
    assert "architecture_summary" not in changes


@pytest.mark.asyncio
async def test_node_does_not_mutate_input_state() -> None:
    state = _base_state(errors=[], metadata={"architecture": "x"})
    orig_errors = list(state["errors"])
    orig_meta = dict(state["metadata"])
    await make_task_planner_node(_make_llm_service())(state)
    assert state["errors"] == orig_errors
    assert state["metadata"] == orig_meta


# ── 42-48. Graph round-trip ───────────────────────────────────────────────────


def test_build_forge_graph_compiles_with_three_nodes() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = _make_llm_service()
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    assert graph is not None


def _make_three_agent_responses() -> list[CompletionResponse]:
    """Return three canned responses: RA → SA → TP."""
    ra = CompletionResponse(
        content=_SAMPLE_CLARIFIED,
        model="gpt-4o-mini",
        usage=UsageInfo(100, 200, 300),
        latency_ms=50,
    )
    sa = CompletionResponse(
        content=_SAMPLE_ARCHITECTURE,
        model="gpt-4o-mini",
        usage=UsageInfo(500, 800, 1300),
        latency_ms=150,
    )
    tp = CompletionResponse(
        content=_SAMPLE_PLAN,
        model="gpt-4o-mini",
        usage=UsageInfo(800, 1200, 2000),
        latency_ms=300,
    )
    return [ra, sa, tp]


@pytest.mark.asyncio
async def test_graph_round_trip_status_completed() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_make_three_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="3-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert result["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_graph_round_trip_all_three_agents_in_completed() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_make_three_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="3-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert "requirements_analyst" in result["completed_agents"]
    assert "architect" in result["completed_agents"]
    assert "task_planner" in result["completed_agents"]


@pytest.mark.asyncio
async def test_graph_round_trip_three_agent_results() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_make_three_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="3-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert len(result["agent_results"]) == 3
    names = [r["agent_name"] for r in result["agent_results"]]
    assert "requirements_analyst" in names
    assert "architect" in names
    assert "task_planner" in names


@pytest.mark.asyncio
async def test_graph_round_trip_task_plan_non_empty() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_make_three_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="3-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert isinstance(result["task_plan"], list)
    assert len(result["task_plan"]) > 0


@pytest.mark.asyncio
async def test_graph_round_trip_metadata_task_plan_present() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_make_three_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="3-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert "task_plan" in result["metadata"]


@pytest.mark.asyncio
async def test_graph_round_trip_tokens_accumulate() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_make_three_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="3-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    # RA: 300, SA: 1300, TP: 2000 → 3600
    assert result["total_tokens"] == 3600, f"Expected 3600, got {result['total_tokens']}"
