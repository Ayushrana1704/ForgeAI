"""
Analytics API routes.

Endpoints
---------
GET /api/v1/analytics/overview
    Aggregated statistics for the authenticated user's account.

GET /api/v1/analytics/runs
    Paginated run history with project name, duration, token use, cost.

All endpoints require authentication.  Data is scoped to the caller's own
projects — users cannot access other users' analytics.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_analytics_service, get_current_user
from app.application.services.analytics_service import AnalyticsService
from app.domain.entities.user import User
from app.schemas.analytics import OverviewResponse, RunHistoryItem, RunHistoryResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Aggregated analytics overview for the authenticated user",
)
async def get_overview(
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> OverviewResponse:
    """
    Return a single JSON object with account-wide aggregated statistics.

    All figures are scoped to projects owned by the authenticated user.
    """
    overview = await analytics_service.get_overview(current_user)
    return OverviewResponse(
        total_projects=overview.total_projects,
        total_runs=overview.total_runs,
        completed_runs=overview.completed_runs,
        failed_runs=overview.failed_runs,
        cancelled_runs=overview.cancelled_runs,
        average_runtime_seconds=overview.average_runtime_seconds,
        total_tokens=overview.total_tokens,
        estimated_total_cost=overview.estimated_total_cost,
        total_artifacts=overview.total_artifacts,
        success_rate=overview.success_rate,
    )


@router.get(
    "/runs",
    response_model=RunHistoryResponse,
    summary="Paginated run history for the authenticated user",
)
async def list_runs(
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> RunHistoryResponse:
    """
    Return a paginated list of all runs across the user's projects.

    Each row includes: project name, status, start/end timestamps, wall-clock
    duration, total token usage, estimated cost, and artifact count.
    """
    items, total = await analytics_service.list_runs(
        current_user, offset=offset, limit=limit
    )
    return RunHistoryResponse(
        items=[
            RunHistoryItem(
                run_id=item.run_id,
                project_id=item.project_id,
                project_name=item.project_name,
                status=item.status,
                started_at=item.started_at,
                completed_at=item.completed_at,
                duration_seconds=item.duration_seconds,
                tokens=item.tokens,
                cost_usd=item.cost_usd,
                artifact_count=item.artifact_count,
            )
            for item in items
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
