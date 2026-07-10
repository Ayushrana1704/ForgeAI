from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.llm_provider import LLMProvider
from app.application.services.auth_service import AuthService
from app.application.services.llm.llm_service import LLMService
from app.application.services.project_service import ProjectService
from app.application.services.workflow_service import WorkflowService
from app.core.config import settings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.domain.entities.user import User
from app.infrastructure.database.session import get_db
from app.infrastructure.llm.providers.openai_provider import OpenAICompatibleProvider
from app.infrastructure.repositories.artifact_repository import SQLAlchemyArtifactRepository
from app.infrastructure.repositories.project_repository import SQLAlchemyProjectRepository
from app.infrastructure.repositories.run_repository import SQLAlchemyRunRepository
from app.infrastructure.repositories.user_repository import SQLAlchemyUserRepository

# auto_error=False so FastAPI does not raise its own 403 when the Authorization
# header is absent. We raise a proper 401 (+ WWW-Authenticate via the exception
# handler in main.py) ourselves in get_current_user().
_bearer = HTTPBearer(auto_error=False)


# ── Repository factories ────────────────────────────────────────────────────


async def get_user_repo(
    session: AsyncSession = Depends(get_db),
) -> SQLAlchemyUserRepository:
    return SQLAlchemyUserRepository(session)


async def get_project_repo(
    session: AsyncSession = Depends(get_db),
) -> SQLAlchemyProjectRepository:
    return SQLAlchemyProjectRepository(session)


async def get_run_repo(
    session: AsyncSession = Depends(get_db),
) -> SQLAlchemyRunRepository:
    return SQLAlchemyRunRepository(session)


async def get_artifact_repo(
    session: AsyncSession = Depends(get_db),
) -> SQLAlchemyArtifactRepository:
    return SQLAlchemyArtifactRepository(session)


# ── Auth guards ─────────────────────────────────────────────────────────────


async def get_auth_service(
    user_repo: SQLAlchemyUserRepository = Depends(get_user_repo),
) -> AuthService:
    return AuthService(user_repo)


async def get_project_service(
    project_repo: SQLAlchemyProjectRepository = Depends(get_project_repo),
) -> ProjectService:
    return ProjectService(project_repo)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve the authenticated user from the Bearer token.

    Raises UnauthorizedException (-> 401 + WWW-Authenticate) for:
    - missing Authorization header
    - malformed / expired / wrong-type token
    - token references a deleted or deactivated user
    """
    if credentials is None:
        raise UnauthorizedException("Authentication required")
    return await auth_service.get_current_user(credentials.credentials)


async def require_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_superuser:
        raise ForbiddenException("Superuser access required")
    return current_user


# ── LLM ─────────────────────────────────────────────────────────────────────

# The provider is a long-lived HTTP client (connection pool).  We create it
# exactly once via lru_cache and reuse the same instance for every request.
@lru_cache(maxsize=1)
def _build_llm_provider() -> LLMProvider:
    return OpenAICompatibleProvider(settings)


async def get_llm_provider() -> LLMProvider:
    """Return the singleton LLMProvider for this process."""
    return _build_llm_provider()


async def get_llm_service(
    provider: LLMProvider = Depends(get_llm_provider),
) -> LLMService:
    """Return an LLMService bound to the configured provider."""
    return LLMService(provider)


# ── Workflow ─────────────────────────────────────────────────────────────────

# Defined after get_llm_service so the Depends() reference resolves correctly.
async def get_workflow_service(
    project_repo: SQLAlchemyProjectRepository = Depends(get_project_repo),
    run_repo: SQLAlchemyRunRepository = Depends(get_run_repo),
    artifact_repo: SQLAlchemyArtifactRepository = Depends(get_artifact_repo),
    llm_service: LLMService = Depends(get_llm_service),
) -> WorkflowService:
    return WorkflowService(
        project_repo=project_repo,
        run_repo=run_repo,
        artifact_repo=artifact_repo,
        llm_service=llm_service,
    )


# ── Analytics ────────────────────────────────────────────────────────────────

from app.application.services.analytics_service import AnalyticsService
from app.infrastructure.repositories.analytics_repository import SQLAlchemyAnalyticsRepository


async def get_analytics_service(
    session: AsyncSession = Depends(get_db),
) -> AnalyticsService:
    """Return an AnalyticsService bound to the current DB session."""
    return AnalyticsService(SQLAlchemyAnalyticsRepository(session))
