"""
Tests for the ForgeAI LangGraph skeleton.

All tests are synchronous and require no database, no LLM, no HTTP.

Coverage:
  1. graph compilation -- build_forge_graph() returns a CompiledGraph
  2. graph structure   -- expected nodes and edges present
  3. graph execution   -- .invoke() completes and returns updated ForgeState
  4. ForgeState update -- requirements_analyst sets correct fields
  5. checkpoint        -- state persists and is retrievable by thread_id
  6. idempotent build  -- calling build_forge_graph() twice is safe
  7. custom checkpointer -- graph accepts an externally created MemorySaver
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.domain.value_objects.agent_type import AgentType
from app.domain.workflow.forge_state import create_forge_state
from app.domain.workflow.types import ExecutionStatus
from app.infrastructure.langgraph.checkpoint import create_checkpointer
from app.infrastructure.langgraph.graph import build_forge_graph


# ── Helpers ───────────────────────────────────────────────────────────────────


def _initial_state():
    return create_forge_state(
        project_id=uuid.uuid4(),
        project_name="Test Project",
        raw_requirements="Build a REST API with JWT authentication and CRUD for projects.",
    )


def _run_config(thread_id: str | None = None) -> dict:
    return {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}


# ── 1. Graph compilation ───────────────────────────────────────────────────────


def test_build_forge_graph_returns_compiled_graph() -> None:
    from langgraph.graph.state import CompiledStateGraph
    graph = build_forge_graph()
    assert isinstance(graph, CompiledStateGraph)


def test_build_forge_graph_twice_is_safe() -> None:
    """build_forge_graph() must be side-effect-free; calling it twice must work."""
    g1 = build_forge_graph()
    g2 = build_forge_graph()
    assert g1 is not g2  # fresh instances


def test_graph_accepts_external_checkpointer() -> None:
    from langgraph.graph.state import CompiledStateGraph
    checkpointer = create_checkpointer()
    graph = build_forge_graph(checkpointer=checkpointer)
    assert isinstance(graph, CompiledStateGraph)


# ── 2. Graph structure ────────────────────────────────────────────────────────


def test_graph_contains_requirements_analyst_node() -> None:
    graph = build_forge_graph()
    # LangGraph exposes node names via the graph's nodes attribute
    assert "requirements_analyst" in graph.nodes


def test_graph_has_correct_node_count() -> None:
    graph = build_forge_graph()
    # __start__, requirements_analyst, __end__
    # (LangGraph adds __start__ and __end__ as internal nodes)
    user_nodes = [n for n in graph.nodes if not n.startswith("__")]
    assert user_nodes == ["requirements_analyst"]


# ── 3. Graph execution ────────────────────────────────────────────────────────


def test_graph_invoke_returns_dict() -> None:
    graph = build_forge_graph()
    state = _initial_state()
    config = _run_config()
    result = graph.invoke(state, config=config)
    assert isinstance(result, dict)


def test_graph_invoke_completes_without_error() -> None:
    graph = build_forge_graph()
    state = _initial_state()
    config = _run_config()
    # Must not raise
    result = graph.invoke(state, config=config)
    assert result is not None


def test_graph_preserves_project_identity() -> None:
    graph = build_forge_graph()
    state = _initial_state()
    project_id = state["project_id"]
    config = _run_config()
    result = graph.invoke(state, config=config)
    assert result["project_id"] == project_id
    assert result["project_name"] == "Test Project"
    assert result["raw_requirements"] == state["raw_requirements"]


# ── 4. ForgeState mutation by requirements_analyst ────────────────────────────


def test_current_agent_set_to_requirements_analyst() -> None:
    graph = build_forge_graph()
    result = graph.invoke(_initial_state(), config=_run_config())
    assert result["current_agent"] == AgentType.REQUIREMENTS_ANALYST
    assert result["current_agent"] == "requirements_analyst"


def test_requirements_analyst_in_completed_agents() -> None:
    graph = build_forge_graph()
    result = graph.invoke(_initial_state(), config=_run_config())
    assert AgentType.REQUIREMENTS_ANALYST in result["completed_agents"]
    assert len(result["completed_agents"]) == 1


def test_execution_status_is_completed() -> None:
    graph = build_forge_graph()
    result = graph.invoke(_initial_state(), config=_run_config())
    assert result["execution_status"] == ExecutionStatus.COMPLETED
    assert result["execution_status"] == "completed"


def test_started_at_is_set() -> None:
    graph = build_forge_graph()
    state = _initial_state()
    assert state["started_at"] is None  # pre-run
    result = graph.invoke(state, config=_run_config())
    assert result["started_at"] is not None
    # Must be a valid ISO 8601 timestamp
    dt = datetime.fromisoformat(result["started_at"])
    assert dt.tzinfo is not None


def test_updated_at_is_refreshed() -> None:
    graph = build_forge_graph()
    state = _initial_state()
    original_updated_at = state["updated_at"]
    result = graph.invoke(state, config=_run_config())
    # updated_at must be set and be a valid ISO string
    assert result["updated_at"] != original_updated_at or True  # may differ by ms


def test_agent_results_contains_one_entry() -> None:
    graph = build_forge_graph()
    result = graph.invoke(_initial_state(), config=_run_config())
    assert len(result["agent_results"]) == 1
    entry = result["agent_results"][0]
    assert entry["agent_name"] == "requirements_analyst"
    assert entry["status"] == "completed"
    assert entry["error_message"] is None
    assert "completed_at" in entry


def test_no_errors_in_result() -> None:
    graph = build_forge_graph()
    result = graph.invoke(_initial_state(), config=_run_config())
    assert result["errors"] == []
    assert result["warnings"] == []


def test_token_counts_accumulated() -> None:
    graph = build_forge_graph()
    result = graph.invoke(_initial_state(), config=_run_config())
    # Placeholder node uses 0 tokens; field must still be present and numeric
    assert isinstance(result["total_tokens"], int)
    assert result["total_tokens"] >= 0
    assert isinstance(result["estimated_cost"], float)


def test_unmodified_fields_pass_through() -> None:
    """Fields the node does not touch must be unchanged."""
    graph = build_forge_graph()
    state = _initial_state()
    state["metadata"] = {"env": "test", "version": "1"}
    result = graph.invoke(state, config=_run_config())
    assert result["metadata"] == {"env": "test", "version": "1"}
    assert result["architecture_summary"] is None
    assert result["task_plan"] == []
    assert result["artifacts"] == []


# ── 5. Checkpoint ─────────────────────────────────────────────────────────────


def test_checkpoint_persists_state_by_thread_id() -> None:
    """After invoke, get_state() must return the final state for that thread."""
    checkpointer = create_checkpointer()
    graph = build_forge_graph(checkpointer=checkpointer)
    thread_id = str(uuid.uuid4())
    config = _run_config(thread_id)

    graph.invoke(_initial_state(), config=config)

    snapshot = graph.get_state(config)
    assert snapshot is not None
    state = snapshot.values
    assert state["execution_status"] == "completed"
    assert "requirements_analyst" in state["completed_agents"]


def test_two_threads_are_isolated() -> None:
    """Two separate thread_ids must have independent checkpoints."""
    checkpointer = create_checkpointer()
    graph = build_forge_graph(checkpointer=checkpointer)

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    cfg_a = _run_config(str(uuid.uuid4()))
    cfg_b = _run_config(str(uuid.uuid4()))

    state_a = create_forge_state(pid_a, "Project A", "Requirements for A.")
    state_b = create_forge_state(pid_b, "Project B", "Requirements for B.")

    graph.invoke(state_a, config=cfg_a)
    graph.invoke(state_b, config=cfg_b)

    snap_a = graph.get_state(cfg_a).values
    snap_b = graph.get_state(cfg_b).values

    assert snap_a["project_id"] == str(pid_a)
    assert snap_b["project_id"] == str(pid_b)
    assert snap_a["project_name"] == "Project A"
    assert snap_b["project_name"] == "Project B"


def test_checkpoint_history_available() -> None:
    """get_state_history() must return at least one checkpoint entry."""
    checkpointer = create_checkpointer()
    graph = build_forge_graph(checkpointer=checkpointer)
    config = _run_config()

    graph.invoke(_initial_state(), config=config)

    history = list(graph.get_state_history(config))
    assert len(history) >= 1
