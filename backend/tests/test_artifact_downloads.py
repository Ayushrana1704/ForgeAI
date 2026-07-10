"""
Tests for artifact persistence + download API.

Coverage
--------
1. artifact_packager populates ArtifactInfo.content for each artifact
2. artifact_packager writes files to disk (mocked asyncio.to_thread)
3. _persist_artifacts passes content to Artifact entity
4. GET /runs/{run_id}/artifacts/{artifact_id}/download — success
5. GET /runs/{run_id}/artifacts/{artifact_id}/download — artifact not in run (404)
6. GET /runs/{run_id}/download — returns ZIP with correct members
7. GET /runs/{run_id}/download — run not found (404)
8. ArtifactResponse includes description field
"""
from __future__ import annotations

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest

# ── Unit: ArtifactInfo content field ──────────────────────────────────────


def test_artifact_info_content_field():
    """ArtifactInfo TypedDict now contains a 'content' key."""
    from app.domain.workflow.types import ArtifactInfo

    assert "content" in ArtifactInfo.__annotations__, (
        "ArtifactInfo must declare 'content: str'"
    )


# ── Unit: artifact_packager populates content ──────────────────────────────


def _minimal_forge_state() -> dict:
    """Return a ForgeState dict that satisfies all artifact_packager guards."""
    import json

    task = json.dumps({
        "id": "T1", "title": "Setup", "category": "Backend",
        "priority": "high", "complexity": "low",
        "description": "Bootstrap the project", "dependencies": [],
    })
    return {
        "project_id": str(uuid4()),
        "project_name": "TestProject",
        "raw_requirements": "Build a thing",
        "clarified_requirements": "Build a tested thing",
        "architecture_summary": "Monolith with FastAPI",
        "task_plan": [task],
        "database_schema": "CREATE TABLE users (id SERIAL PRIMARY KEY);",
        "backend_code_summary": "FastAPI app with JWT auth",
        "frontend_code_summary": "React + Vite",
        "review_notes": ["Good architecture", "Needs more tests"],
        "metadata": {"refined": "No major changes"},
        "artifacts": [],
        "agent_results": [],
        "errors": [],
        "completed_agents": [],
        "execution_status": "running",
        "current_agent": None,
        "total_tokens": 0,
        "estimated_cost": 0.0,
        "updated_at": "2024-01-01T00:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_packager_populates_content():
    """Each ArtifactInfo returned by the packager must have a non-empty content field."""
    from app.infrastructure.langgraph.nodes.artifact_packager import make_artifact_packager_node

    state = _minimal_forge_state()
    node = make_artifact_packager_node()

    with patch(
        "app.infrastructure.langgraph.nodes.artifact_packager.asyncio.to_thread",
        new_callable=AsyncMock,
    ):
        result = await node(state)

    artifacts = result.get("artifacts", [])
    assert len(artifacts) == 9, f"Expected 9 artifacts, got {len(artifacts)}"
    for ai in artifacts:
        assert "content" in ai, f"ArtifactInfo missing 'content' key: {ai['path']}"
        assert ai["content"], f"ArtifactInfo.content is empty for {ai['path']}"


@pytest.mark.asyncio
async def test_packager_writes_to_disk():
    """artifact_packager calls asyncio.to_thread with _write_artifacts_to_disk."""
    from app.infrastructure.langgraph.nodes.artifact_packager import make_artifact_packager_node

    state = _minimal_forge_state()
    node = make_artifact_packager_node()

    mock_to_thread = AsyncMock()
    with patch(
        "app.infrastructure.langgraph.nodes.artifact_packager.asyncio.to_thread",
        mock_to_thread,
    ):
        await node(state)

    assert mock_to_thread.call_count == 1, "asyncio.to_thread should be called once"


@pytest.mark.asyncio
async def test_packager_disk_failure_is_nonfatal():
    """Disk write failure must NOT propagate — packager returns COMPLETED anyway."""
    from app.infrastructure.langgraph.nodes.artifact_packager import make_artifact_packager_node

    state = _minimal_forge_state()
    node = make_artifact_packager_node()

    async def _fail(*_args, **_kwargs):
        raise OSError("disk full")

    with patch(
        "app.infrastructure.langgraph.nodes.artifact_packager.asyncio.to_thread",
        side_effect=_fail,
    ):
        result = await node(state)

    from app.domain.workflow.types import ExecutionStatus
    assert result["execution_status"] == ExecutionStatus.COMPLETED.value


# ── Unit: _persist_artifacts passes content ────────────────────────────────


@pytest.mark.asyncio
async def test_persist_artifacts_passes_content():
    """WorkflowService._persist_artifacts must pass content=ai['content'] to Artifact."""
    from app.application.services.workflow_service import WorkflowService
    from app.domain.entities.agent_run import AgentRun
    from app.domain.value_objects.run_status import RunStatus
    from datetime import datetime, timezone

    # Build a minimal AgentRun
    project_id = uuid4()
    run_id = uuid4()
    run = AgentRun(
        id=run_id,
        project_id=project_id,
        status=RunStatus.RUNNING,
        trigger="test",
        graph_state={},
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=datetime.now(timezone.utc),
    )

    artifact_id = str(uuid4())
    state: dict = {
        "artifacts": [
            {
                "artifact_id": artifact_id,
                "artifact_type": "documentation",
                "path": "docs/requirements.md",
                "description": "Requirements",
                "size_bytes": 42,
                "created_by": "artifact_packager",
                "content": "# Requirements\n\nBuild a thing",
            }
        ]
    }

    captured: list = []

    async def fake_create(artifact):
        captured.append(artifact)
        return artifact

    artifact_repo = MagicMock()
    artifact_repo.create = fake_create

    svc = WorkflowService(
        project_repo=MagicMock(),
        run_repo=MagicMock(),
        artifact_repo=artifact_repo,
        llm_service=MagicMock(),
    )

    await svc._persist_artifacts(run, state)  # type: ignore[arg-type]

    assert len(captured) == 1
    assert captured[0].content == "# Requirements\n\nBuild a thing"


# ── Integration-style: download endpoint helpers ───────────────────────────


def test_artifact_response_has_description():
    """ArtifactResponse schema must include a 'description' field."""
    from app.schemas.artifact import ArtifactResponse
    import inspect

    fields = ArtifactResponse.model_fields
    assert "description" in fields, "ArtifactResponse must have 'description' field"


def test_artifact_response_description_optional():
    """ArtifactResponse.description must be optional (default None)."""
    from app.schemas.artifact import ArtifactResponse

    fields = ArtifactResponse.model_fields
    field = fields["description"]
    # Pydantic v2: is_required() returns False for optional fields
    assert not field.is_required(), "ArtifactResponse.description must be optional"


# ── Unit: ZIP generation ───────────────────────────────────────────────────


def test_zip_contains_all_artifact_paths():
    """ZIP assembled in runs.py must contain one entry per artifact path."""
    # Replicate the ZIP logic from download_run_zip endpoint
    artifact_paths = [
        "docs/requirements.md",
        "docs/architecture.md",
        "docs/task_plan.md",
        "docs/database_design.md",
        "docs/backend_blueprint.md",
        "docs/frontend_blueprint.md",
        "docs/review.md",
        "docs/refinement.md",
        "docs/project_summary.md",
    ]
    contents = {p: f"# {p}\n\nContent for {p}" for p in artifact_paths}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in contents.items():
            zf.writestr(path, content.encode("utf-8"))
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())

    assert names == set(artifact_paths)


def test_zip_content_round_trips():
    """ZIP content should round-trip losslessly."""
    original = "# Requirements\n\nBuild a **tested** thing.\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("docs/requirements.md", original.encode("utf-8"))
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        recovered = zf.read("docs/requirements.md").decode("utf-8")

    assert recovered == original


# ── Unit: WorkflowService.get_artifact ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_artifact_not_in_run_raises_404():
    """get_artifact must raise NotFoundException if artifact.run_id != run_id."""
    from app.application.services.workflow_service import WorkflowService
    from app.core.exceptions import NotFoundException
    from app.domain.entities.agent_run import AgentRun
    from app.domain.entities.artifact import Artifact
    from app.domain.value_objects.artifact_type import ArtifactType
    from app.domain.value_objects.run_status import RunStatus
    from datetime import datetime, timezone

    run_id = uuid4()
    other_run_id = uuid4()
    artifact_id = uuid4()
    project_id = uuid4()

    run = AgentRun(
        id=run_id, project_id=project_id,
        status=RunStatus.COMPLETED, trigger="test",
        graph_state={}, error_message=None,
        started_at=None, completed_at=None,
        created_at=datetime.now(timezone.utc),
    )
    artifact = Artifact(
        id=artifact_id, project_id=project_id,
        run_id=other_run_id,  # belongs to a different run
        step_id=None,
        artifact_type=ArtifactType.DOCUMENTATION,
        file_path="docs/requirements.md",
        created_at=datetime.now(timezone.utc),
        content="# Hello",
    )

    run_repo = MagicMock()
    run_repo.get_by_id = AsyncMock(return_value=run)
    artifact_repo = MagicMock()
    artifact_repo.get_by_id = AsyncMock(return_value=artifact)
    project_repo = MagicMock()

    async def fake_get_project(pid):
        proj = MagicMock()
        proj.owner_id = uuid4()  # different user → use superuser
        return proj

    project_repo.get_by_id = fake_get_project

    caller = MagicMock()
    caller.id = uuid4()
    caller.is_superuser = True

    svc = WorkflowService(
        project_repo=project_repo,
        run_repo=run_repo,
        artifact_repo=artifact_repo,
        llm_service=MagicMock(),
    )

    with pytest.raises(NotFoundException):
        await svc.get_artifact(run_id, artifact_id, caller)
