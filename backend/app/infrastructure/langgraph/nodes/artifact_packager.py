"""
Artifact Packager node — in-memory artifact assembly agent.

Responsibilities
----------------
- Read all eight upstream outputs from ForgeState.
- Assemble nine ArtifactInfo descriptors (one per generated document).
- Write each artifact to disk under ARTIFACT_STORAGE_PATH (non-blocking).
- Populate ArtifactInfo.content so WorkflowService can persist it to the DB.
- Build the project_summary.md content and store it in metadata["project_summary"].
- Store all nine ArtifactInfo records in ForgeState.artifacts.

IMPORTANT: This agent does NOT call the LLM.

Node contract
-------------
- Input:  full ForgeState (read-only — do not mutate the received dict)
- Output: dict containing only the fields that changed
- Never raises — exceptions are caught, written to state["errors"], and
  execution_status is set to ExecutionStatus.FAILED.value
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from app.core.config import settings
from app.domain.value_objects.agent_type import AgentType
from app.domain.value_objects.artifact_type import ArtifactType
from app.domain.workflow.forge_state import ForgeState
from app.domain.workflow.types import AgentResult, ArtifactInfo, ExecutionStatus

logger = structlog.get_logger(__name__)

_AGENT_NAME: str = AgentType.ARTIFACT_PACKAGER.value

# Stable path constants — used in ArtifactInfo.path and by API endpoints.
_PATH_REQUIREMENTS = "docs/requirements.md"
_PATH_ARCHITECTURE = "docs/architecture.md"
_PATH_TASK_PLAN = "docs/task_plan.md"
_PATH_DATABASE_DESIGN = "docs/database_design.md"
_PATH_BACKEND_BLUEPRINT = "docs/backend_blueprint.md"
_PATH_FRONTEND_BLUEPRINT = "docs/frontend_blueprint.md"
_PATH_REVIEW = "docs/review.md"
_PATH_REFINEMENT = "docs/refinement.md"
_PATH_PROJECT_SUMMARY = "docs/project_summary.md"

ARTIFACT_PATHS: tuple[str, ...] = (
    _PATH_REQUIREMENTS,
    _PATH_ARCHITECTURE,
    _PATH_TASK_PLAN,
    _PATH_DATABASE_DESIGN,
    _PATH_BACKEND_BLUEPRINT,
    _PATH_FRONTEND_BLUEPRINT,
    _PATH_REVIEW,
    _PATH_REFINEMENT,
    _PATH_PROJECT_SUMMARY,
)



def make_artifact_packager_node() -> Any:
    """
    Factory that returns an Artifact Packager node function.

    Returns:
        Async function (state: ForgeState) -> dict[str, Any] for LangGraph.
    """

    async def artifact_packager_node(state: ForgeState) -> dict[str, Any]:
        wall_start = time.monotonic()
        project_id: str = state.get("project_id", "unknown")
        log = logger.bind(project_id=project_id, agent_name=_AGENT_NAME)

        log.info("node_enter")

        # ── Guards ─────────────────────────────────────────────────────────
        clarified: str | None = state.get("clarified_requirements")
        if not clarified or not clarified.strip():
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: clarified_requirements is missing. "
                "Requirements Analyst must complete successfully first."
            ), log)

        architecture: str | None = state.get("architecture_summary")
        if not architecture or not architecture.strip():
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: architecture_summary is missing. "
                "Software Architect must complete successfully first."
            ), log)

        task_plan: list[str] = state.get("task_plan") or []
        if not task_plan:
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: task_plan is empty. "
                "Task Planner must complete successfully first."
            ), log)

        db_schema: str | None = state.get("database_schema")
        if not db_schema or not db_schema.strip():
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: database_schema is missing. "
                "Database Designer must complete successfully first."
            ), log)

        backend: str | None = state.get("backend_code_summary")
        if not backend or not backend.strip():
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: backend_code_summary is missing. "
                "Backend Generator must complete successfully first."
            ), log)

        frontend: str | None = state.get("frontend_code_summary")
        if not frontend or not frontend.strip():
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: frontend_code_summary is missing. "
                "Frontend Generator must complete successfully first."
            ), log)

        review_notes: list[str] = state.get("review_notes") or []
        if not review_notes:
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: review_notes is empty. "
                "Reviewer must complete successfully first."
            ), log)

        current_meta: dict[str, str] = state.get("metadata") or {}
        refined: str = current_meta.get("refined", "")
        if not refined or not refined.strip():
            return _failure_changes(state, wall_start, (
                "Artifact Packager cannot run: metadata['refined'] is missing. "
                "Refiner must complete successfully first."
            ), log)

        log.info(
            "artifact_content_lengths",
            requirements=len(clarified),
            architecture=len(architecture),
            database=len(db_schema),
            backend=len(backend),
            frontend=len(frontend),
            review=sum(len(x) for x in review_notes),
            refinement=len(refined),
        )    

        # ── Assemble artifacts ─────────────────────────────────────────────
        try:
            review_content: str = current_meta.get("review", "\n\n".join(review_notes))
            project_summary: str = _build_project_summary(
                project_name=state.get("project_name", ""),
                project_id=project_id,
                clarified=clarified,
                architecture=architecture,
                task_plan=task_plan,
                db_schema=db_schema,
                backend=backend,
                frontend=frontend,
                review_notes=review_notes,
                refined=refined,
            )

            artifacts: list[ArtifactInfo] = [
                _make_artifact(_PATH_REQUIREMENTS, clarified,
                               "Clarified and structured project requirements"),
                _make_artifact(_PATH_ARCHITECTURE, architecture,
                               "Software architecture design document"),
                _make_artifact(_PATH_TASK_PLAN, _format_task_plan_markdown(task_plan),
                               "Implementation task plan (all categories)"),
                _make_artifact(_PATH_DATABASE_DESIGN, db_schema,
                               "Relational database schema design"),
                _make_artifact(_PATH_BACKEND_BLUEPRINT, backend,
                               "Backend implementation blueprint"),
                _make_artifact(_PATH_FRONTEND_BLUEPRINT, frontend,
                               "Frontend implementation blueprint"),
                _make_artifact(_PATH_REVIEW, review_content,
                               "Cross-cutting plan review findings (nine categories)"),
                _make_artifact(_PATH_REFINEMENT, refined,
                               "Targeted improvement notes from review findings"),
                _make_artifact(_PATH_PROJECT_SUMMARY, project_summary,
                               "Executive project summary across all agents"),
            ]
        except Exception as exc:  # noqa: BLE001
            return _failure_changes(state, wall_start,
                                    f"Artifact assembly error: {type(exc).__name__}: {exc}", log)

        # ── Write to disk (best-effort, non-blocking) ──────────────────────
        base_path = Path(settings.ARTIFACT_STORAGE_PATH) / project_id
        try:
            await asyncio.to_thread(_write_artifacts_to_disk, base_path, artifacts)
        except Exception as exc:  # noqa: BLE001
            # Disk write failure is non-fatal — content is still in DB
            log.warning("artifact_disk_write_failed", error=str(exc))

        # ── Build state update ─────────────────────────────────────────────
        updated_metadata: dict[str, str] = {**current_meta, "project_summary": project_summary}

        artifact_count = len(artifacts)
        duration_ms = int((time.monotonic() - wall_start) * 1000)
        now = datetime.now(timezone.utc).isoformat()

        log.info(
            "node_exit",
            execution_status=ExecutionStatus.COMPLETED.value,
            artifact_count=artifact_count,
            duration_ms=duration_ms,
        )

        agent_result: AgentResult = {
            "agent_name": _AGENT_NAME,
            "status": ExecutionStatus.COMPLETED.value,
            "summary": (
                f"Assembled {artifact_count} artifacts: "
                + ", ".join(p.split("/")[-1] for p in ARTIFACT_PATHS)
            ),
            "tokens_used": 0,
            "cost_usd": 0.0,
            "duration_ms": duration_ms,
            "completed_at": now,
            "error_message": None,
        }

        return {
            "current_agent": _AGENT_NAME,
            "completed_agents": list(state["completed_agents"]) + [_AGENT_NAME],
            "execution_status": ExecutionStatus.COMPLETED.value,
            "updated_at": now,
            "artifacts": artifacts,
            "metadata": updated_metadata,
            "agent_results": list(state["agent_results"]) + [agent_result],
        }

    return artifact_packager_node


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_artifact(path: str, content: str, description: str) -> ArtifactInfo:
    """Build an ArtifactInfo descriptor with content populated."""
    return ArtifactInfo(
        artifact_id=str(uuid4()),
        artifact_type=ArtifactType.DOCUMENTATION.value,
        path=path,
        description=description,
        size_bytes=len(content.encode("utf-8")),
        created_by=_AGENT_NAME,
        content=content,
    )


def _write_artifacts_to_disk(base_path: Path, artifacts: list[ArtifactInfo]) -> None:
    """
    Write each artifact's content to disk.  Runs in a thread pool via
    asyncio.to_thread so it doesn't block the event loop.

    Directory structure:
        {ARTIFACT_STORAGE_PATH}/{project_id}/docs/*.md
    """
    for artifact in artifacts:
        file_path = base_path / artifact["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(artifact["content"], encoding="utf-8")


def _format_task_plan_markdown(task_plan: list[str]) -> str:
    """Format the task_plan list into a full markdown document."""
    by_category: dict[str, list[dict]] = {}
    for raw in task_plan:
        try:
            task = json.loads(raw)
            cat = task.get("category", "Uncategorised")
            by_category.setdefault(cat, []).append(task)
        except (json.JSONDecodeError, AttributeError):
            continue

    if not by_category:
        return "# Task Plan\n\nNo tasks available.\n"

    lines = ["# Task Plan\n"]
    for category in sorted(by_category):
        lines.append(f"\n## {category}\n")
        for t in by_category[category]:
            task_id = t.get("id", "")
            title = t.get("title", "")
            priority = t.get("priority", "")
            complexity = t.get("complexity", "")
            description = t.get("description", "")
            deps = t.get("dependencies") or []
            dep_str = ", ".join(str(d) for d in deps) if deps else "None"
            lines.append(f"### {task_id}: {title}")
            lines.append(f"- **Priority:** {priority}")
            lines.append(f"- **Complexity:** {complexity}")
            lines.append(f"- **Description:** {description}")
            lines.append(f"- **Dependencies:** {dep_str}\n")
    return "\n".join(lines)


def _build_project_summary(
    project_name: str,
    project_id: str,
    clarified: str,
    architecture: str,
    task_plan: list[str],
    db_schema: str,
    backend: str,
    frontend: str,
    review_notes: list[str],
    refined: str,
) -> str:
    """Assemble an executive project summary markdown document."""
    task_count = 0
    category_counts: dict[str, int] = {}
    for raw in task_plan:
        try:
            t = json.loads(raw)
            cat = t.get("category", "Uncategorised")
            category_counts[cat] = category_counts.get(cat, 0) + 1
            task_count += 1
        except (json.JSONDecodeError, AttributeError):
            pass

    task_breakdown = "\n".join(
        f"  - {cat}: {count} task(s)"
        for cat, count in sorted(category_counts.items())
    ) or "  - No tasks parsed."

    review_section_count = len(review_notes)
    artifact_list = "\n".join(f"  - `{path}`" for path in ARTIFACT_PATHS)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""\
# Project Summary: {project_name}

**Project ID:** {project_id}
**Generated:** {now}
**Pipeline:** 9-agent ForgeAI workflow (Requirements → Refiner → Artifact Packager)

---

## Overview

This document provides an executive summary of the complete ForgeAI project plan.
All detailed content is available in the individual artifact files listed below.

---

## Task Plan Overview

**Total tasks:** {task_count}

{task_breakdown}

---

## Artifacts Produced

{artifact_list}

---

## Pipeline Completion

All 9 pipeline stages completed successfully:

1. **Requirements Analyst** — clarified and structured requirements
2. **Software Architect** — designed system architecture
3. **Task Planner** — generated {task_count} implementation tasks
4. **Database Designer** — designed relational schema
5. **Backend Generator** — produced backend implementation blueprint
6. **Frontend Generator** — produced frontend implementation blueprint
7. **Reviewer** — reviewed plan across {review_section_count} categories
8. **Refiner** — applied targeted improvements from review findings
9. **Artifact Packager** — assembled {len(ARTIFACT_PATHS)} documentation artifacts

---

*This summary was generated automatically by the ForgeAI Artifact Packager.*
"""


def _failure_changes(
    state: ForgeState,
    wall_start: float,
    error_msg: str,
    log: Any,
) -> dict[str, Any]:
    """Build the state-update dict for a failed node execution."""
    duration_ms = int((time.monotonic() - wall_start) * 1000)
    now = datetime.now(timezone.utc).isoformat()

    log.error("node_failed", error=error_msg, duration_ms=duration_ms)

    agent_result: AgentResult = {
        "agent_name": _AGENT_NAME,
        "status": ExecutionStatus.FAILED.value,
        "summary": "Artifact packaging failed — see error_message for details.",
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
