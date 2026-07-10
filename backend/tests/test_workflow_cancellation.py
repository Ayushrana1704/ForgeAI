"""
Integration tests for workflow cancellation.

Endpoints under test
--------------------
POST /api/v1/runs/{run_id}/cancel

Test inventory (7 tests)
-------------------------
T01  cancel_queued_run_success         QUEUED run → 200, status=cancelled
T02  cancel_running_run_with_stream    RUNNING + active SSE stream → 200, status=running
                                       (signal sent; stream transitions to CANCELLED)
T03  cancel_running_run_no_stream      RUNNING + no active stream → 200, status=cancelled
T04  cancel_completed_run_409          COMPLETED run → 409 ConflictException
T05  cancel_failed_run_409             FAILED run → 409 ConflictException
T06  cancel_already_cancelled_run_409  CANCELLED run → 409 ConflictException
T07  cancel_wrong_owner_403            Run owned by other user → 403 ForbiddenException

Strategy
--------
- Real PostgreSQL test database via conftest.py fixtures.
- Pipeline execution bypassed via WorkflowService subclasses:
    _QueuingService      — execute_run returns immediately (run stays QUEUED)
    _RunningService      — execute_run sets status=RUNNING and returns
- cancellation_registry is imported and manipulated directly in T02.
- Auth handled via register_and_login so 401/403 guards run real middleware.
"""
from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import MagicMock

from app.api.dependencies import get_workflow_service
from app.application.services.workflow_service import WorkflowService
from app.domain.entities.agent_run import AgentRun
from app.domain.value_objects.run_status import RunStatus
from app.domain.workflow.cancellation import cancellation_registry
from app.infrastructure.repositories.artifact_repository import SQLAlchemyArtifactRepository
from app.infrastructure.repositories.project_repository import SQLAlchemyProjectRepository
from app.infrastructure.repositories.run_repository import SQLAlchemyRunRepository
from app.main import app
from tests.conftest import register_and_login

pytestmark = pytest.mark.asyncio

# ── Shared constants ──────────────────────────────────────────────────────────

_PROJECT_PAYLOAD = {
    "name": "Cancellation Test Project",
    "requirements": "Build a service that can be cancelled mid-flight.",
    "description": "Cancellation integration test project",
    "tech_stack": {},
}

_CANCEL_URL = "/api/v1/runs/{run_id}/cancel"


# ── WorkflowService subclasses for controlled test state ─────────────────────


class _QueuingService(WorkflowService):
    """Creates the AgentRun record but skips pipeline execution.

    The run stays in QUEUED status so we can test cancellation of QUEUED runs.
    """

    async def execute_run(self, run_id: UUID) -> AgentRun:  # type: ignore[override]
        # Return without changing status — run remains QUEUED.
        return await self._run_repo.get_by_id(run_id)  # type: ignore[return-value]


class _RunningService(WorkflowService):
    """Advances the run to RUNNING without actually running the pipeline.

    Used to simulate a run that is executing (but has no active SSE stream).
    """

    async def execute_run(self, run_id: UUID) -> AgentRun:  # type: ignore[override]
        await self._run_repo.update_status(run_id, RunStatus.RUNNING)
        return await self._run_repo.get_by_id(run_id)  # type: ignore[return-value]


def _make_service(db_session: AsyncSession, cls=WorkflowService, **kw) -> WorkflowService:
    """Instantiate a (sub)class of WorkflowService wired to the test DB."""
    return cls(
        project_repo=SQLAlchemyProjectRepository(db_session),
        run_repo=SQLAlchemyRunRepository(db_session),
        artifact_repo=SQLAlchemyArtifactRepository(db_session),
        llm_service=MagicMock(),
        **kw,
    )


# ── Shared test helpers ───────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json=_PROJECT_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _trigger_run_as(
    client: AsyncClient,
    project_id: str,
    token: str,
    db_session: AsyncSession,
    *,
    svc_cls=_QueuingService,
    graph_factory=None,
) -> str:
    """POST /projects/{id}/run with a controlled service, return the run_id."""
    kw = {"graph_factory": graph_factory} if graph_factory else {}
    svc = _make_service(db_session, svc_cls, **kw)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202, resp.text
        return resp.json()["run_id"]
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── T01 — cancel QUEUED run ───────────────────────────────────────────────────


async def test_cancel_queued_run_success(client: AsyncClient, db: AsyncSession) -> None:
    """A QUEUED run is cancelled immediately; response status is 'cancelled'."""
    token = await register_and_login(client, "cancel_t01@example.com", "Pass1234!")
    project_id = await _create_project(client, token)

    # Start run but skip execution — stays QUEUED
    run_id = await _trigger_run_as(client, project_id, token, db, svc_cls=_QueuingService)

    svc = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "cancelled"


# ── T02 — cancel RUNNING run with an active SSE stream ───────────────────────


async def test_cancel_running_run_with_stream(
    client: AsyncClient, db: AsyncSession
) -> None:
    """
    When a run is RUNNING and an SSE stream is registered in the
    CancellationRegistry, cancel sets the event flag but does NOT update the
    DB immediately.  The response status is 'running'.
    """
    token = await register_and_login(client, "cancel_t02@example.com", "Pass1234!")
    project_id = await _create_project(client, token)

    # Advance run to RUNNING (no actual pipeline)
    run_id = await _trigger_run_as(client, project_id, token, db, svc_cls=_RunningService)

    # Simulate an active SSE stream by registering the run in the registry
    run_uuid = UUID(run_id)
    cancel_event = cancellation_registry.register(run_uuid)

    svc = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)
        # Clean up registry entry (stream_run's finally block would normally do this)
        cancellation_registry.unregister(run_uuid)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    # DB not updated yet — status is still 'running'; stream will transition it
    assert body["status"] == "running"
    # Cancellation event must have been set
    assert cancel_event.is_set()


# ── T03 — cancel RUNNING run without an active SSE stream ────────────────────


async def test_cancel_running_run_no_stream(
    client: AsyncClient, db: AsyncSession
) -> None:
    """
    A RUNNING run with no active SSE stream is cancelled immediately at the DB
    level because there is nothing to signal.
    """
    token = await register_and_login(client, "cancel_t03@example.com", "Pass1234!")
    project_id = await _create_project(client, token)

    run_id = await _trigger_run_as(client, project_id, token, db, svc_cls=_RunningService)

    # No registry entry — simulates execute_run path (no SSE stream open)
    svc = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "cancelled"


# ── T04 — cancel COMPLETED run → 409 ─────────────────────────────────────────


async def test_cancel_completed_run_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Cancelling a COMPLETED run raises 409 ConflictException."""
    from unittest.mock import AsyncMock

    token = await register_and_login(client, "cancel_t04@example.com", "Pass1234!")
    project_id = await _create_project(client, token)

    # Run the pipeline to COMPLETED using a mock graph
    from tests.test_workflow_api import _completed_forge_state, _make_workflow_service

    svc = _make_workflow_service(db, _completed_forge_state(project_id))
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/run",
            headers=_auth(token),
        )
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    svc2 = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    try:
        resp = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 409, resp.text


# ── T05 — cancel FAILED run → 409 ────────────────────────────────────────────


async def test_cancel_failed_run_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Cancelling a FAILED run raises 409 ConflictException."""
    token = await register_and_login(client, "cancel_t05@example.com", "Pass1234!")
    project_id = await _create_project(client, token)

    from tests.test_workflow_api import _failed_forge_state, _make_workflow_service

    svc = _make_workflow_service(db, _failed_forge_state(project_id))
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/run",
            headers=_auth(token),
        )
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    svc2 = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc2
    try:
        resp = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 409, resp.text


# ── T06 — cancel already-CANCELLED run → 409 ─────────────────────────────────


async def test_cancel_already_cancelled_run_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A second cancel request on an already-CANCELLED run raises 409."""
    token = await register_and_login(client, "cancel_t06@example.com", "Pass1234!")
    project_id = await _create_project(client, token)

    run_id = await _trigger_run_as(client, project_id, token, db, svc_cls=_QueuingService)

    svc = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc

    try:
        # First cancel — should succeed
        resp1 = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
        assert resp1.status_code == 200, resp1.text

        # Second cancel — should be 409
        resp2 = await client.post(_CANCEL_URL.format(run_id=run_id), headers=_auth(token))
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    assert resp2.status_code == 409, resp2.text


# ── T07 — cancel another user's run → 403 ────────────────────────────────────


async def test_cancel_wrong_owner_returns_403(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Cancelling a run that belongs to another user raises 403."""
    token_owner = await register_and_login(client, "cancel_t07a@example.com", "Pass1234!")
    token_other = await register_and_login(client, "cancel_t07b@example.com", "Pass1234!")

    project_id = await _create_project(client, token_owner)
    run_id = await _trigger_run_as(
        client, project_id, token_owner, db, svc_cls=_QueuingService
    )

    svc = _make_service(db)
    app.dependency_overrides[get_workflow_service] = lambda: svc
    try:
        resp = await client.post(
            _CANCEL_URL.format(run_id=run_id),
            headers=_auth(token_other),  # wrong user
        )
    finally:
        app.dependency_overrides.pop(get_workflow_service, None)

    assert resp.status_code == 403, resp.text
