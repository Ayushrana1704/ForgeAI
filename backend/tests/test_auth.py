import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from jose import jwt

from app.core.config import settings
from tests.conftest import register_and_login

_EMAIL = f"auth_{uuid.uuid4().hex[:8]}@test.com"
_PASSWORD = "Secure1pass"


# ── Registration ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_creates_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD, "full_name": "Alice"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == _EMAIL
    assert "hashed_password" not in body
    assert body["is_active"] is True
    assert body["is_superuser"] is False


@pytest.mark.asyncio
async def test_register_duplicate_returns_409(client: AsyncClient) -> None:
    email = f"dup_{uuid.uuid4().hex[:8]}@test.com"
    payload = {"email": email, "password": _PASSWORD}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_invalid_email_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": _PASSWORD},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_weak_password_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@test.com", "password": "noDIGIT"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_body_returns_422(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/register", json={})
    assert resp.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_returns_tokens(client: AsyncClient) -> None:
    email = f"login_{uuid.uuid4().hex[:8]}@test.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": _EMAIL, "password": "WrongPass1"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@test.com", "password": _PASSWORD}
    )
    assert resp.status_code == 401


# ── Protected routes ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_me_authenticated(client: AsyncClient) -> None:
    email = f"me_{uuid.uuid4().hex[:8]}@test.com"
    token = await register_and_login(client, email, _PASSWORD)
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email


@pytest.mark.asyncio
async def test_get_me_missing_auth_returns_401(client: AsyncClient) -> None:
    # RFC 7235: absent credentials must yield 401 (not 403).
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401
    # RFC 7235 §3.1: 401 must carry WWW-Authenticate.
    assert "www-authenticate" in resp.headers
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer totally.invalid.token"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(client: AsyncClient) -> None:
    # Craft a structurally valid JWT whose exp is 1 hour in the past.
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired_token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "type": "access",
            "iat": past,
            "exp": past + timedelta(minutes=15),  # still in the past
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert resp.status_code == 401


# ── Token operations ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token_works(client: AsyncClient) -> None:
    email = f"refresh_{uuid.uuid4().hex[:8]}@test.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    refresh_token = login_resp.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_access_token_rejected_as_refresh(client: AsyncClient) -> None:
    # Using an access token where a refresh token is expected must return 401.
    email = f"wrongtype_{uuid.uuid4().hex[:8]}@test.com"
    access_token = await register_and_login(client, email, _PASSWORD)

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": access_token}
    )
    assert resp.status_code == 401
