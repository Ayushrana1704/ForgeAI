import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

_PASSWORD = "Secure1pass"

_VALID_PROJECT = {
    "name": "My Test Project",
    "description": "A test project",
    "requirements": "Build a REST API with authentication and CRUD operations for a blog.",
    "tech_stack": {"language": "Python", "framework": "FastAPI"},
}


async def _auth_headers(client: AsyncClient) -> dict:
    email = f"proj_{uuid.uuid4().hex[:8]}@test.com"
    token = await register_and_login(client, email, _PASSWORD)
    return {"Authorization": f"Bearer {token}"}


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == _VALID_PROJECT["name"]
    assert body["status"] == "draft"          # DRAFT is the initial status
    assert "id" in body
    assert "owner_id" in body


@pytest.mark.asyncio
async def test_create_project_requires_auth(client: AsyncClient) -> None:
    # Missing Authorization header must return 401 (RFC 7235), not 403.
    resp = await client.post("/api/v1/projects", json=_VALID_PROJECT)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_project_short_requirements_returns_422(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    bad = {**_VALID_PROJECT, "requirements": "too short"}
    resp = await client.post("/api/v1/projects", json=bad, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_project_blank_name_returns_422(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    bad = {**_VALID_PROJECT, "name": "   "}   # whitespace-only name
    resp = await client.post("/api/v1/projects", json=bad, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_project_empty_name_returns_422(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    bad = {**_VALID_PROJECT, "name": ""}
    resp = await client.post("/api/v1/projects", json=bad, headers=headers)
    assert resp.status_code == 422


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_projects(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)

    resp = await client.get("/api/v1/projects", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_list_projects_isolated_between_users(client: AsyncClient) -> None:
    user_a_headers = await _auth_headers(client)
    user_b_headers = await _auth_headers(client)

    await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=user_a_headers)

    resp = await client.get("/api/v1/projects", headers=user_b_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_projects_filter_by_status(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)

    # Filter by the initial status — should match the newly created project.
    resp = await client.get("/api/v1/projects?status=draft", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(p["status"] == "draft" for p in body["items"])

    # Filter by a status that has no projects yet.
    resp_none = await client.get("/api/v1/projects?status=completed", headers=headers)
    assert resp_none.status_code == 200
    assert resp_none.json()["total"] == 0


# ── Get ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_project_by_id(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create_resp = await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    project_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id


@pytest.mark.asyncio
async def test_get_project_not_found_returns_404(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_access_project(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    create_resp = await client.post(
        "/api/v1/projects", json=_VALID_PROJECT, headers=owner_headers
    )
    project_id = create_resp.json()["id"]

    intruder_headers = await _auth_headers(client)
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=intruder_headers)
    assert resp.status_code == 403


# ── Update (PATCH) ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_project(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create_resp = await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    project_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Updated Name"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_project_requires_auth(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create_resp = await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    project_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "New"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_other_user_cannot_update_project(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    create_resp = await client.post(
        "/api/v1/projects", json=_VALID_PROJECT, headers=owner_headers
    )
    project_id = create_resp.json()["id"]

    intruder_headers = await _auth_headers(client)
    resp = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Hijacked"},
        headers=intruder_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_project_blank_name_returns_422(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create_resp = await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    project_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "   "},
        headers=headers,
    )
    assert resp.status_code == 422


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_project(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create_resp = await client.post("/api/v1/projects", json=_VALID_PROJECT, headers=headers)
    project_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/projects/{project_id}", headers=headers)
    assert del_resp.status_code == 200

    get_resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_other_user_cannot_delete_project(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    create_resp = await client.post(
        "/api/v1/projects", json=_VALID_PROJECT, headers=owner_headers
    )
    project_id = create_resp.json()["id"]

    intruder_headers = await _auth_headers(client)
    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=intruder_headers)
    assert resp.status_code == 403

    # Verify the project still exists for the owner.
    get_resp = await client.get(f"/api/v1/projects/{project_id}", headers=owner_headers)
    assert get_resp.status_code == 200
