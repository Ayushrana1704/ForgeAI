"""
AnalyticsRepository — abstract interface for read-only analytics queries.

All queries are scoped to a single owner (user_id) so that each user only
sees data for their own projects and runs.

Design note
-----------
Analytics queries are complex SQL aggregations across multiple tables.
Placing them here (repository layer) keeps them out of the service and routes
while making them injectable / mockable in tests.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class AnalyticsOverview:
    """Aggregated statistics for a user's entire account."""

    total_projects: int
    total_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    average_runtime_seconds: float
    total_tokens: int
    estimated_total_cost: float
    total_artifacts: int
    success_rate: float          # 0.0 – 100.0


@dataclass
class RunHistoryItem:
    """Single row in the paginated run history table."""

    run_id: UUID
    project_id: UUID
    project_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None   # None when run has no completed_at
    tokens: int
    cost_usd: float
    artifact_count: int


class AnalyticsRepository(ABC):
    @abstractmethod
    async def get_overview(self, owner_id: UUID) -> AnalyticsOverview:
        """Return aggregated stats across all projects owned by owner_id."""

    @abstractmethod
    async def list_runs(
        self,
        owner_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[RunHistoryItem], int]:
        """
        Return paginated run history for owner_id.

        Returns (items, total_count) so the caller can build pagination metadata
        without a second query.
        """
