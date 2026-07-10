import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api.middleware import RequestContextMiddleware
from app.api.v1.routes import analytics, auth, health, projects, runs, users
from app.core.config import Settings, settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

# Providers that ship with sensible defaults and don't need a real API key.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"lmstudio", "ollama", "vllm"})
_KNOWN_PROVIDERS: frozenset[str] = frozenset({"openai", "azure"}) | _LOCAL_PROVIDERS


def _validate_llm_config(cfg: Settings) -> None:
    """
    Validate LLM configuration at application startup.

    Raises RuntimeError with an actionable message if the configuration is
    incomplete or inconsistent.  This prevents the first workflow execution
    from being the point of discovery for misconfiguration.
    """
    provider = cfg.LLM_PROVIDER.lower()

    if provider not in _KNOWN_PROVIDERS:
        raise RuntimeError(
            f"LLM_PROVIDER={cfg.LLM_PROVIDER!r} is not supported. "
            f"Valid values: {sorted(_KNOWN_PROVIDERS)}"
        )

    if not cfg.LLM_MODEL or not cfg.LLM_MODEL.strip():
        raise RuntimeError(
            "LLM_MODEL must be set to a non-empty model name "
            "(e.g. 'gpt-4o-mini' for OpenAI, 'llama3' for Ollama)."
        )

    if provider == "azure":
        if not cfg.LLM_BASE_URL:
            raise RuntimeError(
                "LLM_BASE_URL must be set when LLM_PROVIDER=azure "
                "(e.g. https://<resource>.openai.azure.com)."
            )
        if not cfg.LLM_API_KEY:
            raise RuntimeError(
                "LLM_API_KEY must be set when LLM_PROVIDER=azure."
            )

    if provider == "openai":
        # The OpenAI SDK falls back to the OPENAI_API_KEY env var when
        # LLM_API_KEY is None, so accept either source.
        has_key = cfg.LLM_API_KEY or os.environ.get("OPENAI_API_KEY")
        if not has_key:
            raise RuntimeError(
                "LLM_API_KEY (or environment variable OPENAI_API_KEY) must be "
                "set when LLM_PROVIDER=openai."
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    _validate_llm_config(settings)
    logger.info(
        "startup",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
    )
    yield
    logger.info("shutdown", service=settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Enterprise Multi-Agent Software Engineering Platform",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        # RFC 7235 §3.1: every 401 response MUST include WWW-Authenticate.
        headers: dict[str, str] | None = (
            {"WWW-Authenticate": "Bearer"}
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
    app.include_router(runs.router, prefix="/api/v1", tags=["runs"])
    app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])

    # ── OpenAPI / Swagger Bearer auth ─────────────────────────────────────────
    # Defining a global BearerAuth security scheme allows developers to click
    # "Authorize" in Swagger UI, paste their access token from POST /auth/login,
    # and test every protected endpoint without manually adding Authorization
    # headers.  The scheme is applied globally (all operations); public
    # endpoints such as /health and /auth/login simply ignore the credential.
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema  # type: ignore[return-value]
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description or "",
            routes=app.routes,
        )
        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Paste the **access_token** returned by `POST /api/v1/auth/login`."
                ),
            }
        }
        schema["security"] = [{"BearerAuth": []}]
        app.openapi_schema = schema
        return schema  # type: ignore[return-value]

    app.openapi = custom_openapi  # type: ignore[method-assign]

    return app


app = create_app()
