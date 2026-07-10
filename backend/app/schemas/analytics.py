"""
Pydantic response schemas for the analytics API.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OverviewResponse(BaseModel):
    """GET /analytics/overview — aggregated account statistics."""

    total_projects: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    average_runtime_seconds: float
    total_tokens: int
    estimated_total_cost: float
    total_artifacts: int
    success_rate: float           # 0.0 – 100.0


class RunHistoryItem(BaseModel):
    """Single row in GET /analytics/runs."""

    run_id: UUID
    project_id: UUID
    project_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None
    tokens: int
    cost_usd: float
    artifact_count: int


class RunHistoryResponse(BaseModel):
    """GET /analytics/runs — paginated run history."""

    items: list[RunHistoryItem]
    total: int
    offset: int
    limit: int
