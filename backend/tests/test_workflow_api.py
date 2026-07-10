"""
Integration tests for the Workflow Execution API.

Strategy
--------
- Real PostgreSQL test database (via conftest.py fixtures).
- LangGraph pipeline mocked via ``WorkflowService.graph_factory`` injection.
  ``get_workflow_service`` is overridden in each test that triggers execution.
- Tests cover: create run (happy path + error cases), get run, get status,
  get artifacts, ownership enforcement, and 401 guards.

Test inventory (13 tests)
--------------------------
T01  create_run_success                  POST /projects/{id}/run → 202, run_id
T02  create_run_unauthorized             POST without token → 401
T03  create_run_project_not_found        POST with unknown project_id → 404
T04  create_run_wrong_owner              POST on another user's project → 403
T05  create_run_pipeline_failure         Graph returns FAILED state → run persisted as FAILED
T06  get_run_success                     GET /runs/{id} → 200 with detail
T07  get_run_unauthorized                GET without token → 401
T08  get_run_not_found                   GET /runs/<unknown> → 404
T09  get_run_wrong_owner                 GET another user's run → 403
T10  get_run_status_success              GET /runs/{id}/status → 200 with progress_percentage
T11  get_run_status_completed_progress   Completed run shows 100 %
T12  get_run_artifacts_success           GET /runs/{id}/artifacts → list
T13  get_run_artifacts_wrong_owner       GET artifacts for another user's run → 403
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.dependencies import get_workflow_service
from app.application.services.workflow_service import WorkflowService
from app.infrastructure.repositories.artifact_repository import SQLAlchemyArtifactRepository
from app.infrastructure.repositories.project_repository import SQLAlchemyProjectRepository
from app.infrastructure.repositories.run_repository import SQLAlchemyRunRepository
from app.main import app
from tests.conftest import register_and_login

pytestmark = pytest.mark.asyncio

# ── Shared fixtures ───────────────────────────────────────────────────────────

PROJECT_PAYLOAD = {
    "name": "Workflow Test Project",
    "requirements": "Build a REST API with user auth and CRUD for tasks.",
    "description": "Integration test project",
    "tech_stack": {},
}


def _completed_forge_state(project_id: str) -> dict:
    """Minimal ForgeState that looks like a successfully completed pipeline run."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    artifact_id = str(uuid.uuid4())
    return {
        "project_id": project_id,
        "project_name": "Workflow Test Project",
        "raw_requirements": "Build a REST API with user auth and CRUD for tasks.",
        "clarified_requirements": "Clarified requirements text.",
        "architecture_summary": "Microservices architecture.",
        "task_plan": ["Task 1", "Task 2"],
        "database_schema": "CREATE TABLE users (...);",
        "backend_code_summary": "FastAPI backend.",
        "frontend_code_summary": "React frontend.",
        "review_notes": ["Looks good."],
        "artifacts": [
            {
                "artifact_id": artifact_id,
                "artifact_type": "documentation",
                "path": "docs/requirements.md",
                "description": "Clarified requirements",
                "size_bytes": 123,
                "created_by": "artifact_packager",
            }
        ],
        "current_agent": None,
        "completed_agents": [
            "requirements_analyst",
            "architect",
            "task_planner",
            "database_designer",
            "backend_generator",
            "frontend_generator",
            "reviewer",
            "refiner",
            "artifact_packager",
        ],
        "execution_status": "completed",
        "started_at": now,
        "updated_at": now,
        "model_used": "gpt-4o-mini",
        "total_tokens": 5000,
        "estimated_cost": 0.05,
        "conversation_history": [],
        "agent_results": [
            {
                "agent_name": "requirements_analyst",
                "status": "completed",
                "summary": "Requirements clarified.",
                "tokens_used": 500,
                "cost_usd": 0.005,
                "duration_ms": 1200,
                "completed_at": now,
                "error_message": None,
            }
        ],
        "errors": [],
        "warnings": [],
        "metadata": {"project_summary": "A REST API platform."},
    }


def _failed_forge_state(project_id: str) -> dict:
    """ForgeState that looks like a failed pipeline run."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    base = _completed_forge_state(project_id)
    base["execution_status"] = "failed"
    base["errors"] = ["LLM call failed: rate limit"]
    base["completed_agents"] = ["requirements_analyst"]
    base["artifacts"] = []
    return base


def _make_mock_graph(final_state: dict):
    """Return a mock CompiledStateGraph whose ainvoke returns final_state."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=final_state)
    return mock_graph


def _make_workflow_service(db_session, final_state: dict) -> WorkflowService:
    """Build a WorkflowService with a mocked graph factory against the test DB."""
    project_repo = SQLAlchemyProjectRepository(db_session)
    run_repo = SQLAlchemyRunRepository(db_session)
    artifact_repo = SQLAlchemyArtifactRepository(db_session)
    llm_service = MagicMock()

    def mock_graph_factory(*_args, **_kwargs):
        return _make_mock_graph(final_state)

    return WorkflowService(
        project_repo=project_repo,
        run_repo=run_repo,
        artifact_repo=artifact_repo,
        llm_service=llm_service,
        graph_factory=mock_graph_factory,
    )


# ── Helper to create a project and optionally run it ─────────────────────────


async def _create_project(client: AsyncClient, token: str) -> dict:
    resp = await client.post(
        "/api/v1/projects",
        json=PROJECT_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _trigger_run(
    client: AsyncClient,
    project_id: str,
    token: str,
    db_session,
    completed: bool = True,
) -> dict:
    """POST /projects/{id}/run with a mocked graph service."""
    project_id_str = project_id
    final_state = (
        _completed_forge_state(project_id_str)
        if completed
        else _failed_forge_state(project_id_str)
    )
    svc = _make_workflow_service(db_session, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/run",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)
    return resp


# ── T01 ───────────────────────────────────────────────────────────────────────


async def test_create_run_success(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user1@example.com", "Pass1234!")
    project = await _create_project(client, token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc

    resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "run_id" in body
    assert body["project_id"] == project_id
    assert body["status"] == "completed"


# ── T02 ───────────────────────────────────────────────────────────────────────


async def test_create_run_unauthorized(client: AsyncClient, db) -> None:
    resp = await client.post(f"/api/v1/projects/{uuid.uuid4()}/run")
    assert resp.status_code == 401


# ── T03 ───────────────────────────────────────────────────────────────────────


async def test_create_run_project_not_found(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user3@example.com", "Pass1234!")
    unknown = str(uuid.uuid4())
    final_state = _completed_forge_state(unknown)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc

    resp = await client.post(
        f"/api/v1/projects/{unknown}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 404


# ── T04 ───────────────────────────────────────────────────────────────────────


async def test_create_run_wrong_owner(client: AsyncClient, db) -> None:
    owner_token = await register_and_login(client, "owner4@example.com", "Pass1234!")
    other_token = await register_and_login(client, "other4@example.com", "Pass1234!")

    project = await _create_project(client, owner_token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc

    resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 403


# ── T05 ───────────────────────────────────────────────────────────────────────


async def test_create_run_pipeline_failure(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user5@example.com", "Pass1234!")
    project = await _create_project(client, token)
    project_id = project["id"]

    final_state = _failed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc

    resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "failed"


# ── T06 ───────────────────────────────────────────────────────────────────────


async def test_get_run_success(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user6@example.com", "Pass1234!")
    project = await _create_project(client, token)
    project_id = project["id"]

    # Create a run
    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)
    run_id = run_resp.json()["run_id"]

    # GET the run — use the same service (has access to test DB)
    svc2 = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    resp = await client.get(
        f"/api/v1/runs/{run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == run_id
    assert body["project_id"] == project_id
    assert body["status"] == "completed"
    assert "completed_agents" in body
    assert "artifacts" in body


# ── T07 ───────────────────────────────────────────────────────────────────────


async def test_get_run_unauthorized(client: AsyncClient, db) -> None:
    resp = await client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert resp.status_code == 401


# ── T08 ───────────────────────────────────────────────────────────────────────


async def test_get_run_not_found(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user8@example.com", "Pass1234!")
    unknown = str(uuid.uuid4())
    # Use a real-ish service pointing at test DB
    svc = _make_workflow_service(db, {})
    app.dependency_overrides[get_workflow_service] = lambda: svc

    resp = await client.get(
        f"/api/v1/runs/{unknown}",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 404


# ── T09 ───────────────────────────────────────────────────────────────────────


async def test_get_run_wrong_owner(client: AsyncClient, db) -> None:
    owner_token = await register_and_login(client, "owner9@example.com", "Pass1234!")
    other_token = await register_and_login(client, "other9@example.com", "Pass1234!")

    project = await _create_project(client, owner_token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)
    run_id = run_resp.json()["run_id"]

    svc2 = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    resp = await client.get(
        f"/api/v1/runs/{run_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 403


# ── T10 ───────────────────────────────────────────────────────────────────────


async def test_get_run_status_success(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user10@example.com", "Pass1234!")
    project = await _create_project(client, token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)
    run_id = run_resp.json()["run_id"]

    svc2 = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    resp = await client.get(
        f"/api/v1/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "completed"
    assert "progress_percentage" in body
    assert isinstance(body["progress_percentage"], float)
    assert 0.0 <= body["progress_percentage"] <= 100.0


# ── T11 ───────────────────────────────────────────────────────────────────────


async def test_get_run_status_completed_progress(client: AsyncClient, db) -> None:
    """A fully completed run (9 agents) shows 100% progress."""
    token = await register_and_login(client, "run_user11@example.com", "Pass1234!")
    project = await _create_project(client, token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    # Ensure all 9 agents in completed_agents
    assert len(final_state["completed_agents"]) == 9

    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)
    run_id = run_resp.json()["run_id"]

    svc2 = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    resp = await client.get(
        f"/api/v1/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 200
    assert resp.json()["progress_percentage"] == 100.0


# ── T12 ───────────────────────────────────────────────────────────────────────


async def test_get_run_artifacts_success(client: AsyncClient, db) -> None:
    token = await register_and_login(client, "run_user12@example.com", "Pass1234!")
    project = await _create_project(client, token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)
    run_id = run_resp.json()["run_id"]

    svc2 = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    resp = await client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers={"Authorization": f"Bearer {token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert "artifacts" in body
    assert isinstance(body["total"], int)
    # Completed run has 1 artifact (from mock state)
    assert body["total"] == 1
    assert body["artifacts"][0]["file_path"] == "docs/requirements.md"


# ── T13 ───────────────────────────────────────────────────────────────────────


async def test_get_run_artifacts_wrong_owner(client: AsyncClient, db) -> None:
    owner_token = await register_and_login(client, "owner13@example.com", "Pass1234!")
    other_token = await register_and_login(client, "other13@example.com", "Pass1234!")

    project = await _create_project(client, owner_token)
    project_id = project["id"]

    final_state = _completed_forge_state(project_id)
    svc = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    run_resp = await client.post(
        f"/api/v1/projects/{project_id}/run",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)
    run_id = run_resp.json()["run_id"]

    svc2 = _make_workflow_service(db, final_state)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    resp = await client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 403
