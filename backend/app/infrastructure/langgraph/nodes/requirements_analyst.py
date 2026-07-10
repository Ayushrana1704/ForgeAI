"""
Requirements Analyst node — real LLM-backed implementation.

Responsibilities
----------------
- Call LLMService to clarify and structure raw project requirements.
- Parse the structured markdown response into ForgeState fields.
- Track token usage, cost, and execution time in ForgeState.
- Handle all LLM errors internally — never raise out of the node.

Node contract
-------------
- Input:  full ForgeState (read-only — do not mutate the received dict)
- Output: dict containing only the fields that changed
- Never raises — exceptions are caught, written to state["errors"], and
  execution_status is set to ExecutionStatus.FAILED.value
- Logging: only project_id, agent_name, token counts, and execution time.
  NEVER log prompts, raw_requirements, or generated content.

Factory pattern
---------------
The node requires an LLMService, which is constructed by the DI layer
(api/dependencies.py) and lives outside the graph.  Rather than using a
global or class attribute, we use a closure factory so the node function
has no module-level mutable state and is trivially testable via injection.

    node_fn = make_requirements_analyst_node(llm_service)
    builder.add_node("requirements_analyst", node_fn)

LangGraph treats the returned async callable as the node; it is
functionally equivalent to a top-level async def.

Architecture summary extraction
--------------------------------
The architecture_summary field is populated with the Non-Functional
Requirements section from the LLM output.  This section is the closest
proxy for high-level architectural concerns until the Architect agent runs.
It is intentionally brief — the Architect agent will expand it.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog

from app.application.prompts.requirements_analyst import (
    REQUIRED_SECTIONS,
    SECTION_NON_FUNCTIONAL,
    build_requirements_analyst_messages,
)
from app.application.services.llm.llm_service import LLMService
from app.application.services.llm.types import CompletionRequest
from app.core.exceptions import LLMException, LLMUnavailableException
from app.domain.value_objects.agent_type import AgentType
from app.domain.workflow.forge_state import ForgeState
from app.domain.workflow.types import AgentResult, ExecutionStatus

logger = structlog.get_logger(__name__)

_AGENT_NAME: str = AgentType.REQUIREMENTS_ANALYST.value  # plain str, not StrEnum subtype

# Cost estimate: $0.150 / 1M input tokens, $0.600 / 1M output tokens (gpt-4o-mini pricing).
# Stored as floats so arithmetic stays simple; actual cost comes from the provider.
_COST_PER_INPUT_TOKEN: float = 0.000_000_150
_COST_PER_OUTPUT_TOKEN: float = 0.000_000_600


# ── Factory ───────────────────────────────────────────────────────────────────


def make_requirements_analyst_node(
    llm_service: LLMService,
) -> Any:  # returns Callable[[ForgeState], Awaitable[dict[str, Any]]]
    """
    Return an async LangGraph node function bound to the given LLMService.

    Args:
        llm_service: Configured LLMService instance from the DI layer.

    Returns:
        Async callable compatible with StateGraph.add_node().
    """

    async def requirements_analyst_node(state: ForgeState) -> dict[str, Any]:
        """
        Requirements Analyst node — clarifies and structures raw requirements.

        On success, populates:
          - clarified_requirements  (full structured markdown from LLM)
          - architecture_summary    (Non-Functional Requirements section)
          - current_agent           (_AGENT_NAME)
          - completed_agents        (appended)
          - execution_status        (COMPLETED)
          - agent_results           (appended AgentResult)
          - total_tokens            (incremented)
          - estimated_cost          (incremented)
          - model_used              (model string from response)
          - started_at              (preserved or set)
          - updated_at              (refreshed)

        On failure, populates:
          - errors                  (appended error description)
          - execution_status        (FAILED)
          - agent_results           (appended failed AgentResult)
          - current_agent, updated_at
        """
        log = logger.bind(project_id=state["project_id"], agent=_AGENT_NAME)
        log.info("node_enter", execution_status=state["execution_status"])

        started_at: str = state["started_at"] or datetime.now(timezone.utc).isoformat()
        wall_start: float = time.monotonic()

        # ── Build request ─────────────────────────────────────────────────
        messages = build_requirements_analyst_messages(state["raw_requirements"])
        request = CompletionRequest(messages=messages)

        # ── Call LLM ──────────────────────────────────────────────────────
        try:
            response = await llm_service.complete(request)
        except LLMUnavailableException as exc:
            return _failure_changes(
                state=state,
                started_at=started_at,
                wall_start=wall_start,
                error_msg=f"LLM provider unavailable: {exc.detail}",
                log=log,
            )
        except LLMException as exc:
            return _failure_changes(
                state=state,
                started_at=started_at,
                wall_start=wall_start,
                error_msg=f"LLM provider error: {exc.detail}",
                log=log,
            )
        except Exception as exc:  # noqa: BLE001 — broad catch intentional in node
            return _failure_changes(
                state=state,
                started_at=started_at,
                wall_start=wall_start,
                error_msg=f"Unexpected error in requirements analyst: {type(exc).__name__}",
                log=log,
            )

        # ── Parse response ────────────────────────────────────────────────
        clarified = response.content.strip()
        architecture_summary = _extract_section(clarified, SECTION_NON_FUNCTIONAL)

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
                "Requirements clarified and structured into six sections: "
                "Functional, Non-Functional, Assumptions, Missing Information, "
                "Risks, Suggested Improvements."
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
            "started_at": started_at,
            "updated_at": now,
            "clarified_requirements": clarified,
            "architecture_summary": architecture_summary,
            "total_tokens": state["total_tokens"] + tokens_used,
            "estimated_cost": state["estimated_cost"] + cost_usd,
            "model_used": response.model,
            "agent_results": list(state["agent_results"]) + [agent_result],
        }

    return requirements_analyst_node


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_section(markdown: str, heading: str) -> str | None:
    """
    Extract the content of a single markdown section identified by *heading*.

    Scans *markdown* for *heading* (H2 level) and returns everything between
    it and the next H2 heading (or end of string).  Returns None if the
    heading is not found.

    Args:
        markdown: Full structured markdown string from the LLM.
        heading:  Exact H2 heading string, e.g. "## Non-Functional Requirements".

    Returns:
        Section body text (stripped), or None if the heading is absent.
    """
    idx = markdown.find(heading)
    if idx == -1:
        return None

    # Content starts after the heading line
    content_start = markdown.find("\n", idx)
    if content_start == -1:
        return None
    content_start += 1  # skip the newline itself

    # Find next H2 heading that is NOT the current one
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
    started_at: str,
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
        "summary": "Requirements analysis failed — see error_message for details.",
        "tokens_used": 0,
        "cost_usd": 0.0,
        "duration_ms": duration_ms,
        "completed_at": now,
        "error_message": error_msg,
    }

    return {
        "current_agent": _AGENT_NAME,
        "execution_status": ExecutionStatus.FAILED.value,
        "started_at": started_at,
        "updated_at": now,
        "errors": list(state["errors"]) + [error_msg],
        "agent_results": list(state["agent_results"]) + [agent_result],
    }
