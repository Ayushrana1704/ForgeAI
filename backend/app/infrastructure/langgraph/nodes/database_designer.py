"""
Database Designer node — LLM-backed relational schema design agent.

Responsibilities
----------------
- Read clarified_requirements, architecture_summary, and task_plan from ForgeState.
- Extract database-relevant tasks from task_plan to provide focused context.
- Call LLMService to produce a full relational database schema document.
- Store the schema in database_schema (str | None) and metadata["database_schema"].
- Track token usage, cost, and execution time in ForgeState.
- Handle all LLM errors internally — never raise out of the node.

Node contract
-------------
- Input:  full ForgeState (read-only — do not mutate the received dict)
- Output: dict containing only the fields that changed
- Never raises — exceptions are caught, written to state["errors"], and
  execution_status is set to ExecutionStatus.FAILED.value
- Logging: only project_id, agent_name, token counts, and execution time.
  NEVER log prompts, schema content, or generated output.

Factory pattern
---------------
Identical to all preceding agents: a closure factory injects LLMService
so the node is stateless and trivially testable.

    node_fn = make_database_designer_node(llm_service)
    builder.add_node("database_designer", node_fn)

database_schema storage
-----------------------
ForgeState.database_schema is str | None.  The full schema document (raw
markdown) is stored there.  An identical copy is placed in
metadata["database_schema"] for downstream agents that prefer the flat
metadata dict over full state introspection.

task_plan context extraction
----------------------------
The Task Planner stores each task as a JSON string in state["task_plan"].
This node deserialises every task and filters to those whose category is
"Database" (case-insensitive).  The filtered tasks are formatted as a
compact bullet list and passed to the LLM as implementation context.
If no database tasks are found, the full task summary is omitted and a
placeholder note is passed instead.

Guard conditions
----------------
All three of the following must be present and non-empty:
  - clarified_requirements  (from Requirements Analyst)
  - architecture_summary    (from Software Architect)
  - task_plan               (from Task Planner — must be a non-empty list)
If any guard fails the node returns FAILED without calling the LLM.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.application.prompts.database_designer import (
    REQUIRED_SECTIONS,
    build_database_designer_messages,
)
from app.application.services.llm.llm_service import LLMService
from app.application.services.llm.types import CompletionRequest
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.value_objects.agent_type import AgentType
from app.domain.workflow.forge_state import ForgeState
from app.domain.workflow.types import AgentResult, ExecutionStatus

logger = structlog.get_logger(__name__)

_AGENT_NAME: str = AgentType.DATABASE_DESIGNER.value  # plain str, not StrEnum subtype

# Cost estimate: $0.150 / 1M input tokens, $0.600 / 1M output tokens (gpt-4o-mini pricing).
_COST_PER_INPUT_TOKEN: float = 0.000_000_150
_COST_PER_OUTPUT_TOKEN: float = 0.000_000_600


# ── Factory ───────────────────────────────────────────────────────────────────


def make_database_designer_node(
    llm_service: LLMService,
) -> Any:  # returns Callable[[ForgeState], Awaitable[dict[str, Any]]]
    """
    Return an async LangGraph node function bound to the given LLMService.

    Args:
        llm_service: Configured LLMService instance from the DI layer.

    Returns:
        Async callable compatible with StateGraph.add_node().
    """

    async def database_designer_node(state: ForgeState) -> dict[str, Any]:
        """
        Database Designer node — designs the relational database schema.

        On success, populates:
          - database_schema   (full schema document as raw markdown)
          - metadata          (merged with {"database_schema": <document>})
          - current_agent     (_AGENT_NAME)
          - completed_agents  (appended)
          - execution_status  (COMPLETED)
          - agent_results     (appended AgentResult)
          - total_tokens      (incremented)
          - estimated_cost    (incremented)
          - model_used        (model string from response)
          - updated_at        (refreshed)

        On failure, populates:
          - errors            (appended error description)
          - execution_status  (FAILED)
          - agent_results     (appended failed AgentResult)
          - current_agent, updated_at
        """
        log = logger.bind(project_id=state["project_id"], agent=_AGENT_NAME)
        log.info("node_enter", execution_status=state["execution_status"])

        wall_start: float = time.monotonic()

        # ── Guards ────────────────────────────────────────────────────────
        clarified = state.get("clarified_requirements")  # type: ignore[attr-defined]
        architecture = state.get("architecture_summary")  # type: ignore[attr-defined]
        task_plan = state.get("task_plan")  # type: ignore[attr-defined]

        if not clarified:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Database Designer cannot run: clarified_requirements is empty. "
                    "Requirements Analyst must complete successfully first."
                ),
                log=log,
            )

        if not architecture:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Database Designer cannot run: architecture_summary is empty. "
                    "Software Architect must complete successfully first."
                ),
                log=log,
            )

        if not task_plan:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Database Designer cannot run: task_plan is empty. "
                    "Task Planner must complete successfully first."
                ),
                log=log,
            )

        # ── Extract database tasks for focused context ────────────────────
        task_plan_summary = _extract_db_task_summary(task_plan)

        # ── Build request ─────────────────────────────────────────────────
        messages = build_database_designer_messages(
            clarified_requirements=clarified,
            architecture_summary=architecture,
            task_plan_summary=task_plan_summary,
        )
        request = CompletionRequest(
            messages=messages,
            max_tokens=700,
        )

        # ── Call LLM ──────────────────────────────────────────────────────
        try:
            response = await llm_service.complete(request)
        except LLMUnavailableException as exc:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=f"LLM provider unavailable: {exc.detail}",
                log=log,
            )
        except LLMException as exc:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=f"LLM provider error: {exc.detail}",
                log=log,
            )
        except Exception as exc:  # noqa: BLE001 — broad catch intentional in node
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=f"Unexpected error in database designer: {type(exc).__name__}",
                log=log,
            )

        # ── Store result ──────────────────────────────────────────────────
        schema_doc: str = response.content.strip()
        updated_metadata: dict[str, str] = {
            **state["metadata"],
            "database_schema": schema_doc,
        }

        # ── Telemetry ─────────────────────────────────────────────────────
        tokens_used: int = response.usage.total_tokens
        cost_usd: float = (
            response.usage.prompt_tokens * _COST_PER_INPUT_TOKEN
            + response.usage.completion_tokens * _COST_PER_OUTPUT_TOKEN
        )
        duration_ms: int = int((time.monotonic() - wall_start) * 1000)
        now: str = datetime.now(timezone.utc).isoformat()

        log.info(
            "node_exit",
            execution_status=ExecutionStatus.COMPLETED.value,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
        )

        agent_result: AgentResult = {
            "agent_name": _AGENT_NAME,
            "status": ExecutionStatus.COMPLETED.value,
            "summary": (
                "Database schema designed across eight sections: "
                "Entities, Attributes, Relationships, Primary Keys, "
                "Foreign Keys, Constraints, Indexes, Normalization Notes."
            ),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "completed_at": now,
            "error_message": None,
        }

        return {
            "current_agent": _AGENT_NAME,
            "completed_agents": list(state["completed_agents"]) + [_AGENT_NAME],
            "execution_status": ExecutionStatus.COMPLETED.value,
            "updated_at": now,
            "database_schema": schema_doc,
            "metadata": updated_metadata,
            "total_tokens": state["total_tokens"] + tokens_used,
            "estimated_cost": state["estimated_cost"] + cost_usd,
            "model_used": response.model,
            "agent_results": list(state["agent_results"]) + [agent_result],
        }

    return database_designer_node


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_db_task_summary(task_plan: list[str]) -> str:
    """
    Extract database-related tasks from the task_plan and format as a bullet list.

    Each element of task_plan is a JSON string produced by the Task Planner.
    This function filters tasks whose category is "Database" and formats them
    as a compact summary for the LLM prompt.

    Args:
        task_plan: List of JSON-serialised task dicts from ForgeState.task_plan.

    Returns:
        Formatted bullet list of database tasks, or a note if none are found.
    """
    db_tasks: list[str] = []
    for raw in task_plan:
        try:
            task = json.loads(raw)
            if task.get("category", "").lower() == "database":
                task_id = task.get("id", "")
                title = task.get("title", "")
                desc = task.get("description", "")
                priority = task.get("priority", "")
                prefix = f"{task_id}: " if task_id else ""
                db_tasks.append(f"- [{priority}] {prefix}{title} — {desc}")
        except (json.JSONDecodeError, AttributeError):
            # Skip malformed task entries silently
            continue

    if not db_tasks:
        return "No explicit database tasks found in plan; infer schema from requirements and architecture."

    return "\n".join(db_tasks)


def _extract_section(markdown: str, heading: str) -> str | None:
    """
    Extract the content of a single markdown section identified by *heading*.

    Returns everything between *heading* and the next H2 heading (or end of
    string).  Returns None if the heading is not found or the body is empty.
    """
    idx = markdown.find(heading)
    if idx == -1:
        return None

    content_start = markdown.find("\n", idx)
    if content_start == -1:
        return None
    content_start += 1

    remaining = markdown[content_start:]
    next_h2 = -1
    for section in REQUIRED_SECTIONS:
        if section == heading:
            continue
        pos = remaining.find(section)
        if pos != -1 and (next_h2 == -1 or pos < next_h2):
            next_h2 = pos

    body = remaining[:next_h2].strip() if next_h2 != -1 else remaining.strip()
    return body or None


def _failure_changes(
    state: ForgeState,
    wall_start: float,
    error_msg: str,
    log: Any,
) -> dict[str, Any]:
    """
    Build the state-update dict for a failed node execution.

    Appends *error_msg* to state["errors"], sets execution_status to FAILED,
    and records a failed AgentResult.  Does NOT raise.
    """
    duration_ms = int((time.monotonic() - wall_start) * 1000)
    now = datetime.now(timezone.utc).isoformat()

    log.error("node_failed", error=error_msg, duration_ms=duration_ms)

    agent_result: AgentResult = {
        "agent_name": _AGENT_NAME,
        "status": ExecutionStatus.FAILED.value,
        "summary": "Database schema design failed — see error_message for details.",
        "tokens_used": 0,
        "cost_usd": 0.0,
        "duration_ms": duration_ms,
        "completed_at": now,
        "error_message": error_msg,
    }

    return {
        "current_agent": _AGENT_NAME,
        "execution_status": ExecutionStatus.FAILED.value,
        "updated_at": now,
        "errors": list(state["errors"]) + [error_msg],
        "agent_results": list(state["agent_results"]) + [agent_result],
    }
