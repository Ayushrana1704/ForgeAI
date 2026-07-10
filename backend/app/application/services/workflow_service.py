"""
WorkflowService — orchestrates a full ForgeAI pipeline run.

Responsibilities
----------------
1. Verify the caller owns the target project.
2. Create an ``AgentRun`` record (status = QUEUED).
3. Initialise a ``ForgeState`` from project fields.
4. Execute the LangGraph pipeline (currently synchronous; designed so that step
   4 can be moved to a background worker without changing callers).
5. Persist ``AgentStep`` records from ``ForgeState.agent_results``.
6. Persist ``Artifact`` records from ``ForgeState.artifacts``.
7. Flush the final ``graph_state`` and terminal ``RunStatus`` to the DB.

Background-execution readiness
-------------------------------
``start_run`` and ``execute_run`` are intentionally separate so a future
caller can do::

    run = await svc.start_run(project_id, user)
    await worker_queue.enqueue("execute_run", run.id)   # non-blocking
    return RunCreateResponse(run_id=run.id, ...)

For now the route calls both in sequence (synchronous, but 202 is still
returned so the client contract is stable).

Testability
-----------
``graph_factory`` is injectable (defaults to ``build_forge_graph``).
Integration tests override it with an ``AsyncMock`` that returns a
pre-built ``ForgeState`` without calling any LLM.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable
from uuid import UUID, uuid4

import structlog

from app.application.interfaces.artifact_repository import ArtifactRepository
from app.application.interfaces.project_repository import ProjectRepository
from app.application.interfaces.run_repository import RunRepository
from app.application.services.llm.llm_service import LLMService
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.agent_step import AgentStep
from app.domain.entities.artifact import Artifact
from app.domain.entities.user import User
from app.domain.value_objects.agent_type import AgentType
from app.domain.value_objects.artifact_type import ArtifactType
from app.domain.value_objects.run_status import RunStatus
from app.domain.workflow.cancellation import cancellation_registry
from app.domain.workflow.events import WorkflowEvent, make_event
from app.domain.workflow.forge_state import ForgeState, create_forge_state
from app.infrastructure.langgraph.graph import build_forge_graph

logger = structlog.get_logger(__name__)

_TOTAL_PIPELINE_AGENTS = 9

# Exact node names registered in build_forge_graph().
_PIPELINE_NODES: frozenset[str] = frozenset({
    "requirements_analyst",
    "software_architect",
    "task_planner",
    "database_designer",
    "backend_generator",
    "frontend_generator",
    "reviewer",
    "refiner",
    "artifact_packager",
})

_LANGGRAPH_ROOT_NAME = "LangGraph"   # CompiledStateGraph.name default


class WorkflowService:
    def __init__(
        self,
        project_repo: ProjectRepository,
        run_repo: RunRepository,
        artifact_repo: ArtifactRepository,
        llm_service: LLMService,
        graph_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._run_repo = run_repo
        self._artifact_repo = artifact_repo
        self._llm_service = llm_service
        # Allows tests to inject a mock graph without touching production code.
        self._graph_factory: Callable[..., Any] = graph_factory or build_forge_graph

    # ── Public API ────────────────────────────────────────────────────────────

    async def start_run(
        self,
        project_id: UUID,
        caller: User,
        trigger: str = "manual",
    ) -> AgentRun:
        """
        Verify ownership, create an AgentRun record, and return it immediately.

        The run starts in QUEUED status.  The caller is expected to follow up
        with ``execute_run(run.id)`` — either inline or via a background worker.
        """
        project = await self._project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")
        if project.owner_id != caller.id and not caller.is_superuser:
            raise ForbiddenException("You do not have access to this project")

        initial_state: ForgeState = create_forge_state(
            project_id=project_id,
            project_name=project.name,
            raw_requirements=project.requirements,
        )

        run = AgentRun(
            id=uuid4(),
            project_id=project_id,
            status=RunStatus.QUEUED,
            trigger=trigger,
            graph_state=dict(initial_state),
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=datetime.now(timezone.utc),
        )
        created = await self._run_repo.create(run)
        logger.info(
            "run_queued",
            run_id=str(created.id),
            project_id=str(project_id),
            trigger=trigger,
        )
        return created

    async def execute_run(self, run_id: UUID) -> AgentRun:
        """
        Execute the LangGraph pipeline for an existing run (QUEUED → RUNNING →
        COMPLETED | FAILED).

        Persist agent steps and assembled artifacts on completion.
        """
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")

        await self._run_repo.update_status(run_id, RunStatus.RUNNING)
        logger.info("run_started", run_id=str(run_id), project_id=str(run.project_id))

        initial_state: ForgeState = run.graph_state  # type: ignore[assignment]

        try:
            graph = self._graph_factory(self._llm_service)
            config = {"configurable": {"thread_id": str(run_id)}}
            final_state: ForgeState = await graph.ainvoke(initial_state, config=config)

            # Determine terminal status from workflow outcome
            execution_status = final_state.get("execution_status", "failed")
            run_status = (
                RunStatus.COMPLETED
                if execution_status == "completed"
                else RunStatus.FAILED
            )
            errors: list[str] = final_state.get("errors", [])
            error_message = (
                "; ".join(errors) if errors and run_status == RunStatus.FAILED else None
            )

            # Persist results
            await self._run_repo.save_graph_state(run_id, dict(final_state))
            await self._persist_steps(run, final_state)
            await self._persist_artifacts(run, final_state)
            await self._run_repo.update_status(run_id, run_status, error_message)

            logger.info(
                "run_finished",
                run_id=str(run_id),
                status=run_status.value,
                agents_completed=len(final_state.get("completed_agents", [])),
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            await self._run_repo.update_status(run_id, RunStatus.FAILED, error_msg)
            logger.exception("run_failed", run_id=str(run_id), error=error_msg)
            raise

        return await self._run_repo.get_by_id(run_id)  # type: ignore[return-value]

    async def get_run(
        self,
        run_id: UUID,
        caller: User,
    ) -> tuple[AgentRun, list[Artifact]]:
        """Return the run entity and its artifacts after verifying access."""
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")
        await self._verify_run_access(run, caller)
        artifacts = await self._artifact_repo.list_by_project(
            run.project_id, run_id=run_id
        )
        return run, artifacts

    async def get_run_status(self, run_id: UUID, caller: User) -> AgentRun:
        """Return the run entity (lightweight status poll)."""
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")
        await self._verify_run_access(run, caller)
        return run

    async def get_run_artifacts(
        self, run_id: UUID, caller: User
    ) -> list[Artifact]:
        """Return the artifact list for the given run."""
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")
        await self._verify_run_access(run, caller)
        return await self._artifact_repo.list_by_project(
            run.project_id, run_id=run_id
        )

    async def get_artifact(
        self,
        run_id: UUID,
        artifact_id: UUID,
        caller: User,
    ) -> Artifact:
        """
        Return a single artifact (including content) after verifying access.

        Raises NotFoundException if the run or artifact does not exist, or if
        the artifact does not belong to the specified run.
        """
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")
        await self._verify_run_access(run, caller)

        artifact = await self._artifact_repo.get_by_id(artifact_id)
        if not artifact or artifact.run_id != run_id:
            raise NotFoundException(f"Artifact {artifact_id} not found in run {run_id}")
        return artifact

    async def stream_run(
        self,
        run_id: UUID,
        caller: User,
    ) -> AsyncGenerator[WorkflowEvent, None]:
        """
        Execute (or replay) the pipeline for ``run_id`` and yield
        ``WorkflowEvent`` dicts as each agent completes.

        Execution paths
        ---------------
        QUEUED / RUNNING
            Execute the pipeline via ``graph.astream_events()``.  Yields live
            events as each node fires.  Persists steps, artifacts, and final
            graph_state when the graph completes — identical side-effects to
            ``execute_run()``.

        COMPLETED
            Yield a synthetic replay from the stored ``graph_state``
            (agent names, artifacts, completion).  No DB writes.

        FAILED
            Yield a single ``run_failed`` event with the stored error message.

        CANCELLED
            Yield a single ``run_cancelled`` event with the partial progress.

        Cancellation (QUEUED / RUNNING path)
        ------------------------------------
        Before entering the ``astream_events`` loop, the run is registered with
        ``CancellationRegistry``.  After each agent's ``on_chain_end`` event the
        generator checks whether cancellation was requested.  If so it persists
        whatever partial state has accumulated, updates the run status to
        CANCELLED, yields ``run_cancelled``, and returns.  The registry entry is
        cleaned up in a ``finally`` block regardless of how the generator exits.
        """
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")
        await self._verify_run_access(run, caller)

        run_id_str = str(run_id)

        # ── Already-terminal runs: replay from stored graph_state ────────────
        if run.status == RunStatus.FAILED:
            errors: list[str] = run.graph_state.get("errors", [])
            err_msg = "; ".join(errors) if errors else (run.error_message or "Run failed")
            yield make_event("run_failed", run_id_str, error=err_msg)
            return

        if run.status == RunStatus.CANCELLED:
            completed: list[str] = run.graph_state.get("completed_agents", [])
            prog = progress_percentage(completed)
            yield make_event("run_cancelled", run_id_str, progress=prog)
            return

        if run.status == RunStatus.COMPLETED:
            completed_agents: list[str] = run.graph_state.get("completed_agents", [])
            yield make_event("run_started", run_id_str)
            for i, agent_name in enumerate(completed_agents):
                prog = round((i + 1) / _TOTAL_PIPELINE_AGENTS * 100, 1)
                yield make_event("agent_started", run_id_str, agent=agent_name)
                yield make_event("agent_completed", run_id_str, agent=agent_name, progress=prog)
                yield make_event("progress_updated", run_id_str, progress=prog)
            for ai in run.graph_state.get("artifacts", []):
                yield make_event(
                    "artifact_created",
                    run_id_str,
                    artifact_path=ai.get("path"),
                    artifact_type=ai.get("artifact_type"),
                )
            yield make_event("run_completed", run_id_str, progress=100.0)
            return

        # ── QUEUED / RUNNING: live execution via astream_events ──────────────
        initial_state = run.graph_state  # full ForgeState stored at start_run time

        yield make_event("run_started", run_id_str)
        await self._run_repo.update_status(run_id, RunStatus.RUNNING)

        final_state: dict | None = None
        completed_count = 0
        # Tracks accumulating state as each node's output is merged in.
        # Used to persist partial results when cancellation is requested.
        partial_state: dict = dict(initial_state)

        # Register this run so cancel_run() can signal it.
        _cancel_ev = cancellation_registry.register(run_id)

        try:
            graph = self._graph_factory(self._llm_service)
            config = {"configurable": {"thread_id": run_id_str}}

            async for lg_event in graph.astream_events(
                initial_state,
                config=config,
                version="v2",
            ):
                name: str = lg_event.get("name", "")
                kind: str = lg_event.get("event", "")
                data: dict = lg_event.get("data", {}) or {}

                if name in _PIPELINE_NODES:
                    if kind == "on_chain_start":
                        yield make_event("agent_started", run_id_str, agent=name)

                    elif kind == "on_chain_end":
                        completed_count += 1
                        prog = round(completed_count / _TOTAL_PIPELINE_AGENTS * 100, 1)
                        yield make_event("agent_completed", run_id_str, agent=name, progress=prog)
                        yield make_event("progress_updated", run_id_str, progress=prog)

                        output = data.get("output") or {}

                        # Merge this node's output into partial_state so we always
                        # have an up-to-date snapshot for graceful cancellation.
                        partial_state.update(output)

                        # Emit artifact_created for each ArtifactInfo in the changeset.
                        for ai in output.get("artifacts", []):
                            yield make_event(
                                "artifact_created",
                                run_id_str,
                                artifact_path=ai.get("path"),
                                artifact_type=ai.get("artifact_type"),
                            )

                        # ── Cancellation check ────────────────────────────────
                        if _cancel_ev.is_set():
                            logger.info(
                                "run_cancellation_detected",
                                run_id=run_id_str,
                                agents_completed=completed_count,
                            )
                            await self._run_repo.save_graph_state(run_id, partial_state)
                            await self._persist_steps(run, partial_state)  # type: ignore[arg-type]
                            await self._persist_artifacts(run, partial_state)  # type: ignore[arg-type]
                            await self._run_repo.update_status(
                                run_id, RunStatus.CANCELLED, "Cancelled by user"
                            )
                            yield make_event("run_cancelled", run_id_str, progress=prog)
                            return

                elif name == _LANGGRAPH_ROOT_NAME and kind == "on_chain_end":
                    # Final complete state returned by the graph
                    final_state = data.get("output") or {}

            # ── Persist results ───────────────────────────────────────────────
            if final_state:
                execution_status = final_state.get("execution_status", "failed")
                run_status = (
                    RunStatus.COMPLETED
                    if execution_status == "completed"
                    else RunStatus.FAILED
                )
                errors_list: list[str] = final_state.get("errors", [])
                error_message = (
                    "; ".join(errors_list)
                    if errors_list and run_status == RunStatus.FAILED
                    else None
                )

                await self._run_repo.save_graph_state(run_id, dict(final_state))
                await self._persist_steps(run, final_state)  # type: ignore[arg-type]
                await self._persist_artifacts(run, final_state)  # type: ignore[arg-type]
                await self._run_repo.update_status(run_id, run_status, error_message)

                if run_status == RunStatus.COMPLETED:
                    yield make_event("run_completed", run_id_str, progress=100.0)
                else:
                    yield make_event(
                        "run_failed",
                        run_id_str,
                        error=error_message or "Pipeline returned a failed execution status",
                    )
            else:
                error_message = "Pipeline produced no final state"
                await self._run_repo.update_status(run_id, RunStatus.FAILED, error_message)
                yield make_event("run_failed", run_id_str, error=error_message)

        except GeneratorExit:
            # Client disconnected — clean up quietly; no more yields allowed.
            try:
                await self._run_repo.update_status(
                    run_id, RunStatus.FAILED, "Client disconnected"
                )
            except Exception:
                pass

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            try:
                await self._run_repo.update_status(run_id, RunStatus.FAILED, error_msg)
            except Exception:
                pass
            yield make_event("run_failed", run_id_str, error=error_msg)
            logger.exception("stream_run_failed", run_id=run_id_str, error=error_msg)

        finally:
            # Always clean up the cancellation registry entry, whether the run
            # completed, failed, was cancelled, or the client disconnected.
            cancellation_registry.unregister(run_id)

    async def cancel_run(
        self,
        run_id: UUID,
        caller: User,
    ) -> AgentRun:
        """
        Cancel a QUEUED or RUNNING run.

        Behaviour by status
        -------------------
        QUEUED
            No execution has started.  Update the DB record to CANCELLED immediately.

        RUNNING (with active SSE stream)
            Signal the stream_run async generator via the CancellationRegistry.
            The generator will detect the signal after the current agent completes,
            persist partial state, and yield a ``run_cancelled`` event.

        RUNNING (no active stream — e.g. synchronous execute_run in progress)
            Update the DB record directly.  The existing synchronous ainvoke will
            finish, but the record is already marked CANCELLED so the caller knows.
            When background workers are added, this path will enqueue a cancel task.

        COMPLETED | FAILED | CANCELLED
            Raise ConflictException (409).

        Returns
        -------
        The refreshed AgentRun entity reflecting the new status.
        """
        run = await self._run_repo.get_by_id(run_id)
        if not run:
            raise NotFoundException(f"Run {run_id} not found")
        await self._verify_run_access(run, caller)

        _TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
        if run.status in _TERMINAL:
            raise ConflictException(
                f"Run cannot be cancelled: already {run.status.value}"
            )

        # Signal any active SSE stream to stop gracefully after its current agent.
        has_active_stream = cancellation_registry.request(run_id)

        if not has_active_stream or run.status == RunStatus.QUEUED:
            # No live stream to notify, or run hasn't started executing — update DB now.
            await self._run_repo.update_status(
                run_id, RunStatus.CANCELLED, "Cancelled by user"
            )

        logger.info(
            "run_cancel_requested",
            run_id=str(run_id),
            status=run.status.value,
            has_active_stream=has_active_stream,
        )

        return await self._run_repo.get_by_id(run_id)  # type: ignore[return-value]

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _verify_run_access(self, run: AgentRun, caller: User) -> None:
        project = await self._project_repo.get_by_id(run.project_id)
        if not project:
            raise NotFoundException(f"Project {run.project_id} not found")
        if project.owner_id != caller.id and not caller.is_superuser:
            raise ForbiddenException("You do not have access to this run")

    async def _persist_steps(self, run: AgentRun, state: ForgeState) -> None:
        for i, result in enumerate(state.get("agent_results", [])):
            try:
                agent_type = AgentType(result["agent_name"])
            except ValueError:
                logger.warning(
                    "unknown_agent_type",
                    agent_name=result.get("agent_name"),
                    run_id=str(run.id),
                )
                continue

            completed_at: datetime | None = None
            raw_ts = result.get("completed_at")
            if raw_ts:
                try:
                    completed_at = datetime.fromisoformat(raw_ts)
                except (ValueError, TypeError):
                    pass

            step = AgentStep(
                id=uuid4(),
                run_id=run.id,
                agent_type=agent_type,
                sequence=i,
                status=result.get("status", "completed"),
                input={},
                output={"summary": result.get("summary", "")},
                tokens_used=int(result.get("tokens_used", 0)),
                cost_usd=float(result.get("cost_usd", 0.0)),
                duration_ms=result.get("duration_ms"),
                error_message=result.get("error_message"),
                started_at=None,
                completed_at=completed_at,
            )
            await self._run_repo.upsert_step(step)

    async def _persist_artifacts(self, run: AgentRun, state: ForgeState) -> None:
        now = datetime.now(timezone.utc)
        for ai in state.get("artifacts", []):
            try:
                artifact_type = ArtifactType(ai["artifact_type"])
            except ValueError:
                artifact_type = ArtifactType.DOCUMENTATION

            artifact = Artifact(
                id=UUID(ai["artifact_id"]),
                project_id=run.project_id,
                run_id=run.id,
                step_id=None,
                artifact_type=artifact_type,
                file_path=ai["path"],
                language=None,
                size_bytes=int(ai.get("size_bytes", 0)),
                checksum=None,
                storage_key=None,
                content=ai.get("content"),
                metadata={
                    "description": ai.get("description", ""),
                    "created_by": ai.get("created_by", ""),
                },
                created_at=now,
            )
            await self._artifact_repo.create(artifact)


def progress_percentage(completed_agents: list[str]) -> float:
    """Return 0.0–100.0 progress based on completed agent count."""
    return round(len(completed_agents) / _TOTAL_PIPELINE_AGENTS * 100, 1)
