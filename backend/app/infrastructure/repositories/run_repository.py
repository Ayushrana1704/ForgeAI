from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.run_repository import RunRepository
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.agent_step import AgentStep
from app.domain.value_objects.agent_type import AgentType
from app.domain.value_objects.run_status import RunStatus
from app.infrastructure.database.models.agent_run import AgentRunModel
from app.infrastructure.database.models.agent_step import AgentStepModel


class SQLAlchemyRunRepository(RunRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, run_id: UUID) -> AgentRun | None:
        result = await self._session.execute(
            select(AgentRunModel).where(AgentRunModel.id == run_id)
        )
        model = result.scalar_one_or_none()
        return self._run_to_entity(model) if model else None

    async def list_by_project(
        self,
        project_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> list[AgentRun]:
        result = await self._session.execute(
            select(AgentRunModel)
            .where(AgentRunModel.project_id == project_id)
            .order_by(AgentRunModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [self._run_to_entity(m) for m in result.scalars().all()]

    async def create(self, run: AgentRun) -> AgentRun:
        model = AgentRunModel(
            id=run.id,
            project_id=run.project_id,
            status=run.status.value,
            trigger=run.trigger,
            graph_state=run.graph_state,
            error_message=run.error_message,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._run_to_entity(model)

    async def update_status(
        self,
        run_id: UUID,
        status: RunStatus,
        error_message: str | None = None,
    ) -> None:
        result = await self._session.execute(
            select(AgentRunModel).where(AgentRunModel.id == run_id)
        )
        model = result.scalar_one()
        model.status = status.value
        model.error_message = error_message

        if status == RunStatus.RUNNING and model.started_at is None:
            model.started_at = datetime.now(timezone.utc)
        if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            model.completed_at = datetime.now(timezone.utc)

        await self._session.flush()

    async def save_graph_state(
        self,
        run_id: UUID,
        graph_state: dict,
    ) -> None:
        result = await self._session.execute(
            select(AgentRunModel).where(AgentRunModel.id == run_id)
        )
        model = result.scalar_one()
        model.graph_state = graph_state
        await self._session.flush()

    async def get_steps(self, run_id: UUID) -> list[AgentStep]:
        result = await self._session.execute(
            select(AgentStepModel)
            .where(AgentStepModel.run_id == run_id)
            .order_by(AgentStepModel.sequence)
        )
        return [self._step_to_entity(m) for m in result.scalars().all()]

    async def upsert_step(self, step: AgentStep) -> AgentStep:
        result = await self._session.execute(
            select(AgentStepModel).where(AgentStepModel.id == step.id)
        )
        model = result.scalar_one_or_none()

        if model is None:
            model = AgentStepModel(
                id=step.id,
                run_id=step.run_id,
                agent_type=step.agent_type.value,
                sequence=step.sequence,
                status=step.status,
                input=step.input,
                output=step.output,
                tokens_used=step.tokens_used,
                cost_usd=step.cost_usd,
                duration_ms=step.duration_ms,
                error_message=step.error_message,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            self._session.add(model)
        else:
            model.status = step.status
            model.output = step.output
            model.tokens_used = step.tokens_used
            model.cost_usd = step.cost_usd
            model.duration_ms = step.duration_ms
            model.error_message = step.error_message
            model.started_at = step.started_at
            model.completed_at = step.completed_at

        await self._session.flush()
        await self._session.refresh(model)
        return self._step_to_entity(model)

    @staticmethod
    def _run_to_entity(model: AgentRunModel) -> AgentRun:
        return AgentRun(
            id=model.id,
            project_id=model.project_id,
            status=RunStatus(model.status),
            trigger=model.trigger,
            graph_state=model.graph_state or {},
            error_message=model.error_message,
            started_at=model.started_at,
            completed_at=model.completed_at,
            created_at=model.created_at,
        )

    @staticmethod
    def _step_to_entity(model: AgentStepModel) -> AgentStep:
        return AgentStep(
            id=model.id,
            run_id=model.run_id,
            agent_type=AgentType(model.agent_type),
            sequence=model.sequence,
            status=model.status,
            input=model.input or {},
            output=model.output or {},
            tokens_used=model.tokens_used,
            cost_usd=float(model.cost_usd),
            duration_ms=model.duration_ms,
            error_message=model.error_message,
            started_at=model.started_at,
            completed_at=model.completed_at,
        )
