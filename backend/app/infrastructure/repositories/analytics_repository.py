"""
SQLAlchemy implementation of AnalyticsRepository.

All queries run against the existing tables — no schema changes required.

Query strategy
--------------
overview
    Two queries:
    1. Aggregate project + run + artifact counts via LEFT JOIN so we get correct
       artifact counts even when steps have no llm_calls.
    2. Token + cost aggregation from agent_steps (separate because joining steps
       in the same query as artifacts produces a cartesian product).

list_runs
    JOIN agent_runs → projects for the project name.
    Subquery-aggregate agent_steps (tokens, cost) and artifacts (count) then
    JOIN them so each run row has accurate step/artifact totals.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.analytics_repository import (
    AnalyticsOverview,
    AnalyticsRepository,
    RunHistoryItem,
)
from app.infrastructure.database.models.agent_run import AgentRunModel
from app.infrastructure.database.models.agent_step import AgentStepModel
from app.infrastructure.database.models.artifact import ArtifactModel
from app.infrastructure.database.models.project import ProjectModel


class SQLAlchemyAnalyticsRepository(AnalyticsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Overview ──────────────────────────────────────────────────────────────

    async def get_overview(self, owner_id: UUID) -> AnalyticsOverview:
        # ── Query 1: projects / runs / artifacts / runtime ────────────────────
        # We aggregate runs and artifacts separately via subqueries to avoid
        # cross-join inflation.
        artifact_sub = (
            select(
                ArtifactModel.project_id,
                func.count(ArtifactModel.id).label("cnt"),
            )
            .group_by(ArtifactModel.project_id)
            .subquery()
        )

        run_sub = (
            select(
                AgentRunModel.project_id,
                func.count(AgentRunModel.id).label("total"),
                func.count(AgentRunModel.id)
                .filter(AgentRunModel.status == "completed")
                .label("completed"),
                func.count(AgentRunModel.id)
                .filter(AgentRunModel.status == "failed")
                .label("failed"),
                func.count(AgentRunModel.id)
                .filter(AgentRunModel.status == "cancelled")
                .label("cancelled"),
                func.avg(
                    func.extract(
                        "epoch",
                        AgentRunModel.completed_at - AgentRunModel.started_at,
                    )
                )
                .filter(
                    AgentRunModel.completed_at.is_not(None),
                    AgentRunModel.started_at.is_not(None),
                )
                .label("avg_runtime"),
            )
            .group_by(AgentRunModel.project_id)
            .subquery()
        )

        q1 = (
            select(
                func.count(ProjectModel.id).label("total_projects"),
                func.coalesce(func.sum(run_sub.c.total), 0).label("total_runs"),
                func.coalesce(func.sum(run_sub.c.completed), 0).label("completed_runs"),
                func.coalesce(func.sum(run_sub.c.failed), 0).label("failed_runs"),
                func.coalesce(func.sum(run_sub.c.cancelled), 0).label("cancelled_runs"),
                func.avg(run_sub.c.avg_runtime).label("avg_runtime"),
                func.coalesce(func.sum(artifact_sub.c.cnt), 0).label("total_artifacts"),
            )
            .select_from(ProjectModel)
            .outerjoin(run_sub, run_sub.c.project_id == ProjectModel.id)
            .outerjoin(artifact_sub, artifact_sub.c.project_id == ProjectModel.id)
            .where(ProjectModel.owner_id == owner_id)
        )

        row1 = (await self._session.execute(q1)).one()

        # ── Query 2: token + cost totals from agent_steps ─────────────────────
        q2 = (
            select(
                func.coalesce(func.sum(AgentStepModel.tokens_used), 0).label("tokens"),
                func.coalesce(func.sum(AgentStepModel.cost_usd), 0).label("cost"),
            )
            .select_from(AgentStepModel)
            .join(AgentRunModel, AgentRunModel.id == AgentStepModel.run_id)
            .join(ProjectModel, ProjectModel.id == AgentRunModel.project_id)
            .where(ProjectModel.owner_id == owner_id)
        )

        row2 = (await self._session.execute(q2)).one()

        total_runs = int(row1.total_runs)
        completed_runs = int(row1.completed_runs)
        avg_rt = float(row1.avg_runtime) if row1.avg_runtime is not None else 0.0
        success_rate = (
            round(completed_runs / total_runs * 100, 1) if total_runs > 0 else 0.0
        )

        return AnalyticsOverview(
            total_projects=int(row1.total_projects),
            total_runs=total_runs,
            completed_runs=completed_runs,
            failed_runs=int(row1.failed_runs),
            cancelled_runs=int(row1.cancelled_runs),
            average_runtime_seconds=round(avg_rt, 1),
            total_tokens=int(row2.tokens),
            estimated_total_cost=round(float(row2.cost), 6),
            total_artifacts=int(row1.total_artifacts),
            success_rate=success_rate,
        )

    # ── Run history ───────────────────────────────────────────────────────────

    async def list_runs(
        self,
        owner_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[RunHistoryItem], int]:
        # Step aggregation subquery
        step_sub = (
            select(
                AgentStepModel.run_id,
                func.coalesce(func.sum(AgentStepModel.tokens_used), 0).label("tokens"),
                func.coalesce(func.sum(AgentStepModel.cost_usd), 0).label("cost"),
            )
            .group_by(AgentStepModel.run_id)
            .subquery()
        )

        # Artifact count subquery
        artifact_sub = (
            select(
                ArtifactModel.run_id,
                func.count(ArtifactModel.id).label("cnt"),
            )
            .where(ArtifactModel.run_id.is_not(None))
            .group_by(ArtifactModel.run_id)
            .subquery()
        )

        base = (
            select(AgentRunModel, ProjectModel.name.label("project_name"))
            .join(ProjectModel, ProjectModel.id == AgentRunModel.project_id)
            .where(ProjectModel.owner_id == owner_id)
        )

        # Total count (no pagination)
        count_q = select(func.count()).select_from(base.subquery())
        total = (await self._session.execute(count_q)).scalar_one()

        # Paginated data with aggregated columns
        data_q = (
            select(
                AgentRunModel.id,
                AgentRunModel.project_id,
                ProjectModel.name.label("project_name"),
                AgentRunModel.status,
                AgentRunModel.started_at,
                AgentRunModel.completed_at,
                AgentRunModel.created_at,
                func.extract(
                    "epoch",
                    AgentRunModel.completed_at - AgentRunModel.started_at,
                ).label("duration_seconds"),
                func.coalesce(step_sub.c.tokens, 0).label("tokens"),
                func.coalesce(step_sub.c.cost, 0).label("cost"),
                func.coalesce(artifact_sub.c.cnt, 0).label("artifact_count"),
            )
            .join(ProjectModel, ProjectModel.id == AgentRunModel.project_id)
            .outerjoin(step_sub, step_sub.c.run_id == AgentRunModel.id)
            .outerjoin(artifact_sub, artifact_sub.c.run_id == AgentRunModel.id)
            .where(ProjectModel.owner_id == owner_id)
            .order_by(AgentRunModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        rows = (await self._session.execute(data_q)).all()

        items = [
            RunHistoryItem(
                run_id=row.id,
                project_id=row.project_id,
                project_name=row.project_name,
                status=row.status,
                started_at=row.started_at,
                completed_at=row.completed_at,
                duration_seconds=(
                    round(float(row.duration_seconds), 1)
                    if row.duration_seconds is not None
                    else None
                ),
                tokens=int(row.tokens),
                cost_usd=round(float(row.cost), 6),
                artifact_count=int(row.artifact_count),
            )
            for row in rows
        ]

        return items, int(total)
