"""
Integration tests for the Analytics API.

Endpoints under test
--------------------
GET /api/v1/analytics/overview
GET /api/v1/analytics/runs

Test inventory (10 tests)
--------------------------
T01  overview_empty_account         New user with no data → all zeros
T02  overview_with_data             After creating project + run → counts correct
T03  overview_unauthorized          Missing token → 401
T04  overview_isolation             User A cannot see User B's data
T05  runs_empty                     No runs → empty list, total=0
T06  runs_with_data                 Runs appear in history with correct fields
T07  runs_unauthorized              Missing token → 401
T08  runs_pagination_limit          limit=1 returns exactly 1 item
T09  runs_isolation                 User A cannot see User B's runs
T10  overview_success_rate          Correct success_rate for mixed statuses

Strategy
--------
- Real PostgreSQL test database (via conftest.py fixtures).
- Pipeline mocked via WorkflowService graph_factory injection so tests are fast.
- Auth handled via register_and_login.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_workflow_service
from app.application.services.workflow_service import WorkflowService
from app.infrastructure.repositories.artifact_repository import SQLAlchemyArtifactRepository
from app.infrastructure.repositories.project_repository import SQLAlchemyProjectRepository
from app.infrastructure.repositories.run_repository import SQLAlchemyRunRepository
from app.main import app
from tests.conftest import register_and_login

pytestmark = pytest.mark.asyncio

# ── Shared constants ──────────────────────────────────────────────────────────

_PROJECT = {
    "name": "Analytics Test Project",
    "requirements": "Build something testable.",
    "description": "Analytics integration test",
    "tech_stack": {},
}

_OVERVIEW_URL = "/api/v1/analytics/overview"
_RUNS_URL = "/api/v1/analytics/runs"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _completed_state() -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    agents = [
        "requirements_analyst", "software_architect", "task_planner",
        "database_designer", "backend_generator", "frontend_generator",
        "reviewer", "refiner", "artifact_packager",
    ]
    return {
        "execution_status": "completed",
        "completed_agents": agents,
        "agent_results": [
            {
                "agent_name": a, "status": "completed", "summary": "done",
                "tokens_used": 100, "cost_usd": 0.001, "completed_at": now,
            }
            for a in agents
        ],
        "artifacts": [],
        "errors": [],
    }


def _failed_state() -> dict:
    state = _completed_state()
    state["execution_status"] = "failed"
    state["errors"] = ["Something broke"]
    state["completed_agents"] = ["requirements_analyst"]
    return state


def _make_workflow_service(db_session: AsyncSession, final_state: dict) -> WorkflowService:
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=final_state)

    def _factory(*_a, **_kw):
        return mock_graph

    return WorkflowService(
        project_repo=SQLAlchemyProjectRepository(db_session),
        run_repo=SQLAlchemyRunRepository(db_session),
        artifact_repo=SQLAlchemyArtifactRepository(db_session),
        llm_service=MagicMock(),
        graph_factory=_factory,
    )


async def _create_project(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/projects", json=_PROJECT, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _trigger_run(
    client: AsyncClient,
    project_id: str,
    token: str,
    db: AsyncSession,
    *,
    completed: bool = True,
) -> str:
    state = _completed_state() if completed else _failed_state()
    svc = _make_workflow_service(db, state)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/run", headers=_auth(token)
        )
        assert resp.status_code == 202, resp.text
        return resp.json()["run_id"]
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)


# ── T01 — empty account ───────────────────────────────────────────────────────


async def test_overview_empty_account(client: AsyncClient) -> None:
    """Brand-new user sees all zeros."""
    token = await register_and_login(client, "analytics_t01@example.com", "Pass1234!")
    resp = await client.get(_OVERVIEW_URL, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_projects"] == 0
    assert body["total_runs"] == 0
    assert body["completed_runs"] == 0
    assert body["success_rate"] == 0.0
    assert body["total_tokens"] == 0
    assert body["estimated_total_cost"] == 0.0
    assert body["total_artifacts"] == 0


# ── T02 — overview with data ──────────────────────────────────────────────────


async def test_overview_with_data(client: AsyncClient, db: AsyncSession) -> None:
    """After a completed run the overview counts increase correctly."""
    token = await register_and_login(client, "analytics_t02@example.com", "Pass1234!")
    pid = await _create_project(client, token)
    await _trigger_run(client, pid, token, db, completed=True)

    resp = await client.get(_OVERVIEW_URL, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total_projects"] == 1
    assert body["total_runs"] == 1
    assert body["completed_runs"] == 1
    assert body["failed_runs"] == 0
    assert body["cancelled_runs"] == 0
    assert body["success_rate"] == 100.0
    # 9 agents × 100 tokens
    assert body["total_tokens"] == 900


# ── T03 — overview unauthorized ───────────────────────────────────────────────


async def test_overview_unauthorized(client: AsyncClient) -> None:
    resp = await client.get(_OVERVIEW_URL)
    assert resp.status_code == 401


# ── T04 — overview isolation ──────────────────────────────────────────────────


async def test_overview_isolation(client: AsyncClient, db: AsyncSession) -> None:
    """User A's projects do not appear in User B's overview."""
    token_a = await register_and_login(client, "analytics_t04a@example.com", "Pass1234!")
    token_b = await register_and_login(client, "analytics_t04b@example.com", "Pass1234!")

    pid = await _create_project(client, token_a)
    await _trigger_run(client, pid, token_a, db, completed=True)

    resp = await client.get(_OVERVIEW_URL, headers=_auth(token_b))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_projects"] == 0
    assert body["total_runs"] == 0


# ── T05 — runs empty ─────────────────────────────────────────────────────────


async def test_runs_empty(client: AsyncClient) -> None:
    token = await register_and_login(client, "analytics_t05@example.com", "Pass1234!")
    resp = await client.get(_RUNS_URL, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


# ── T06 — runs with data ──────────────────────────────────────────────────────


async def test_runs_with_data(client: AsyncClient, db: AsyncSession) -> None:
    """Run history contains the correct fields for a completed run."""
    token = await register_and_login(client, "analytics_t06@example.com", "Pass1234!")
    pid = await _create_project(client, token)
    run_id = await _trigger_run(client, pid, token, db, completed=True)

    resp = await client.get(_RUNS_URL, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]

    assert item["run_id"] == run_id
    assert item["project_id"] == pid
    assert item["status"] == "completed"
    assert item["tokens"] == 900
    # Duration may be 0 in fast tests but field must exist
    assert "duration_seconds" in item
    assert "cost_usd" in item


# ── T07 — runs unauthorized ───────────────────────────────────────────────────


async def test_runs_unauthorized(client: AsyncClient) -> None:
    resp = await client.get(_RUNS_URL)
    assert resp.status_code == 401


# ── T08 — runs pagination ─────────────────────────────────────────────────────


async def test_runs_pagination_limit(client: AsyncClient, db: AsyncSession) -> None:
    """limit=1 returns exactly one item even when multiple runs exist."""
    token = await register_and_login(client, "analytics_t08@example.com", "Pass1234!")
    pid = await _create_project(client, token)
    await _trigger_run(client, pid, token, db, completed=True)
    await _trigger_run(client, pid, token, db, completed=False)

    resp = await client.get(_RUNS_URL + "?limit=1", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["limit"] == 1


# ── T09 — runs isolation ──────────────────────────────────────────────────────


async def test_runs_isolation(client: AsyncClient, db: AsyncSession) -> None:
    """User B cannot see User A's runs."""
    token_a = await register_and_login(client, "analytics_t09a@example.com", "Pass1234!")
    token_b = await register_and_login(client, "analytics_t09b@example.com", "Pass1234!")

    pid = await _create_project(client, token_a)
    await _trigger_run(client, pid, token_a, db, completed=True)

    resp = await client.get(_RUNS_URL, headers=_auth(token_b))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ── T10 — success rate accuracy ───────────────────────────────────────────────


async def test_overview_success_rate(client: AsyncClient, db: AsyncSession) -> None:
    """With 1 completed and 1 failed run, success_rate = 50.0."""
    token = await register_and_login(client, "analytics_t10@example.com", "Pass1234!")
    pid = await _create_project(client, token)
    await _trigger_run(client, pid, token, db, completed=True)
    await _trigger_run(client, pid, token, db, completed=False)

    resp = await client.get(_OVERVIEW_URL, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 2
    assert body["completed_runs"] == 1
    assert body["failed_runs"] == 1
    assert body["success_rate"] == 50.0
