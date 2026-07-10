from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_llm_service
from app.application.services.llm.llm_service import LLMService
from app.core.config import settings
from app.infrastructure.database.session import get_db

router = APIRouter()


@router.get("/health", summary="Liveness check")
async def health() -> dict:
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@router.get("/health/ready", summary="Readiness check -- verifies DB and LLM connectivity")
async def readiness(
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> dict:
    await session.execute(text("SELECT 1"))
    llm_healthy = await llm_service.health_check()
    return {
        "status": "ready",
        "database": "connected",
        "llm_provider": "healthy" if llm_healthy else "degraded",
        "llm_provider_name": llm_service.provider_name,
        "llm_default_model": llm_service.default_model,
    }
