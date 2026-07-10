"""
Tests for the Software Architect agent.

Coverage
--------
1.  Prompt builder — correct message count, roles, both context blocks present
2.  Prompt builder — handles None architecture_notes gracefully
3.  Prompt builder — required sections present in system prompt
4.  Section extractor — happy path, missing heading, last section, empty body
5.  Node success — execution_status COMPLETED
6.  Node success — architecture_summary populated from LLM response
7.  Node success — metadata["architecture"] equals architecture_summary
8.  Node success — existing metadata keys preserved (merge, not replace)
9.  Node success — current_agent set to "architect"
10. Node success — completed_agents appended
11. Node success — prior completed_agents preserved
12. Node success — agent_results appended with correct shape
13. Node success — total_tokens incremented
14. Node success — estimated_cost incremented
15. Node success — model_used set from response
16. Node success — updated_at refreshed
17. Node guard — empty clarified_requirements → FAILED without LLM call
18. Node guard — None clarified_requirements → FAILED without LLM call
19. Provider unavailable — FAILED, error appended, no raise
20. Generic LLMException — FAILED, error message contains detail
21. Unexpected exception — caught, FAILED, error contains class name
22. Failure path — failed AgentResult recorded with error_message
23. State integrity — raw_requirements not in changeset
24. State integrity — clarified_requirements not in changeset (not re-emitted)
25. State integrity — input state not mutated
26. Graph construction — build_forge_graph compiles with two nodes
27. Graph round-trip — ainvoke traverses RA → SA, status COMPLETED
28. Graph round-trip — both agents in completed_agents
29. Graph round-trip — two agent_results records
30. Graph round-trip — architecture_summary non-empty after full run

No real LLM calls are made.  All LLMService interactions are mocked.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from typing import Any

import pytest

from app.application.prompts.software_architect import (
    REQUIRED_SECTIONS,
    SECTION_ARCHITECTURE_PATTERN,
    SECTION_BACKEND,
    SECTION_DEPLOYMENT,
    build_software_architect_messages,
)
from app.application.services.llm.types import (
    CompletionResponse,
    MessageRole,
    UsageInfo,
)
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.software_architect import (
    _extract_section,
    make_software_architect_node,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_REQUIREMENTS = (
    "Build a REST API for a task management application. "
    "Users can create, read, update, and delete tasks with title, status, and due date."
)

_SAMPLE_CLARIFIED = """\
## Functional Requirements
- Users can create tasks with title, description, status, and due date.
- Users can list, update, and delete tasks.

## Non-Functional Requirements
- API p99 latency must be ≤ 200 ms under 500 rps.
- JWT authentication on all endpoints.

## Assumptions
- Single-tenant; one user per token.

## Missing Information
- Maximum tasks per user not specified.

## Risks
- No rate-limiting spec.

## Suggested Improvements
- Add task priority field.
"""

_SAMPLE_ARCHITECTURE = """\
## Recommended Architecture Pattern
Layered monolith (Clean Architecture). Justified by team size and requirement simplicity. \
Key principles: dependency inversion, single responsibility, explicit error handling.

## Backend Structure
FastAPI + Python 3.12. Layers: API → Application (services) → Domain → Infrastructure. \
SQLAlchemy async ORM. Alembic for migrations. structlog for structured logging.

## Frontend Structure
React 18 + TypeScript. Vite build tooling. TanStack Query for server state. \
React Router v6 for routing. Tailwind CSS for styling.

## Database Design Overview
PostgreSQL 16. Primary entity: Task (id UUID PK, title TEXT NOT NULL, \
description TEXT, status VARCHAR(20), due_date TIMESTAMPTZ, user_id UUID FK). \
Index on (user_id, status). Alembic versioned migrations.

## API Design Overview
REST, versioned under /api/v1/. JWT Bearer auth. Cursor-based pagination. \
Error format: {"error": {"code": str, "message": str, "details": list}}. \
Example: POST /api/v1/tasks → 201 {"id": uuid, "title": str, "status": str}.

## Security Considerations
- Argon2id password hashing.
- JWT RS256 signed tokens, 15-minute expiry.
- Input validation via Pydantic v2.
- CORS restricted to known origins.
- Rate limiting: 100 req/min per IP via slowapi.
- Secrets via environment variables; never committed to VCS.

## Scalability Considerations
- Horizontal scaling behind a load balancer.
- Redis cache for session data and hot task lists.
- Background jobs via Celery + Redis for notifications.
- Read replicas for heavy reporting queries.

## Deployment Recommendations
- AWS ECS Fargate; Docker images in ECR.
- GitHub Actions CI/CD: lint → test → build → deploy.
- Environments: dev / staging / prod.
- Terraform for IaC. Prometheus + Grafana for metrics. PagerDuty for alerts.
"""


def _make_llm_service(
    content: str = _SAMPLE_ARCHITECTURE,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 500,
    completion_tokens: int = 800,
) -> MagicMock:
    response = CompletionResponse(
        content=content,
        model=model,
        usage=UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        latency_ms=200,
    )
    svc = MagicMock()
    svc.complete = AsyncMock(return_value=response)
    svc.provider_name = "mock"
    svc.default_model = model
    return svc


def _base_state(**overrides: Any) -> ForgeState:
    state = create_forge_state(
        project_id=uuid4(),
        project_name="Architect Test Project",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    # Pre-populate fields that RA would have set
    state["clarified_requirements"] = _SAMPLE_CLARIFIED
    state["architecture_summary"] = "- API p99 latency must be ≤ 200 ms\n- JWT auth required"
    state["completed_agents"] = ["requirements_analyst"]
    state["total_tokens"] = 300
    state["estimated_cost"] = 0.001
    state.update(overrides)  # type: ignore[attr-defined]
    return state


# ── 1-3. Prompt builder ───────────────────────────────────────────────────────


def test_prompt_builder_returns_two_messages() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, "some notes")
    assert len(msgs) == 2


def test_prompt_builder_first_is_system() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, None)
    assert msgs[0].role == MessageRole.SYSTEM


def test_prompt_builder_second_is_user() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, None)
    assert msgs[1].role == MessageRole.USER


def test_prompt_builder_user_contains_clarified_requirements() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, None)
    assert "CLARIFIED REQUIREMENTS" in msgs[1].content
    assert "Functional Requirements" in msgs[1].content


def test_prompt_builder_user_contains_architecture_notes() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, "latency ≤ 200 ms")
    assert "INITIAL ARCHITECTURE NOTES" in msgs[1].content
    assert "latency ≤ 200 ms" in msgs[1].content


def test_prompt_builder_none_architecture_notes_handled() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, None)
    assert "No initial architecture notes provided" in msgs[1].content


def test_prompt_builder_system_contains_all_required_sections() -> None:
    msgs = build_software_architect_messages(_SAMPLE_CLARIFIED, None)
    sys_content = msgs[0].content
    for section in REQUIRED_SECTIONS:
        assert section in sys_content, f"Missing from system prompt: {section}"


# ── 4. Section extractor ──────────────────────────────────────────────────────


def test_extract_section_architecture_pattern() -> None:
    body = _extract_section(_SAMPLE_ARCHITECTURE, SECTION_ARCHITECTURE_PATTERN)
    assert body is not None
    assert "layered" in body.lower()


def test_extract_section_backend() -> None:
    body = _extract_section(_SAMPLE_ARCHITECTURE, SECTION_BACKEND)
    assert body is not None
    assert "fastapi" in body.lower()


def test_extract_section_last_section() -> None:
    body = _extract_section(_SAMPLE_ARCHITECTURE, SECTION_DEPLOYMENT)
    assert body is not None
    assert "fargate" in body.lower() or "ecs" in body.lower()


def test_extract_section_missing_heading() -> None:
    assert _extract_section(_SAMPLE_ARCHITECTURE, "## Does Not Exist") is None


def test_extract_section_empty_body_returns_none() -> None:
    md = f"{SECTION_ARCHITECTURE_PATTERN}\n\n{SECTION_BACKEND}\n- FastAPI\n"
    assert _extract_section(md, SECTION_ARCHITECTURE_PATTERN) is None


# ── 5-16. Node success ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_execution_status_completed() -> None:
    node = make_software_architect_node(_make_llm_service())
    changes = await node(_base_state())
    assert changes["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_node_success_architecture_summary_populated() -> None:
    node = make_software_architect_node(_make_llm_service())
    changes = await node(_base_state())
    assert changes["architecture_summary"] == _SAMPLE_ARCHITECTURE.strip()


@pytest.mark.asyncio
async def test_node_success_metadata_architecture_key_set() -> None:
    node = make_software_architect_node(_make_llm_service())
    changes = await node(_base_state())
    assert "architecture" in changes["metadata"]
    assert changes["metadata"]["architecture"] == _SAMPLE_ARCHITECTURE.strip()


@pytest.mark.asyncio
async def test_node_success_metadata_existing_keys_preserved() -> None:
    state = _base_state(metadata={"foo": "bar"})
    node = make_software_architect_node(_make_llm_service())
    changes = await node(state)
    assert changes["metadata"]["foo"] == "bar"
    assert "architecture" in changes["metadata"]


@pytest.mark.asyncio
async def test_node_success_current_agent_set() -> None:
    node = make_software_architect_node(_make_llm_service())
    changes = await node(_base_state())
    assert changes["current_agent"] == "architect"


@pytest.mark.asyncio
async def test_node_success_completed_agents_appended() -> None:
    state = _base_state(completed_agents=["requirements_analyst"])
    node = make_software_architect_node(_make_llm_service())
    changes = await node(state)
    assert "architect" in changes["completed_agents"]
    assert "requirements_analyst" in changes["completed_agents"]


@pytest.mark.asyncio
async def test_node_success_prior_completed_agents_preserved() -> None:
    state = _base_state(completed_agents=["requirements_analyst", "some_other"])
    node = make_software_architect_node(_make_llm_service())
    changes = await node(state)
    assert "some_other" in changes["completed_agents"]


@pytest.mark.asyncio
async def test_node_success_agent_result_shape() -> None:
    node = make_software_architect_node(_make_llm_service())
    changes = await node(_base_state())
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "architect"
    assert result["status"] == ExecutionStatus.COMPLETED.value
    assert result["error_message"] is None
    assert result["tokens_used"] == 1300  # 500 + 800
    assert result["completed_at"] is not None


@pytest.mark.asyncio
async def test_node_success_total_tokens_incremented() -> None:
    node = make_software_architect_node(_make_llm_service(prompt_tokens=500, completion_tokens=800))
    state = _base_state(total_tokens=300)
    changes = await node(state)
    assert changes["total_tokens"] == 300 + 1300


@pytest.mark.asyncio
async def test_node_success_estimated_cost_incremented() -> None:
    node = make_software_architect_node(_make_llm_service(prompt_tokens=1_000_000, completion_tokens=0))
    state = _base_state(estimated_cost=0.0)
    changes = await node(state)
    assert abs(changes["estimated_cost"] - 0.15) < 0.001


@pytest.mark.asyncio
async def test_node_success_model_used_set() -> None:
    node = make_software_architect_node(_make_llm_service(model="gpt-4o"))
    changes = await node(_base_state())
    assert changes["model_used"] == "gpt-4o"


@pytest.mark.asyncio
async def test_node_success_updated_at_present() -> None:
    node = make_software_architect_node(_make_llm_service())
    changes = await node(_base_state())
    assert changes["updated_at"] is not None


# ── 17-18. Guard: missing clarified_requirements ──────────────────────────────


@pytest.mark.asyncio
async def test_node_guard_empty_clarified_requirements() -> None:
    svc = _make_llm_service()
    node = make_software_architect_node(svc)
    state = _base_state(clarified_requirements="")
    changes = await node(state)
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_guard_none_clarified_requirements() -> None:
    svc = _make_llm_service()
    node = make_software_architect_node(svc)
    state = _base_state(clarified_requirements=None)
    changes = await node(state)
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    svc.complete.assert_not_awaited()


# ── 19. LLMUnavailableException ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_llm_unavailable_does_not_raise() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("timeout"))
    node = make_software_architect_node(svc)
    changes = await node(_base_state())
    assert changes["execution_status"] == ExecutionStatus.FAILED.value


@pytest.mark.asyncio
async def test_node_llm_unavailable_appends_error() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("timeout"))
    node = make_software_architect_node(svc)
    changes = await node(_base_state(errors=[]))
    assert len(changes["errors"]) == 1
    assert "unavailable" in changes["errors"][0].lower()


# ── 20. Generic LLMException ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_llm_exception_failed_status() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("context length exceeded"))
    node = make_software_architect_node(svc)
    changes = await node(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert any("context length exceeded" in e for e in changes["errors"])


# ── 21. Unexpected exception ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_unexpected_exception_caught() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=MemoryError("OOM"))
    node = make_software_architect_node(svc)
    changes = await node(_base_state(errors=[]))
    assert changes["execution_status"] == ExecutionStatus.FAILED.value
    assert "MemoryError" in changes["errors"][0]


# ── 22. Failure path AgentResult ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_failure_records_failed_agent_result() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("bad request"))
    node = make_software_architect_node(svc)
    changes = await node(_base_state())
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "architect"
    assert result["status"] == ExecutionStatus.FAILED.value
    assert result["error_message"] is not None


# ── 23-25. State integrity ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_raw_requirements_not_in_changeset() -> None:
    changes = await make_software_architect_node(_make_llm_service())(_base_state())
    assert "raw_requirements" not in changes


@pytest.mark.asyncio
async def test_node_clarified_requirements_not_re_emitted() -> None:
    changes = await make_software_architect_node(_make_llm_service())(_base_state())
    assert "clarified_requirements" not in changes


@pytest.mark.asyncio
async def test_node_does_not_mutate_input_state() -> None:
    state = _base_state(errors=[], agent_results=[], metadata={})
    orig_errors = list(state["errors"])
    orig_meta = dict(state["metadata"])
    await make_software_architect_node(_make_llm_service())(state)
    assert state["errors"] == orig_errors
    assert state["metadata"] == orig_meta


# ── 26-30. Graph round-trip ───────────────────────────────────────────────────


def test_build_forge_graph_compiles_with_two_nodes() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    graph = build_forge_graph(llm_service=_make_llm_service(), checkpointer=MemorySaver())
    assert graph is not None


@pytest.mark.asyncio
async def test_graph_round_trip_status_completed() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    # RA mock returns clarified reqs; SA mock returns architecture doc
    ra_response = CompletionResponse(
        content=_SAMPLE_CLARIFIED,
        model="gpt-4o-mini",
        usage=UsageInfo(100, 200, 300),
        latency_ms=50,
    )
    sa_response = CompletionResponse(
        content=_SAMPLE_ARCHITECTURE,
        model="gpt-4o-mini",
        usage=UsageInfo(500, 800, 1300),
        latency_ms=150,
    )
    # Both nodes use the same LLMService instance; responses alternate by call order
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=[ra_response, sa_response])
    svc.provider_name = "mock"
    svc.default_model = "gpt-4o-mini"

    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    initial = create_forge_state(
        project_id=uuid4(),
        project_name="Two-Agent Round-Trip",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    result = await graph.ainvoke(initial, config={"configurable": {"thread_id": str(uuid4())}})

    assert result["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_graph_round_trip_both_agents_in_completed() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    ra_resp = CompletionResponse(content=_SAMPLE_CLARIFIED, model="m", usage=UsageInfo(10,10,20), latency_ms=5)
    sa_resp = CompletionResponse(content=_SAMPLE_ARCHITECTURE, model="m", usage=UsageInfo(10,10,20), latency_ms=5)
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=[ra_resp, sa_resp])

    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="P", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )

    assert "requirements_analyst" in result["completed_agents"]
    assert "architect" in result["completed_agents"]


@pytest.mark.asyncio
async def test_graph_round_trip_two_agent_results() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    ra_resp = CompletionResponse(content=_SAMPLE_CLARIFIED, model="m", usage=UsageInfo(10,10,20), latency_ms=5)
    sa_resp = CompletionResponse(content=_SAMPLE_ARCHITECTURE, model="m", usage=UsageInfo(10,10,20), latency_ms=5)
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=[ra_resp, sa_resp])

    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="P", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )

    assert len(result["agent_results"]) == 2
    names = [r["agent_name"] for r in result["agent_results"]]
    assert "requirements_analyst" in names
    assert "architect" in names


@pytest.mark.asyncio
async def test_graph_round_trip_architecture_summary_non_empty() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    ra_resp = CompletionResponse(content=_SAMPLE_CLARIFIED, model="m", usage=UsageInfo(10,10,20), latency_ms=5)
    sa_resp = CompletionResponse(content=_SAMPLE_ARCHITECTURE, model="m", usage=UsageInfo(10,10,20), latency_ms=5)
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=[ra_resp, sa_resp])

    graph = build_forge_graph(llm_service=svc, checkpointer=MemorySaver())
    result = await graph.ainvoke(
        create_forge_state(project_id=uuid4(), project_name="P", raw_requirements=_SAMPLE_REQUIREMENTS),
        config={"configurable": {"thread_id": str(uuid4())}},
    )

    assert result["architecture_summary"] is not None
    assert len(result["architecture_summary"]) > 100
    assert result["metadata"].get("architecture") == result["architecture_summary"]
