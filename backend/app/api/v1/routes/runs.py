"""
Workflow Execution API routes.

Endpoints
---------
POST /api/v1/projects/{project_id}/run
    Trigger a full pipeline run; returns 202 with run_id.

GET  /api/v1/runs/{run_id}
    Full run detail: metadata + graph progress + artifact list.

GET  /api/v1/runs/{run_id}/status
    Lightweight status poll.

GET  /api/v1/runs/{run_id}/artifacts
    Artifact list for the run.

GET  /api/v1/runs/{run_id}/artifacts/{artifact_id}/download
    Download a single artifact as a markdown file attachment.

GET  /api/v1/runs/{run_id}/download
    Download all artifacts as a ZIP archive (streamed in-memory).

POST /api/v1/runs/{run_id}/cancel
    Cancel a QUEUED or RUNNING run.  Owner-only.  409 if already terminal.

GET  /api/v1/runs/{run_id}/stream
    Server-Sent Events stream for live pipeline execution.
"""
from __future__ import annotations

import dataclasses
import io
import json
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import get_current_user, get_workflow_service
from app.application.services.workflow_service import WorkflowService, progress_percentage
from app.domain.entities.artifact import Artifact
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.user import User
from app.schemas.artifact import ArtifactResponse
from app.schemas.run import (
    CancelRunResponse,
    RunArtifactsResponse,
    RunCreateResponse,
    RunDetailResponse,
    RunStatusResponse,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _artifact_response(artifact: Artifact) -> ArtifactResponse:
    d = dataclasses.asdict(artifact)
    # ArtifactType enum → str
    d["artifact_type"] = artifact.artifact_type.value
    # Promote description from metadata dict to top-level response field
    d["description"] = (artifact.metadata or {}).get("description")
    return ArtifactResponse.model_validate(d)


def _run_detail_response(
    run: AgentRun,
    artifacts: list[Artifact],
) -> RunDetailResponse:
    graph = run.graph_state
    return RunDetailResponse(
        id=run.id,
        project_id=run.project_id,
        status=run.status.value,
        trigger=run.trigger,
        current_agent=graph.get("current_agent"),
        completed_agents=graph.get("completed_agents", []),
        artifacts=[_artifact_response(a) for a in artifacts],
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/run",
    response_model=RunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a full pipeline run for a project",
    tags=["runs"],
)
async def create_run(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> RunCreateResponse:
    run = await workflow_service.start_run(project_id, current_user)
    run = await workflow_service.execute_run(run.id)

    return RunCreateResponse(
        run_id=run.id,
        project_id=run.project_id,
        status=run.status.value,
        created_at=run.created_at,
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Get full run detail",
    tags=["runs"],
)
async def get_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> RunDetailResponse:
    run, artifacts = await workflow_service.get_run(run_id, current_user)
    return _run_detail_response(run, artifacts)


@router.get(
    "/runs/{run_id}/status",
    response_model=RunStatusResponse,
    summary="Lightweight status poll for a run",
    tags=["runs"],
)
async def get_run_status(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> RunStatusResponse:
    run = await workflow_service.get_run_status(run_id, current_user)
    completed = run.graph_state.get("completed_agents", [])
    return RunStatusResponse(
        run_id=run.id,
        status=run.status.value,
        current_agent=run.graph_state.get("current_agent"),
        completed_agents=completed,
        progress_percentage=progress_percentage(completed),
    )


@router.get(
    "/runs/{run_id}/artifacts",
    response_model=RunArtifactsResponse,
    summary="List artifacts for a run",
    tags=["runs"],
)
async def get_run_artifacts(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> RunArtifactsResponse:
    artifacts = await workflow_service.get_run_artifacts(run_id, current_user)
    return RunArtifactsResponse(
        run_id=run_id,
        artifacts=[_artifact_response(a) for a in artifacts],
        total=len(artifacts),
    )


@router.get(
    "/runs/{run_id}/artifacts/{artifact_id}/download",
    summary="Download a single artifact as a markdown file",
    tags=["runs"],
    responses={
        200: {
            "description": "Markdown file attachment",
            "content": {"text/markdown": {}},
        },
        404: {"description": "Run or artifact not found"},
    },
)
async def download_artifact(
    run_id: UUID,
    artifact_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Response:
    """
    Download a single artifact's markdown content as a file attachment.

    Content is served from the ``content`` column in the database; no
    filesystem access is required.  Returns 404 if the artifact does not
    exist or does not belong to the specified run.
    """
    artifact = await workflow_service.get_artifact(run_id, artifact_id, current_user)

    content = artifact.content or ""
    filename = artifact.file_path.split("/")[-1]  # e.g. "requirements.md"

    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content.encode("utf-8"))),
        },
    )


@router.get(
    "/runs/{run_id}/download",
    summary="Download all artifacts for a run as a ZIP archive",
    tags=["runs"],
    responses={
        200: {
            "description": "ZIP archive streamed in-memory",
            "content": {"application/zip": {}},
        },
        404: {"description": "Run not found"},
    },
)
async def download_run_zip(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> StreamingResponse:
    """
    Stream all artifacts for a run as a ZIP archive.

    The ZIP is assembled in-memory from DB content; it is never written to
    disk and is not cached — each request produces a fresh archive.

    Artifacts with no stored content are included as empty files so the
    archive always contains all expected paths.
    """
    artifacts = await workflow_service.get_run_artifacts(run_id, current_user)

    # Build ZIP in-memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for artifact in artifacts:
            arc_path = artifact.file_path  # e.g. "docs/requirements.md"
            content = artifact.content or ""
            zf.writestr(arc_path, content.encode("utf-8"))
    buf.seek(0)

    zip_filename = f"forgeai-run-{str(run_id)[:8]}.zip"

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
        },
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a queued or running workflow run",
    tags=["runs"],
    responses={
        409: {"description": "Run is already in a terminal state"},
        403: {"description": "Caller does not own this run"},
        404: {"description": "Run not found"},
    },
)
async def cancel_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> CancelRunResponse:
    run = await workflow_service.cancel_run(run_id, current_user)

    if run.status.value == "running":
        message = (
            "Cancellation signal sent. The pipeline will stop after the "
            "current agent completes. Poll /status to confirm."
        )
    else:
        message = "Run cancelled successfully."

    return CancelRunResponse(
        run_id=run.id,
        status=run.status.value,
        message=message,
    )


# ── SSE streaming endpoint ────────────────────────────────────────────────────


@router.get(
    "/runs/{run_id}/stream",
    summary="Stream live workflow execution events via SSE",
    response_class=StreamingResponse,
    tags=["runs"],
    responses={
        200: {
            "description": "Server-Sent Events stream",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_run_sse(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> StreamingResponse:
    """
    Open a Server-Sent Events stream for the given run.

    Event types: run_started, agent_started, agent_completed,
    progress_updated, artifact_created, run_completed, run_failed,
    run_cancelled.  The stream closes after the terminal event.
    """
    async def _generate():
        try:
            async for event in workflow_service.stream_run(run_id, current_user):
                event_type = event.get("type", "message")
                payload = json.dumps(event)
                yield f"event: {event_type}\ndata: {payload}\n\n"
        except GeneratorExit:
            return
        except Exception as exc:
            error_payload = json.dumps({
                "type": "run_failed",
                "run_id": str(run_id),
                "error": f"{type(exc).__name__}: {exc}",
            })
            yield f"event: run_failed\ndata: {error_payload}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
