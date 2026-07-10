"""
Frontend Generator node — LLM-backed frontend implementation blueprint agent.

Responsibilities
----------------
- Read clarified_requirements, architecture_summary, task_plan, and
  backend_code_summary from ForgeState.
- Extract frontend-relevant tasks from task_plan to provide focused context.
- Call LLMService to produce a full frontend implementation blueprint document.
- Store the blueprint in frontend_code_summary (str | None) and
  metadata["frontend"].
- Track token usage, cost, and execution time in ForgeState.
- Handle all LLM errors internally — never raise out of the node.

IMPORTANT: This node generates a BLUEPRINT document only.
           It does NOT generate actual React source code, JSX, or TypeScript.
           Real code artifacts are produced in a later milestone.

Node contract
-------------
- Input:  full ForgeState (read-only — do not mutate the received dict)
- Output: dict containing only the fields that changed
- Never raises — exceptions are caught, written to state["errors"], and
  execution_status is set to ExecutionStatus.FAILED.value
- Logging: only project_id, agent_name, token counts, and execution time.
  NEVER log prompts, blueprint content, or generated output.

Factory pattern
---------------
Identical to all preceding agents: a closure factory injects LLMService
so the node is stateless and trivially testable.

    node_fn = make_frontend_generator_node(llm_service)
    builder.add_node("frontend_generator", node_fn)

frontend_code_summary storage
------------------------------
ForgeState.frontend_code_summary is str | None.  The full blueprint document
(raw markdown) is stored there.  An identical copy is placed in
metadata["frontend"] for downstream agents.

task_plan context extraction
----------------------------
The Task Planner stores each task as a JSON string in state["task_plan"].
This node deserialises every task and filters to those whose category is
"Frontend" (case-insensitive).  The filtered tasks are formatted as a compact
bullet list.  If no frontend tasks are found, a placeholder note is passed.

Guard conditions
----------------
All four of the following must be present and non-empty:
  - clarified_requirements  (from Requirements Analyst)
  - architecture_summary    (from Software Architect)
  - task_plan               (from Task Planner — must be a non-empty list)
  - backend_code_summary    (from Backend Generator)
If any guard fails the node returns FAILED without calling the LLM.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.application.prompts.frontend_generator import (
    REQUIRED_SECTIONS,
    build_frontend_generator_messages,
)
from app.application.services.llm.llm_service import LLMService
from app.application.services.llm.types import CompletionRequest
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.value_objects.agent_type import AgentType
from app.domain.workflow.forge_state import ForgeState
from app.domain.workflow.types import AgentResult, ExecutionStatus

logger = structlog.get_logger(__name__)

_AGENT_NAME: str = AgentType.FRONTEND_GENERATOR.value  # plain str, not StrEnum subtype

# Cost estimate: $0.150 / 1M input tokens, $0.600 / 1M output tokens (gpt-4o-mini pricing).
_COST_PER_INPUT_TOKEN: float = 0.000_000_150
_COST_PER_OUTPUT_TOKEN: float = 0.000_000_600


def make_frontend_generator_node(llm_service: LLMService) -> Any:
    """
    Factory that returns a Frontend Generator node function.

    The returned coroutine closes over *llm_service* so the node is stateless
    and can be injected with a mock during testing.

    Args:
        llm_service: The application-level LLM abstraction to call.

    Returns:
        An async function with signature (state: ForgeState) -> dict[str, Any]
        suitable for use with LangGraph's StateGraph.add_node().
    """

    async def frontend_generator_node(state: ForgeState) -> dict[str, Any]:
        wall_start = time.monotonic()
        project_id: str = state.get("project_id", "unknown")
        log = logger.bind(project_id=project_id, agent_name=_AGENT_NAME)

        log.info("node_enter")

        # ── Guard: clarified_requirements ─────────────────────────────────
        clarified: str | None = state.get("clarified_requirements")
        if not clarified or not clarified.strip():
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Frontend Generator cannot run: clarified_requirements is missing. "
                    "Requirements Analyst must complete successfully first."
                ),
                log=log,
            )

        # ── Guard: architecture_summary ───────────────────────────────────
        architecture: str | None = state.get("architecture_summary")
        if not architecture or not architecture.strip():
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Frontend Generator cannot run: architecture_summary is missing. "
                    "Software Architect must complete successfully first."
                ),
                log=log,
            )

        # ── Guard: task_plan ──────────────────────────────────────────────
        task_plan: list[str] = state.get("task_plan") or []
        if not task_plan:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Frontend Generator cannot run: task_plan is empty. "
                    "Task Planner must complete successfully first."
                ),
                log=log,
            )

        # ── Guard: backend_code_summary ───────────────────────────────────
        backend_blueprint: str | None = state.get("backend_code_summary")
        if not backend_blueprint or not backend_blueprint.strip():
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Frontend Generator cannot run: backend_code_summary is missing. "
                    "Backend Generator must complete successfully first."
                ),
                log=log,
            )

        # ── Extract frontend tasks for focused context ────────────────────
        frontend_task_summary = _extract_frontend_task_summary(task_plan)

        # ── Build request ─────────────────────────────────────────────────
        messages = build_frontend_generator_messages(
            clarified_requirements=clarified,
            architecture_summary=architecture,
            backend_code_summary=backend_blueprint,
            frontend_task_summary=frontend_task_summary,
        )
        request = CompletionRequest(messages=messages)

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
                error_msg=f"Unexpected error in frontend generator: {type(exc).__name__}",
                log=log,
            )

        # ── Store result ──────────────────────────────────────────────────
        blueprint_doc: str = response.content.strip()
        updated_metadata: dict[str, str] = {
            **state["metadata"],
            "frontend": blueprint_doc,
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
                "Frontend implementation blueprint generated across ten sections: "
                "Application Structure, Feature Organization, Routing, State Management, "
                "API Integration, Authentication Flow, UI Components, Forms & Validation, "
                "Error Handling, Testing Strategy."
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
            "frontend_code_summary": blueprint_doc,
            "metadata": updated_metadata,
            "total_tokens": state["total_tokens"] + tokens_used,
            "estimated_cost": state["estimated_cost"] + cost_usd,
            "model_used": response.model,
            "agent_results": list(state["agent_results"]) + [agent_result],
        }

    return frontend_generator_node


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_frontend_task_summary(task_plan: list[str]) -> str:
    """
    Extract frontend-related tasks from the task_plan and format as a bullet list.

    Each element of task_plan is a JSON string produced by the Task Planner.
    This function filters tasks whose category is "Frontend" (case-insensitive)
    and formats them as a compact summary for the LLM prompt.

    Args:
        task_plan: List of JSON-serialised task dicts from ForgeState.task_plan.

    Returns:
        Formatted bullet list of frontend tasks, or a placeholder note if none
        are found.
    """
    frontend_tasks: list[str] = []
    for raw in task_plan:
        try:
            task = json.loads(raw)
            if task.get("category", "").lower() == "frontend":
                task_id = task.get("id", "")
                title = task.get("title", "")
                desc = task.get("description", "")
                priority = task.get("priority", "")
                prefix = f"{task_id}: " if task_id else ""
                frontend_tasks.append(f"- [{priority}] {prefix}{title} — {desc}")
        except (json.JSONDecodeError, AttributeError):
            # Skip malformed task entries silently
            continue

    if not frontend_tasks:
        return (
            "No explicit frontend tasks found in plan; "
            "infer frontend structure from requirements and architecture."
        )

    return "\n".join(frontend_tasks)


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
        "summary": "Frontend blueprint generation failed — see error_message for details.",
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
