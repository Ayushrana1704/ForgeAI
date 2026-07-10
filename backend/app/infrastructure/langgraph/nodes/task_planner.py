"""
Task Planner node — LLM-backed implementation planning agent.

Responsibilities
----------------
- Read clarified_requirements and architecture_summary from ForgeState.
- Call LLMService to produce a structured implementation task plan.
- Parse the plan into a list of JSON-serialised task dicts stored in
  ForgeState.task_plan (list[str]).
- Store the full raw plan markdown in metadata["task_plan"] for human-readable
  access by downstream agents and API routes.
- Track token usage, cost, and execution time in ForgeState.
- Handle all LLM errors internally — never raise out of the node.

Node contract
-------------
- Input:  full ForgeState (read-only — do not mutate the received dict)
- Output: dict containing only the fields that changed
- Never raises — exceptions are caught, written to state["errors"], and
  execution_status is set to ExecutionStatus.FAILED.value
- Logging: only project_id, agent_name, token counts, and execution time.
  NEVER log prompts, task plan content, or generated output.

Factory pattern
---------------
Identical to Requirements Analyst and Software Architect: a closure factory
injects LLMService so the node is stateless and trivially testable.

    node_fn = make_task_planner_node(llm_service)
    builder.add_node("task_planner", node_fn)

task_plan storage format
------------------------
ForgeState.task_plan is list[str].  Each element is a JSON-serialised dict
with these keys:

    {
        "id":           str,        # e.g. "BE-001"
        "title":        str,        # human-readable title
        "category":     str,        # e.g. "Backend"
        "priority":     str,        # "High" | "Medium" | "Low"
        "complexity":   str,        # "High" | "Medium" | "Low"
        "description":  str,        # one-sentence deliverable description
        "dependencies": list[str]   # IDs of prerequisite tasks, may be empty
    }

Downstream agents can parse individual tasks with json.loads(task_str).
The full raw markdown is always available in metadata["task_plan"].

Guard conditions
----------------
Both clarified_requirements and architecture_summary must be non-empty.
If either is missing the node returns FAILED without calling the LLM, since
the plan would be meaningless without them.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.application.prompts.task_planner import (
    FIELD_COMPLEXITY,
    FIELD_DEPENDENCIES,
    FIELD_DESCRIPTION,
    FIELD_PRIORITY,
    REQUIRED_SECTIONS,
    build_task_planner_messages,
)
from app.application.services.llm.llm_service import LLMService
from app.application.services.llm.types import CompletionRequest
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.value_objects.agent_type import AgentType
from app.domain.workflow.forge_state import ForgeState
from app.domain.workflow.types import AgentResult, ExecutionStatus

logger = structlog.get_logger(__name__)

_AGENT_NAME: str = AgentType.TASK_PLANNER.value  # plain str, not StrEnum subtype

# Cost estimate: $0.150 / 1M input tokens, $0.600 / 1M output tokens (gpt-4o-mini pricing).
_COST_PER_INPUT_TOKEN: float = 0.000_000_150
_COST_PER_OUTPUT_TOKEN: float = 0.000_000_600


# ── Factory ───────────────────────────────────────────────────────────────────


def make_task_planner_node(
    llm_service: LLMService,
) -> Any:  # returns Callable[[ForgeState], Awaitable[dict[str, Any]]]
    """
    Return an async LangGraph node function bound to the given LLMService.

    Args:
        llm_service: Configured LLMService instance from the DI layer.

    Returns:
        Async callable compatible with StateGraph.add_node().
    """

    async def task_planner_node(state: ForgeState) -> dict[str, Any]:
        """
        Task Planner node — generates a structured implementation task plan.

        On success, populates:
          - task_plan         (list[str] of JSON-serialised task dicts)
          - metadata          (merged with {"task_plan": <raw markdown>})
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

        if not clarified:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Task Planner cannot run: clarified_requirements is empty. "
                    "Requirements Analyst must complete successfully first."
                ),
                log=log,
            )

        if not architecture:
            return _failure_changes(
                state=state,
                wall_start=wall_start,
                error_msg=(
                    "Task Planner cannot run: architecture_summary is empty. "
                    "Software Architect must complete successfully first."
                ),
                log=log,
            )

        # ── Build request ─────────────────────────────────────────────────
        messages = build_task_planner_messages(
            clarified_requirements=clarified,
            architecture_summary=architecture,
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
                error_msg=f"Unexpected error in task planner: {type(exc).__name__}",
                log=log,
            )

        # ── Parse response ────────────────────────────────────────────────
        plan_markdown: str = response.content.strip()
        task_plan: list[str] = _parse_task_plan(plan_markdown)

        # Merge new task_plan key into existing metadata (dict[str, str])
        updated_metadata: dict[str, str] = {
            **state["metadata"],
            "task_plan": plan_markdown,
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
            task_count=len(task_plan),
        )

        agent_result: AgentResult = {
            "agent_name": _AGENT_NAME,
            "status": ExecutionStatus.COMPLETED.value,
            "summary": (
                f"Implementation plan generated: {len(task_plan)} tasks across "
                "Backend, Frontend, Database, Infrastructure, Testing, and Deployment."
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
            "task_plan": task_plan,
            "metadata": updated_metadata,
            "total_tokens": state["total_tokens"] + tokens_used,
            "estimated_cost": state["estimated_cost"] + cost_usd,
            "model_used": response.model,
            "agent_results": list(state["agent_results"]) + [agent_result],
        }

    return task_planner_node


# ── Parsing ───────────────────────────────────────────────────────────────────


def _parse_task_plan(markdown: str) -> list[str]:
    """
    Parse the full task plan markdown into a list of JSON-serialised task dicts.

    Each element in the returned list is a valid JSON string that can be
    deserialised with json.loads() into a dict with these keys:
        id, title, category, priority, complexity, description, dependencies

    Tasks that cannot be parsed (malformed H3 blocks) are skipped silently
    to keep the node from failing on minor LLM formatting deviations.

    Args:
        markdown: Raw LLM response, expected to contain H2 sections with H3
                  task blocks as defined in the prompt output contract.

    Returns:
        List of JSON strings, one per successfully parsed task.
    """
    tasks: list[str] = []

    for section_heading in REQUIRED_SECTIONS:
        section_body = _extract_section(markdown, section_heading)
        if not section_body:
            continue

        # Derive a clean category name from the heading ("## Backend Tasks" → "Backend")
        category = section_heading.lstrip("# ").replace(" Tasks", "").strip()

        # Split the section body into H3 blocks; each starts with "###"
        h3_blocks = re.split(r"\n(?=###\s)", "\n" + section_body)
        for block in h3_blocks:
            block = block.strip()
            if not block.startswith("###"):
                continue
            parsed = _parse_task_block(block, category)
            if parsed is not None:
                tasks.append(json.dumps(parsed, ensure_ascii=False))

    return tasks


def _parse_task_block(block: str, category: str) -> dict[str, Any] | None:
    """
    Parse a single H3 task block into a dict.

    Expected format:
        ### BE-001: Set up FastAPI project structure
        - **Priority:** High
        - **Complexity:** Low
        - **Description:** Initialize FastAPI application with Clean Architecture.
        - **Dependencies:** None

    Args:
        block:    Raw text of one H3 block (heading + bullet lines).
        category: Category name derived from the parent H2 heading.

    Returns:
        Parsed task dict, or None if the block is too malformed to use.
    """
    lines = block.splitlines()
    if not lines:
        return None

    # ── Title / ID ────────────────────────────────────────────────────────
    raw_title = lines[0].lstrip("# ").strip()
    # Split "BE-001: Title text" into id and title
    if ":" in raw_title:
        task_id, _, title = raw_title.partition(":")
        task_id = task_id.strip()
        title = title.strip()
    else:
        task_id = ""
        title = raw_title

    if not title:
        return None

    # ── Bullet fields ─────────────────────────────────────────────────────
    priority = "Medium"
    complexity = "Medium"
    description = ""
    dependencies: list[str] = []

    for line in lines[1:]:
        stripped = line.strip()
        if FIELD_PRIORITY in stripped:
            priority = stripped.split(FIELD_PRIORITY, 1)[-1].strip()
        elif FIELD_COMPLEXITY in stripped:
            complexity = stripped.split(FIELD_COMPLEXITY, 1)[-1].strip()
        elif FIELD_DESCRIPTION in stripped:
            description = stripped.split(FIELD_DESCRIPTION, 1)[-1].strip()
        elif FIELD_DEPENDENCIES in stripped:
            raw_deps = stripped.split(FIELD_DEPENDENCIES, 1)[-1].strip()
            if raw_deps.lower() not in ("none", ""):
                dependencies = [d.strip() for d in raw_deps.split(",") if d.strip()]

    return {
        "id": task_id,
        "title": title,
        "category": category,
        "priority": priority,
        "complexity": complexity,
        "description": description,
        "dependencies": dependencies,
    }


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
        "summary": "Task planning failed — see error_message for details.",
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
