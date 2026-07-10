"""
Reviewer node — LLM-backed cross-cutting project plan review agent.

Responsibilities
----------------
- Read all six upstream outputs from ForgeState:
    clarified_requirements, architecture_summary, task_plan,
    database_schema, backend_code_summary, frontend_code_summary.
- Summarise task_plan into a flat text for the LLM context.
- Call LLMService to produce a structured review document covering nine
  concern categories.
- Parse the markdown into a list of section strings and store them in
  review_notes (list[str]).
- Store the full raw document in metadata["review"].
- Track token usage, cost, and execution time in ForgeState.
- Handle all LLM errors internally — never raise out of the node.

IMPORTANT: The Reviewer ONLY analyses and critiques.
           It MUST NOT modify any ForgeState field other than:
             review_notes, metadata["review"], and execution metadata
             (current_agent, completed_agents, execution_status,
              updated_at, total_tokens, estimated_cost, model_used,
              agent_results, errors).

review_notes storage
--------------------
ForgeState.review_notes is list[str].  The node splits the LLM markdown
on H2 headings and stores one element per section:
    ["## Missing Requirements\\n- ...", "## Architectural Inconsistencies\\n- ...", ...]
An identical copy of the full raw markdown is placed in metadata["review"]
for downstream agents that need the complete document.

Guard conditions
----------------
All six of the following must be present and non-empty:
  - clarified_requirements  (from Requirements Analyst)
  - architecture_summary    (from Software Architect)
  - task_plan               (from Task Planner — must be a non-empty list)
  - database_schema         (from Database Designer)
  - backend_code_summary    (from Backend Generator)
  - frontend_code_summary   (from Frontend Generator)
If any guard fails the node returns FAILED without calling the LLM.

Node contract
-------------
- Input:  full ForgeState (read-only — do not mutate the received dict)
- Output: dict containing only the fields that changed
- Never raises — exceptions are caught, written to state["errors"], and
  execution_status is set to ExecutionStatus.FAILED.value
- Logging: only project_id, agent_name, token counts, and execution time.
  NEVER log prompts, review content, or any generated output.

Factory pattern
---------------
    node_fn = make_reviewer_node(llm_service)
    builder.add_node("reviewer", node_fn)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.application.prompts.reviewer import (
    REQUIRED_SECTIONS,
    build_reviewer_messages,
)
from app.application.services.llm.llm_service import LLMService
from app.application.services.llm.types import CompletionRequest
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.value_objects.agent_type import AgentType
from app.domain.workflow.forge_state import ForgeState
from app.domain.workflow.types import AgentResult, ExecutionStatus

logger = structlog.get_logger(__name__)

_AGENT_NAME: str = AgentType.REVIEWER.value  # plain str, not StrEnum subtype

# Cost estimate: $0.150 / 1M input tokens, $0.600 / 1M output tokens (gpt-4o-mini pricing).
_COST_PER_INPUT_TOKEN: float = 0.000_000_150
_COST_PER_OUTPUT_TOKEN: float = 0.000_000_600


def make_reviewer_node(llm_service: LLMService) -> Any:
    """
    Factory that returns a Reviewer node function.

    The returned coroutine closes over *llm_service* so the node is stateless
    and can be injected with a mock during testing.

    Args:
        llm_service: The application-level LLM abstraction to call.

    Returns:
        An async function with signature (state: ForgeState) -> dict[str, Any]
        suitable for use with LangGraph's StateGraph.add_node().
    """

    async def reviewer_node(state: ForgeState) -> dict[str, Any]:
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
                    "Reviewer cannot run: clarified_requirements is missing. "
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
                    "Reviewer cannot run: architecture_summary is missing. "
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
                    "Reviewer cannot run: task_plan is empty. "
                    "Task Planner must complete successfully first."
                ),
                log=log,
            )

        # ── Guard: database_schema ────────────────────────────────────────
        db_schema: str | None = state.get("database_schema")
        if not db_schema or not db_schema.strip():
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Reviewer cannot run: database_schema is missing. "
                    "Database Designer must complete successfully first."
                ),
                log=log,
            )

        # ── Guard: backend_code_summary ───────────────────────────────────
        backend: str | None = state.get("backend_code_summary")
        if not backend or not backend.strip():
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Reviewer cannot run: backend_code_summary is missing. "
                    "Backend Generator must complete successfully first."
                ),
                log=log,
            )

        # ── Guard: frontend_code_summary ──────────────────────────────────
        frontend: str | None = state.get("frontend_code_summary")
        if not frontend or not frontend.strip():
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Reviewer cannot run: frontend_code_summary is missing. "
                    "Frontend Generator must complete successfully first."
                ),
                log=log,
            )

        # ── Format task plan for LLM context ─────────────────────────────
        task_plan_summary = _format_task_plan_summary(task_plan)

        # ── Build request ─────────────────────────────────────────────────
        messages = build_reviewer_messages(
            clarified_requirements=clarified,
            architecture_summary=architecture,
            task_plan_summary=task_plan_summary,
            database_schema=db_schema,
            backend_code_summary=backend,
            frontend_code_summary=frontend,
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
                error_msg=f"Unexpected error in reviewer: {type(exc).__name__}",
                log=log,
            )

        # ── Parse and store result ────────────────────────────────────────
        review_markdown: str = response.content.strip()
        review_notes: list[str] = _parse_review_sections(review_markdown)
        updated_metadata: dict[str, str] = {
            **state["metadata"],
            "review": review_markdown,
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
                f"Project plan reviewed across nine concern categories: "
                f"{len(review_notes)} sections produced."
            ),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "completed_at": now,
            "error_message": None,
        }

        # NOTE: Only review_notes and metadata["review"] are written.
        # No prior ForgeState fields (architecture_summary, database_schema,
        # backend_code_summary, frontend_code_summary, task_plan, etc.) are
        # modified or re-emitted.
        return {
            "current_agent": _AGENT_NAME,
            "completed_agents": list(state["completed_agents"]) + [_AGENT_NAME],
            "execution_status": ExecutionStatus.COMPLETED.value,
            "updated_at": now,
            "review_notes": review_notes,
            "metadata": updated_metadata,
            "total_tokens": state["total_tokens"] + tokens_used,
            "estimated_cost": state["estimated_cost"] + cost_usd,
            "model_used": response.model,
            "agent_results": list(state["agent_results"]) + [agent_result],
        }

    return reviewer_node


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_task_plan_summary(task_plan: list[str]) -> str:
    """
    Format the task_plan list into a compact summary for the LLM prompt.

    Each element of task_plan is a JSON string produced by the Task Planner.
    This function formats all tasks (regardless of category) as a grouped
    bullet list organised by category.

    Args:
        task_plan: List of JSON-serialised task dicts from ForgeState.task_plan.

    Returns:
        Formatted multi-line string.  Falls back to a placeholder if all
        entries are malformed.
    """
    by_category: dict[str, list[str]] = {}
    for raw in task_plan:
        try:
            task = json.loads(raw)
            category = task.get("category", "Uncategorised")
            task_id = task.get("id", "")
            title = task.get("title", "")
            priority = task.get("priority", "")
            prefix = f"{task_id}: " if task_id else ""
            line = f"  - [{priority}] {prefix}{title}"
            by_category.setdefault(category, []).append(line)
        except (json.JSONDecodeError, AttributeError):
            continue

    if not by_category:
        return "No task plan available; review based on requirements and blueprints."

    lines: list[str] = []
    for category, tasks in sorted(by_category.items()):
        lines.append(f"**{category}**")
        lines.extend(tasks)
    return "\n".join(lines)


def _parse_review_sections(markdown: str) -> list[str]:
    """
    Split a review document into a list of section strings.

    Each element contains the H2 heading and the body of one review section.
    Sections are extracted in the order they appear in REQUIRED_SECTIONS.
    If a section is absent from the LLM output, a placeholder is inserted.

    Args:
        markdown: Raw LLM response containing nine H2 review sections.

    Returns:
        List of strings, one per section, in REQUIRED_SECTIONS order.
    """
    sections: list[str] = []
    for heading in REQUIRED_SECTIONS:
        idx = markdown.find(heading)
        if idx == -1:
            sections.append(f"{heading}\n- No issues found.")
            continue

        content_start = markdown.find("\n", idx)
        if content_start == -1:
            sections.append(f"{heading}\n- No issues found.")
            continue
        content_start += 1

        remaining = markdown[content_start:]
        next_h2 = -1
        for other in REQUIRED_SECTIONS:
            if other == heading:
                continue
            pos = remaining.find(other)
            if pos != -1 and (next_h2 == -1 or pos < next_h2):
                next_h2 = pos

        body = remaining[:next_h2].strip() if next_h2 != -1 else remaining.strip()
        if not body:
            body = "- No issues found."
        sections.append(f"{heading}\n{body}")

    return sections


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
        "summary": "Project plan review failed — see error_message for details.",
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
