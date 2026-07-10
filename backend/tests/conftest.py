import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.database.base import Base
from app.infrastructure.database.session import get_db
from app.main import app

# Uses a separate test database; fall back to a renamed version of DATABASE_URL
import os

_db_url = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://forgeai:forgeai@localhost:5432/forgeai_test",
)

_engine = create_async_engine(_db_url, echo=False)
_SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def create_tables() -> None:
    # Import models so metadata is populated
    import app.infrastructure.database.models  # noqa: F401

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest.fixture
async def db() -> AsyncSession:
    async with _SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def register_and_login(client: AsyncClient, email: str, password: str) -> str:
    """Register a user (ignoring conflicts) and return a valid access token."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]
