"""
ForgeAI LangGraph workflow -- graph factory.

Current topology
----------------

    START
      |
      v
  requirements_analyst   (LLM-backed: clarifies and structures requirements)
      |
      v
  software_architect     (LLM-backed: designs the full software architecture)
      |
      v
  task_planner           (LLM-backed: generates structured implementation plan)
      |
      v
  database_designer      (LLM-backed: designs the relational database schema)
      |
      v
  backend_generator      (LLM-backed: generates backend implementation blueprint)
      |
      v
  frontend_generator     (LLM-backed: generates frontend implementation blueprint)
      |
      v
  reviewer               (LLM-backed: cross-cutting review of the complete plan)
      |
      v
  refiner                (LLM-backed: targeted improvements from review findings)
      |
      v
  artifact_packager      (in-memory artifact assembly -- no LLM call)
      |
      v
     END

Checkpointing
-------------
Every invocation must pass a LangGraph config dict that includes a
thread_id.  This thread_id is the stable identifier for one workflow run
(use AgentRun.id):

    config = {"configurable": {"thread_id": str(agent_run_id)}}
    result = await graph.ainvoke(initial_state, config=config)

Without a thread_id, LangGraph cannot persist checkpoints.

Clean Architecture note
-----------------------
This file lives in Infrastructure because it depends on LangGraph (an
external library).  The Domain layer (ForgeState, node logic contracts)
remains framework-independent.  If LangGraph is ever replaced, only this
file and the node implementations change.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.application.services.llm.llm_service import LLMService
from app.domain.workflow.forge_state import ForgeState
from app.infrastructure.langgraph.checkpoint import create_checkpointer
from app.infrastructure.langgraph.nodes.artifact_packager import (
    make_artifact_packager_node,
)
from app.infrastructure.langgraph.nodes.backend_generator import (
    make_backend_generator_node,
)
from app.infrastructure.langgraph.nodes.database_designer import (
    make_database_designer_node,
)
from app.infrastructure.langgraph.nodes.frontend_generator import (
    make_frontend_generator_node,
)
from app.infrastructure.langgraph.nodes.refiner import (
    make_refiner_node,
)
from app.infrastructure.langgraph.nodes.requirements_analyst import (
    make_requirements_analyst_node,
)
from app.infrastructure.langgraph.nodes.reviewer import (
    make_reviewer_node,
)
from app.infrastructure.langgraph.nodes.software_architect import (
    make_software_architect_node,
)
from app.infrastructure.langgraph.nodes.task_planner import (
    make_task_planner_node,
)


def build_forge_graph(
    llm_service: LLMService,
    checkpointer: MemorySaver | None = None,
) -> CompiledStateGraph:
    """
    Build and compile the ForgeAI StateGraph.

    Args:
        llm_service:  LLMService instance to inject into node closures.
                      Typically the singleton from api/dependencies.py.
        checkpointer: LangGraph checkpointer instance.  If None, a fresh
                      MemorySaver is created.  For production, pass an
                      AsyncPostgresSaver connected to the ForgeAI database.

    Returns:
        Compiled LangGraph application ready to call .ainvoke() / .astream().
    """
    builder: StateGraph = StateGraph(ForgeState)

    # Nodes
    builder.add_node(
        "requirements_analyst",
        make_requirements_analyst_node(llm_service),
    )
    builder.add_node(
        "software_architect",
        make_software_architect_node(llm_service),
    )
    builder.add_node(
        "task_planner",
        make_task_planner_node(llm_service),
    )
    builder.add_node(
        "database_designer",
        make_database_designer_node(llm_service),
    )
    builder.add_node(
        "backend_generator",
        make_backend_generator_node(llm_service),
    )
    builder.add_node(
        "frontend_generator",
        make_frontend_generator_node(llm_service),
    )
    builder.add_node(
        "reviewer",
        make_reviewer_node(llm_service),
    )
    builder.add_node(
        "refiner",
        make_refiner_node(llm_service),
    )
    builder.add_node(
        "artifact_packager",
        make_artifact_packager_node(),
    )

    # Edges
    builder.add_edge(START, "requirements_analyst")
    builder.add_edge("requirements_analyst", "software_architect")
    builder.add_edge("software_architect", "task_planner")
    builder.add_edge("task_planner", "database_designer")
    builder.add_edge("database_designer", "backend_generator")
    builder.add_edge("backend_generator", "frontend_generator")
    builder.add_edge("frontend_generator", "reviewer")
    builder.add_edge("reviewer", "refiner")
    builder.add_edge("refiner", "artifact_packager")
    builder.add_edge("artifact_packager", END)

    # Compile
    resolved_checkpointer = (
        checkpointer if checkpointer is not None else create_checkpointer()
    )
    return builder.compile(checkpointer=resolved_checkpointer)
