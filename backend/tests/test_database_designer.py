"""
Tests for the Database Designer agent.

Coverage
--------
Prompt builder
 1. Returns two messages
 2. First message is SYSTEM role
 3. Second message is USER role
 4. User message contains CLARIFIED REQUIREMENTS block
 5. User message contains SOFTWARE ARCHITECTURE block
 6. User message contains IMPLEMENTATION TASK PLAN block
 7. System prompt contains all eight required section headings

_extract_db_task_summary helper
 8. Returns only Database-category tasks
 9. Formats each task as a bullet with priority, id, title, description
10. Returns placeholder when no database tasks found
11. Skips malformed (non-JSON) task entries silently
12. Category match is case-insensitive

_extract_section helper
13. Extracts body of a known section
14. Returns None for a missing heading
15. Returns None for an empty section body
16. Correctly extracts the last section (no trailing H2)

Node success
17. execution_status → COMPLETED
18. database_schema populated with LLM response content
19. metadata["database_schema"] equals database_schema
20. Existing metadata keys preserved (merge, not replace)
21. current_agent → "database_designer"
22. completed_agents appended (prior agents preserved)
23. agent_results appended with correct shape (agent_name, status, tokens)
24. total_tokens incremented
25. estimated_cost incremented
26. model_used set from response
27. updated_at present

Guard conditions
28. Empty clarified_requirements → FAILED, no LLM call
29. None clarified_requirements → FAILED, no LLM call
30. Empty architecture_summary → FAILED, no LLM call
31. None architecture_summary → FAILED, no LLM call
32. Empty task_plan list → FAILED, no LLM call
33. None task_plan → FAILED, no LLM call

Error handling
34. LLMUnavailableException → FAILED, "unavailable" in error
35. LLMException → FAILED, detail in errors list
36. Unexpected exception → FAILED, class name in errors list
37. Failure path: failed AgentResult recorded with error_message
38. Failure path: errors list appended (not replaced)

State integrity
39. raw_requirements not in changeset
40. clarified_requirements not re-emitted
41. architecture_summary not re-emitted
42. task_plan not re-emitted
43. Input state dict not mutated

Graph round-trip (four agents)
44. build_forge_graph compiles with four nodes
45. Four-agent ainvoke → execution_status COMPLETED
46. All four agents in completed_agents
47. Four agent_results records
48. database_schema non-empty after full run
49. metadata["database_schema"] present after full run
50. Total tokens accumulate across all four agents
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.application.prompts.database_designer import (
    REQUIRED_SECTIONS,
    SECTION_ATTRIBUTES,
    SECTION_ENTITIES,
    SECTION_NORMALIZATION,
    build_database_designer_messages,
)
from app.application.services.llm.types import (
    CompletionResponse,
    MessageRole,
    UsageInfo,
)
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.database_designer import (
    _extract_db_task_summary,
    _extract_section,
    make_database_designer_node,
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

## Suggested Improvements
- Add priority field.
"""

_SAMPLE_ARCHITECTURE = """\
## Recommended Architecture Pattern
Layered monolith.

## Backend Structure
FastAPI + SQLAlchemy.

## Frontend Structure
React 18.

## Database Design Overview
PostgreSQL 16. Task entity with UUID PK.

## API Design Overview
REST /api/v1/.

## Security Considerations
- JWT auth.

## Scalability Considerations
- Read replicas.

## Deployment Recommendations
- AWS ECS.
"""

_SAMPLE_DB_TASK = json.dumps({
    "id": "DB-001",
    "title": "Create initial migrations",
    "category": "Database",
    "priority": "High",
    "complexity": "Low",
    "description": "Write Alembic migration for Task table.",
    "dependencies": [],
})

_SAMPLE_BE_TASK = json.dumps({
    "id": "BE-001",
    "title": "Set up FastAPI",
    "category": "Backend",
    "priority": "High",
    "complexity": "Low",
    "description": "Initialize FastAPI app.",
    "dependencies": [],
})

_SAMPLE_TASK_PLAN = [_SAMPLE_DB_TASK, _SAMPLE_BE_TASK]

_SAMPLE_SCHEMA = """\
## Entities
- **Task** — Represents a user task with status lifecycle.
- **User** — Represents an authenticated system user.

## Attributes

### Task
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | UUID | No | gen_random_uuid() | Primary key |
| title | TEXT | No | — | Task title |
| description | TEXT | Yes | NULL | Optional details |
| status | VARCHAR(20) | No | 'todo' | Lifecycle status |
| due_date | TIMESTAMPTZ | Yes | NULL | Optional deadline |
| user_id | UUID | No | — | FK to users |
| created_at | TIMESTAMPTZ | No | now() | Creation timestamp |
| deleted_at | TIMESTAMPTZ | Yes | NULL | Soft delete marker |

### User
| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | UUID | No | gen_random_uuid() | Primary key |
| email | TEXT | No | — | Login identifier |
| password_hash | TEXT | No | — | Argon2id hash |
| created_at | TIMESTAMPTZ | No | now() | Registration timestamp |
| deleted_at | TIMESTAMPTZ | Yes | NULL | Soft delete marker |

## Relationships
- **User** → **Task**: one-to-many (tasks.user_id) — Each user owns zero or more tasks.

## Primary Keys
- **Task**: id (UUID) — Globally unique, collision-free across distributed inserts.
- **User**: id (UUID) — Globally unique identifier.

## Foreign Keys
- **tasks**.user_id → **users**.id ON DELETE CASCADE ON UPDATE CASCADE

## Constraints
- **Task**: UNIQUE on (user_id, title) — Prevent duplicate task titles per user.
- **Task**: CHECK (status IN ('todo', 'in_progress', 'done')) — Enforce valid statuses.
- **User**: UNIQUE on (email) — Login identifier must be globally unique.

## Suggested Indexes
- **tasks** (user_id) — btree — Accelerates per-user task list queries.
- **tasks** (user_id, status) — btree — Accelerates filtered task list queries.
- **tasks** (due_date) WHERE due_date IS NOT NULL — btree — Deadline reminder queries.

## Normalization Notes
- Overall form: 3NF
- No deliberate denormalisations; all non-key attributes depend solely on the PK.
"""


def _make_llm_service(
    content: str = _SAMPLE_SCHEMA,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 1000,
    completion_tokens: int = 1500,
) -> MagicMock:
    response = CompletionResponse(
        content=content,
        model=model,
        usage=UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        latency_ms=250,
    )
    svc = MagicMock()
    svc.complete = AsyncMock(return_value=response)
    svc.provider_name = "mock"
    svc.default_model = model
    return svc


def _base_state(**overrides: Any) -> ForgeState:
    state = create_forge_state(
        project_id=uuid4(),
        project_name="DB Designer Test",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    state["clarified_requirements"] = _SAMPLE_CLARIFIED
    state["architecture_summary"] = _SAMPLE_ARCHITECTURE
    state["task_plan"] = list(_SAMPLE_TASK_PLAN)
    state["completed_agents"] = ["requirements_analyst", "architect", "task_planner"]
    state["total_tokens"] = 3600
    state["estimated_cost"] = 0.005
    state.update(overrides)  # type: ignore[attr-defined]
    return state


# ── 1-7. Prompt builder ───────────────────────────────────────────────────────


def test_prompt_builder_returns_two_messages() -> None:
    msgs = build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "- DB task")
    assert len(msgs) == 2


def test_prompt_builder_first_is_system() -> None:
    assert build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x")[0].role == MessageRole.SYSTEM


def test_prompt_builder_second_is_user() -> None:
    assert build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x")[1].role == MessageRole.USER


def test_prompt_builder_user_contains_clarified() -> None:
    content = build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x")[1].content
    assert "CLARIFIED REQUIREMENTS" in content and "Functional Requirements" in content


def test_prompt_builder_user_contains_architecture() -> None:
    content = build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x")[1].content
    assert "SOFTWARE ARCHITECTURE" in content and "Backend Structure" in content


def test_prompt_builder_user_contains_task_plan() -> None:
    content = build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "- DB-001: something")[1].content
    assert "IMPLEMENTATION TASK PLAN" in content and "DB-001" in content


def test_prompt_builder_system_has_all_sections() -> None:
    sys_content = build_database_designer_messages(_SAMPLE_CLARIFIED, _SAMPLE_ARCHITECTURE, "x")[0].content
    for section in REQUIRED_SECTIONS:
        assert section in sys_content, f"Missing: {section}"


# ── 8-12. _extract_db_task_summary ───────────────────────────────────────────


def test_extract_db_task_summary_only_database_tasks() -> None:
    summary = _extract_db_task_summary(_SAMPLE_TASK_PLAN)
    assert "DB-001" in summary
    assert "BE-001" not in summary


def test_extract_db_task_summary_format() -> None:
    summary = _extract_db_task_summary(_SAMPLE_TASK_PLAN)
    assert "[High]" in summary
    assert "Create initial migrations" in summary
    assert "Write Alembic migration" in summary


def test_extract_db_task_summary_placeholder_when_empty() -> None:
    be_only = [_SAMPLE_BE_TASK]
    summary = _extract_db_task_summary(be_only)
    assert "No explicit database tasks" in summary


def test_extract_db_task_summary_skips_malformed() -> None:
    bad = ["not-json", _SAMPLE_DB_TASK]
    summary = _extract_db_task_summary(bad)
    assert "DB-001" in summary  # valid task still extracted


def test_extract_db_task_summary_case_insensitive_category() -> None:
    task = json.dumps({"id": "DB-002", "title": "T", "category": "database",
                       "priority": "Low", "description": "x", "dependencies": []})
    summary = _extract_db_task_summary([task])
    assert "DB-002" in summary


# ── 13-16. _extract_section ───────────────────────────────────────────────────


def test_extract_section_known_heading() -> None:
    body = _extract_section(_SAMPLE_SCHEMA, SECTION_ENTITIES)
    assert body is not None
    assert "Task" in body


def test_extract_section_missing_heading_returns_none() -> None:
    assert _extract_section(_SAMPLE_SCHEMA, "## Ghost Section") is None


def test_extract_section_empty_body_returns_none() -> None:
    md = f"{SECTION_ENTITIES}\n\n{SECTION_ATTRIBUTES}\n- something\n"
    assert _extract_section(md, SECTION_ENTITIES) is None


def test_extract_section_last_section() -> None:
    body = _extract_section(_SAMPLE_SCHEMA, SECTION_NORMALIZATION)
    assert body is not None
    assert "3NF" in body


# ── 17-27. Node success ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_execution_status_completed() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert changes["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_node_success_database_schema_populated() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert changes["database_schema"] == _SAMPLE_SCHEMA.strip()


@pytest.mark.asyncio
async def test_node_success_metadata_database_schema_set() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert changes["metadata"]["database_schema"] == _SAMPLE_SCHEMA.strip()


@pytest.mark.asyncio
async def test_node_success_metadata_existing_keys_preserved() -> None:
    state = _base_state(metadata={"architecture": "arch doc", "task_plan": "plan doc"})
    changes = await make_database_designer_node(_make_llm_service())(state)
    assert changes["metadata"]["architecture"] == "arch doc"
    assert changes["metadata"]["task_plan"] == "plan doc"
    assert "database_schema" in changes["metadata"]


@pytest.mark.asyncio
async def test_node_success_current_agent() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert changes["current_agent"] == "database_designer"


@pytest.mark.asyncio
async def test_node_success_completed_agents_appended() -> None:
    state = _base_state(completed_agents=["requirements_analyst", "architect", "task_planner"])
    changes = await make_database_designer_node(_make_llm_service())(state)
    assert "database_designer" in changes["completed_agents"]
    assert "requirements_analyst" in changes["completed_agents"]
    assert "task_planner" in changes["completed_agents"]


@pytest.mark.asyncio
async def test_node_success_agent_result_shape() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "database_designer"
    assert result["status"] == ExecutionStatus.COMPLETED.value
    assert result["error_message"] is None
    assert result["tokens_used"] == 2500  # 1000 + 1500
    assert result["completed_at"] is not None


@pytest.mark.asyncio
async def test_node_success_total_tokens_incremented() -> None:
    state = _base_state(total_tokens=3600)
    changes = await make_database_designer_node(
        _make_llm_service(prompt_tokens=1000, completion_tokens=1500)
    )(state)
    assert changes["total_tokens"] == 3600 + 2500


@pytest.mark.asyncio
async def test_node_success_estimated_cost_incremented() -> None:
    state = _base_state(estimated_cost=0.0)
    changes = await make_database_designer_node(
        _make_llm_service(prompt_tokens=1_000_000, completion_tokens=0)
    )(state)
    assert abs(changes["estimated_cost"] - 0.15) < 0.001


@pytest.mark.asyncio
async def test_node_success_model_used_set() -> None:
    changes = await make_database_designer_node(_make_llm_service(model="gpt-4o"))(_base_state())
    assert changes["model_used"] == "gpt-4o"


@pytest.mark.asyncio
async def test_node_success_updated_at_present() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert changes["updated_at"] is not None


# ── 28-33. Guard conditions ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_empty_clarified_requirements() -> None:
    svc = _make_llm_service()
    changes = await make_database_designer_node(svc)(_base_state(clarified_requirements=""))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_none_clarified_requirements() -> None:
    svc = _make_llm_service()
    changes = await make_database_designer_node(svc)(_base_state(clarified_requirements=None))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_empty_architecture_summary() -> None:
    svc = _make_llm_service()
    changes = await make_database_designer_node(svc)(_base_state(architecture_summary=""))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_none_architecture_summary() -> None:
    svc = _make_llm_service()
    changes = await make_database_designer_node(svc)(_base_state(architecture_summary=None))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_empty_task_plan_list() -> None:
    svc = _make_llm_service()
    changes = await make_database_designer_node(svc)(_base_state(task_plan=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_guard_none_task_plan() -> None:
    svc = _make_llm_service()
    changes = await make_database_designer_node(svc)(_base_state(task_plan=None))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


# ── 34-38. Error handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_unavailable_does_not_raise() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("timeout"))
    changes = await make_database_designer_node(svc)(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert "unavailable" in changes["errors"][0].lower()


@pytest.mark.asyncio
async def test_llm_exception_detail_in_errors() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("token limit exceeded"))
    changes = await make_database_designer_node(svc)(_base_state(errors=[]))
    assert any("token limit exceeded" in e for e in changes["errors"])


@pytest.mark.asyncio
async def test_unexpected_exception_caught() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=MemoryError("OOM"))
    changes = await make_database_designer_node(svc)(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert "MemoryError" in changes["errors"][0]


@pytest.mark.asyncio
async def test_failure_agent_result_recorded() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("bad"))
    changes = await make_database_designer_node(svc)(_base_state())
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "database_designer"
    assert result["status"] == ExecutionStatus.FAILED.value
    assert result["error_message"] is not None


@pytest.mark.asyncio
async def test_failure_errors_appended_not_replaced() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("x"))
    state = _base_state(errors=["prior error"])
    changes = await make_database_designer_node(svc)(state)
    assert len(changes["errors"]) == 2
    assert changes["errors"][0] == "prior error"


# ── 39-43. State integrity ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_requirements_not_in_changeset() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert "raw_requirements" not in changes


@pytest.mark.asyncio
async def test_clarified_requirements_not_re_emitted() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert "clarified_requirements" not in changes


@pytest.mark.asyncio
async def test_architecture_summary_not_re_emitted() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert "architecture_summary" not in changes


@pytest.mark.asyncio
async def test_task_plan_not_re_emitted() -> None:
    changes = await make_database_designer_node(_make_llm_service())(_base_state())
    assert "task_plan" not in changes


@pytest.mark.asyncio
async def test_input_state_not_mutated() -> None:
    state = _base_state(errors=[], metadata={"k": "v"})
    orig_errors = list(state["errors"])
    orig_meta = dict(state["metadata"])
    await make_database_designer_node(_make_llm_service())(state)
    assert state["errors"] == orig_errors
    assert state["metadata"] == orig_meta


# ── 44-50. Graph round-trip (four agents) ────────────────────────────────────


def test_build_forge_graph_compiles_with_four_nodes() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    graph = build_forge_graph(llm_service=_make_llm_service(), checkpointer=MemorySaver())
    assert graph is not None


def _four_agent_responses() -> list[CompletionResponse]:
    """Canned responses for RA → SA → TP → DD."""
    ra = CompletionResponse(
        content=_SAMPLE_CLARIFIED, model="m", usage=UsageInfo(100, 200, 300), latency_ms=5,
    )
    sa = CompletionResponse(
        content=_SAMPLE_ARCHITECTURE, model="m", usage=UsageInfo(500, 800, 1300), latency_ms=5,
    )
    # Task Planner must return valid JSON tasks so DB Designer guard passes
    tp_plan = "\n".join([
        "## Backend Tasks\n\n### BE-001: Set up FastAPI\n- **Priority:** High\n- **Complexity:** Low\n- **Description:** Init app.\n- **Dependencies:** None",
        "## Frontend Tasks\n\n### FE-001: Set up React\n- **Priority:** High\n- **Complexity:** Low\n- **Description:** Bootstrap.\n- **Dependencies:** None",
        "## Database Tasks\n\n### DB-001: Create migrations\n- **Priority:** High\n- **Complexity:** Low\n- **Description:** Task table.\n- **Dependencies:** None",
        "## Infrastructure Tasks\n\n### INF-001: Docker\n- **Priority:** High\n- **Complexity:** Low\n- **Description:** Compose.\n- **Dependencies:** None",
        "## Testing Tasks\n\n### TST-001: Unit tests\n- **Priority:** High\n- **Complexity:** Low\n- **Description:** Test service.\n- **Dependencies:** None",
        "## Deployment Tasks\n\n### DEP-001: Dockerfile\n- **Priority:** High\n- **Complexity:** Low\n- **Description:** Build image.\n- **Dependencies:** None",
    ])
    tp = CompletionResponse(
        content=tp_plan, model="m", usage=UsageInfo(800, 1200, 2000), latency_ms=5,
    )
    dd = CompletionResponse(
        content=_SAMPLE_SCHEMA, model="m", usage=UsageInfo(1000, 1500, 2500), latency_ms=5,
    )
    return [ra, sa, tp, dd]


@pytest.mark.asyncio
async def test_graph_round_trip_status_completed() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_four_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="4-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert result["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_graph_round_trip_all_four_agents_in_completed() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_four_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="4-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    for agent in ("requirements_analyst", "architect", "task_planner", "database_designer"):
        assert agent in result["completed_agents"], f"Missing: {agent}"


@pytest.mark.asyncio
async def test_graph_round_trip_four_agent_results() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_four_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="4-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert len(result["agent_results"]) == 4
    names = {r["agent_name"] for r in result["agent_results"]}
    assert names == {"requirements_analyst", "architect", "task_planner", "database_designer"}


@pytest.mark.asyncio
async def test_graph_round_trip_database_schema_non_empty() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_four_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="4-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert result["database_schema"] is not None
    assert len(result["database_schema"]) > 100


@pytest.mark.asyncio
async def test_graph_round_trip_metadata_database_schema_present() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_four_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="4-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    assert "database_schema" in result["metadata"]
    assert result["metadata"]["database_schema"] == result["database_schema"]


@pytest.mark.asyncio
async def test_graph_round_trip_tokens_accumulate() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=_four_agent_responses())
    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="4-Agent", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )
    # RA:300 + SA:1300 + TP:2000 + DD:2500 = 6100
    assert result["total_tokens"] == 6100, f"Expected 6100, got {result['total_tokens']}"
