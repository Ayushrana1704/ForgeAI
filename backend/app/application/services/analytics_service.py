"""
AnalyticsService — orchestration layer for analytics endpoints.

Responsibilities
----------------
1. Accept a verified caller (User entity from the auth guard).
2. Delegate all DB work to AnalyticsRepository.
3. Return domain dataclasses that the route layer serialises into responses.

There is intentionally no complex business logic here; analytics is read-only
so there are no ownership assertions beyond passing the caller's ID through.
"""
from __future__ import annotations

from uuid import UUID

from app.application.interfaces.analytics_repository import (
    AnalyticsOverview,
    AnalyticsRepository,
    RunHistoryItem,
)
from app.domain.entities.user import User


class AnalyticsService:
    def __init__(self, analytics_repo: AnalyticsRepository) -> None:
        self._repo = analytics_repo

    async def get_overview(self, caller: User) -> AnalyticsOverview:
        """Return aggregated stats scoped to the caller's projects."""
        return await self._repo.get_overview(caller.id)

    async def list_runs(
        self,
        caller: User,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[RunHistoryItem], int]:
        """Return paginated run history scoped to the caller's projects."""
        return await self._repo.list_runs(caller.id, offset=offset, limit=limit)
