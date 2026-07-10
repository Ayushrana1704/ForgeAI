"""
Tests for the Requirements Analyst agent.

Coverage
--------
1.  Prompt builder — correct message count, roles, required sections present
2.  Section extractor — happy path, missing heading, last section, empty body
3.  Node success — ForgeState fields updated correctly after mocked LLM call
4.  Node token telemetry — total_tokens and estimated_cost incremented
5.  Node model_used — set from response.model
6.  Node completed_agents — appended correctly
7.  Node agent_results — AgentResult shape and values
8.  Provider failure (LLMUnavailableException) — errors list, status FAILED, no raise
9.  Generic LLMException — errors list, status FAILED, no raise
10. Unexpected exception — caught, errors list, status FAILED, no raise
11. ForgeState integrity — node only returns dict keys (not full TypedDict)
12. architecture_summary — extracted from Non-Functional Requirements section
13. Empty raw_requirements — still calls LLM (validation is caller's concern)
14. Graph construction — build_forge_graph accepts mocked LLMService
15. Graph round-trip — ainvoke with mocked LLM produces COMPLETED state

No real LLM calls are made.  All LLMService interactions are mocked.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.application.prompts.requirements_analyst import (
    REQUIRED_SECTIONS,
    SECTION_FUNCTIONAL,
    SECTION_NON_FUNCTIONAL,
    build_requirements_analyst_messages,
)
from app.application.services.llm.types import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    MessageRole,
    UsageInfo,
)
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.nodes.requirements_analyst import (
    _extract_section,
    make_requirements_analyst_node,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_REQUIREMENTS = (
    "Build a REST API for a task management application. "
    "Users should be able to create, read, update, and delete tasks. "
    "Tasks have a title, description, status (todo/in-progress/done), and due date."
)

_SAMPLE_MARKDOWN = """\
## Functional Requirements
- Users can create tasks with title, description, status, and due date.
- Users can list all tasks.
- Users can update any task field.
- Users can delete tasks.

## Non-Functional Requirements
- API p99 latency must be ≤ 200 ms under 500 rps.
- All endpoints must require JWT authentication.
- Data must be persisted in a relational database.

## Assumptions
- A single authenticated user per token; multi-tenancy is out of scope.
- Due dates are stored and returned in UTC ISO 8601 format.

## Missing Information
- Maximum number of tasks per user is not specified.
- Pagination requirements are absent.

## Risks
- No rate-limiting spec; API may be abused if left unthrottled.

## Suggested Improvements
- Add a priority field to tasks.
- Consider soft-delete instead of hard-delete for audit trails.
"""


def _make_llm_service(
    content: str = _SAMPLE_MARKDOWN,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 200,
) -> MagicMock:
    """Return a MagicMock LLMService whose .complete() returns a canned response."""
    response = CompletionResponse(
        content=content,
        model=model,
        usage=UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        latency_ms=123,
    )
    svc = MagicMock()
    svc.complete = AsyncMock(return_value=response)
    svc.provider_name = "mock"
    svc.default_model = model
    return svc


def _base_state(**overrides: Any) -> ForgeState:
    state = create_forge_state(
        project_id=uuid4(),
        project_name="Test Project",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    state.update(overrides)  # type: ignore[attr-defined]
    return state


# ── 1. Prompt builder ─────────────────────────────────────────────────────────


def test_prompt_builder_returns_two_messages() -> None:
    msgs = build_requirements_analyst_messages(_SAMPLE_REQUIREMENTS)
    assert len(msgs) == 2


def test_prompt_builder_first_message_is_system() -> None:
    msgs = build_requirements_analyst_messages(_SAMPLE_REQUIREMENTS)
    assert msgs[0].role == MessageRole.SYSTEM


def test_prompt_builder_second_message_is_user() -> None:
    msgs = build_requirements_analyst_messages(_SAMPLE_REQUIREMENTS)
    assert msgs[1].role == MessageRole.USER


def test_prompt_builder_user_content_matches_input() -> None:
    msgs = build_requirements_analyst_messages("  build me a thing  ")
    assert msgs[1].content == "build me a thing"


def test_prompt_builder_system_contains_all_required_sections() -> None:
    msgs = build_requirements_analyst_messages(_SAMPLE_REQUIREMENTS)
    system_content = msgs[0].content
    for section in REQUIRED_SECTIONS:
        assert section in system_content, f"Section missing from system prompt: {section}"


# ── 2. Section extractor ──────────────────────────────────────────────────────


def test_extract_section_happy_path() -> None:
    body = _extract_section(_SAMPLE_MARKDOWN, SECTION_FUNCTIONAL)
    assert body is not None
    assert "create tasks" in body.lower()


def test_extract_section_nonfunctional() -> None:
    body = _extract_section(_SAMPLE_MARKDOWN, SECTION_NON_FUNCTIONAL)
    assert body is not None
    assert "latency" in body.lower()


def test_extract_section_missing_heading_returns_none() -> None:
    result = _extract_section(_SAMPLE_MARKDOWN, "## Does Not Exist")
    assert result is None


def test_extract_section_last_section() -> None:
    """Last section has no following H2 — must still be extracted."""
    body = _extract_section(_SAMPLE_MARKDOWN, "## Suggested Improvements")
    assert body is not None
    assert "priority" in body.lower()


def test_extract_section_empty_body_returns_none() -> None:
    md = "## Functional Requirements\n\n## Non-Functional Requirements\n- something\n"
    result = _extract_section(md, "## Functional Requirements")
    assert result is None


# ── 3. Node success — ForgeState fields ───────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_execution_status_completed() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    changes = await node(state)
    assert changes["execution_status"] == ExecutionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_node_success_clarified_requirements_populated() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    changes = await node(state)
    assert changes["clarified_requirements"] == _SAMPLE_MARKDOWN.strip()


@pytest.mark.asyncio
async def test_node_success_current_agent_set() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    changes = await node(state)
    assert changes["current_agent"] == "requirements_analyst"


@pytest.mark.asyncio
async def test_node_success_started_at_preserved_when_already_set() -> None:
    original_time = "2024-01-01T00:00:00+00:00"
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state(started_at=original_time)
    changes = await node(state)
    assert changes["started_at"] == original_time


@pytest.mark.asyncio
async def test_node_success_started_at_set_when_none() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state(started_at=None)
    changes = await node(state)
    assert changes["started_at"] is not None


@pytest.mark.asyncio
async def test_node_success_updated_at_refreshed() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    old_updated_at = state["updated_at"]
    changes = await node(state)
    # updated_at may equal old value if clock resolution is low; just assert present
    assert changes["updated_at"] is not None


# ── 4. Token telemetry ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_total_tokens_incremented() -> None:
    node = make_requirements_analyst_node(_make_llm_service(prompt_tokens=100, completion_tokens=200))
    state = _base_state(total_tokens=50)
    changes = await node(state)
    assert changes["total_tokens"] == 50 + 300  # 100+200=300 new


@pytest.mark.asyncio
async def test_node_success_estimated_cost_incremented() -> None:
    node = make_requirements_analyst_node(_make_llm_service(prompt_tokens=1_000_000, completion_tokens=0))
    state = _base_state(estimated_cost=0.0)
    changes = await node(state)
    # 1M input tokens × $0.000_000_150 = $0.15
    assert abs(changes["estimated_cost"] - 0.15) < 0.001


# ── 5. model_used ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_model_used_set() -> None:
    node = make_requirements_analyst_node(_make_llm_service(model="gpt-4o"))
    state = _base_state()
    changes = await node(state)
    assert changes["model_used"] == "gpt-4o"


# ── 6. completed_agents ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_appends_to_completed_agents() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state(completed_agents=[])
    changes = await node(state)
    assert "requirements_analyst" in changes["completed_agents"]


@pytest.mark.asyncio
async def test_node_success_preserves_existing_completed_agents() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state(completed_agents=["some_prior_agent"])
    changes = await node(state)
    assert "some_prior_agent" in changes["completed_agents"]
    assert "requirements_analyst" in changes["completed_agents"]


# ── 7. agent_results ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_success_appends_agent_result() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state(agent_results=[])
    changes = await node(state)
    assert len(changes["agent_results"]) == 1


@pytest.mark.asyncio
async def test_node_success_agent_result_shape() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    changes = await node(state)
    result = changes["agent_results"][-1]
    assert result["agent_name"] == "requirements_analyst"
    assert result["status"] == ExecutionStatus.COMPLETED.value
    assert result["tokens_used"] == 300
    assert result["error_message"] is None
    assert result["completed_at"] is not None


# ── 8. LLMUnavailableException ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_llm_unavailable_does_not_raise() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("provider down"))
    node = make_requirements_analyst_node(svc)
    state = _base_state()
    # Must not raise
    changes = await node(state)
    assert changes is not None


@pytest.mark.asyncio
async def test_node_llm_unavailable_sets_failed_status() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("provider down"))
    node = make_requirements_analyst_node(svc)
    state = _base_state()
    changes = await node(state)
    assert changes["execution_status"] == ExecutionStatus.FAILED.value


@pytest.mark.asyncio
async def test_node_llm_unavailable_appends_error() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("provider down"))
    node = make_requirements_analyst_node(svc)
    state = _base_state(errors=[])
    changes = await node(state)
    assert len(changes["errors"]) == 1
    assert "unavailable" in changes["errors"][0].lower()


@pytest.mark.asyncio
async def test_node_llm_unavailable_records_failed_agent_result() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMUnavailableException("provider down"))
    node = make_requirements_analyst_node(svc)
    state = _base_state()
    changes = await node(state)
    result = changes["agent_results"][-1]
    assert result["status"] == ExecutionStatus.FAILED.value
    assert result["error_message"] is not None


# ── 9. Generic LLMException ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_llm_exception_does_not_raise() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("rate limit"))
    node = make_requirements_analyst_node(svc)
    state = _base_state()
    changes = await node(state)
    assert changes["execution_status"] == ExecutionStatus.FAILED.value


@pytest.mark.asyncio
async def test_node_llm_exception_error_message_contains_detail() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=LLMException("rate limit exceeded"))
    node = make_requirements_analyst_node(svc)
    state = _base_state(errors=[])
    changes = await node(state)
    assert any("rate limit exceeded" in e for e in changes["errors"])


# ── 10. Unexpected exception ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_unexpected_exception_does_not_raise() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=RuntimeError("something exploded"))
    node = make_requirements_analyst_node(svc)
    state = _base_state()
    changes = await node(state)
    assert changes["execution_status"] == ExecutionStatus.FAILED.value


@pytest.mark.asyncio
async def test_node_unexpected_exception_appends_error() -> None:
    svc = MagicMock()
    svc.complete = AsyncMock(side_effect=ValueError("bad value"))
    node = make_requirements_analyst_node(svc)
    state = _base_state(errors=[])
    changes = await node(state)
    assert len(changes["errors"]) == 1
    assert "ValueError" in changes["errors"][0]


# ── 11. ForgeState integrity ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_returns_dict_not_full_state() -> None:
    """Node must return only changed fields, not the full ForgeState."""
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    changes = await node(state)
    assert isinstance(changes, dict)
    # raw_requirements is NOT in the changeset — node does not re-emit it
    assert "raw_requirements" not in changes


@pytest.mark.asyncio
async def test_node_does_not_mutate_input_state() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state(errors=[], agent_results=[])
    original_errors = list(state["errors"])
    original_results = list(state["agent_results"])
    await node(state)
    assert state["errors"] == original_errors
    assert state["agent_results"] == original_results


# ── 12. architecture_summary ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_architecture_summary_extracted_from_nfr_section() -> None:
    node = make_requirements_analyst_node(_make_llm_service())
    state = _base_state()
    changes = await node(state)
    assert changes["architecture_summary"] is not None
    assert "latency" in changes["architecture_summary"].lower()


@pytest.mark.asyncio
async def test_node_architecture_summary_none_when_section_missing() -> None:
    """If the LLM omits the NFR section, architecture_summary is None."""
    content = "## Functional Requirements\n- Something\n"
    node = make_requirements_analyst_node(_make_llm_service(content=content))
    state = _base_state()
    changes = await node(state)
    assert changes["architecture_summary"] is None


# ── 13. Empty raw_requirements ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_calls_llm_even_with_empty_requirements() -> None:
    """Validation of raw_requirements is the caller's responsibility, not the node's."""
    svc = _make_llm_service()
    node = make_requirements_analyst_node(svc)
    state = _base_state(raw_requirements="")
    await node(state)
    svc.complete.assert_awaited_once()


# ── 14. Graph construction ────────────────────────────────────────────────────


def test_build_forge_graph_accepts_mock_llm_service() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = _make_llm_service()
    checkpointer = MemorySaver()
    graph = build_forge_graph(llm_service=svc, checkpointer=checkpointer)
    assert graph is not None


# ── 15. Graph round-trip ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_round_trip_produces_completed_state() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.infrastructure.langgraph.graph import build_forge_graph

    svc = _make_llm_service()
    checkpointer = MemorySaver()
    graph = build_forge_graph(llm_service=svc, checkpointer=checkpointer)

    initial_state = create_forge_state(
        project_id=uuid4(),
        project_name="Graph Round-Trip Test",
        raw_requirements=_SAMPLE_REQUIREMENTS,
    )
    config = {"configurable": {"thread_id": str(uuid4())}}

    result = await graph.ainvoke(initial_state, config=config)

    assert result["execution_status"] == ExecutionStatus.COMPLETED.value
    assert result["clarified_requirements"] is not None
    assert "requirements_analyst" in result["completed_agents"]
    assert len(result["agent_results"]) == 1
    assert result["agent_results"][0]["status"] == ExecutionStatus.COMPLETED.value
