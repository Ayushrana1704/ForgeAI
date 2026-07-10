from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.project_repository import ProjectRepository
from app.core.exceptions import NotFoundException
from app.domain.entities.project import Project
from app.domain.value_objects.project_status import ProjectStatus
from app.infrastructure.database.models.project import ProjectModel


class SQLAlchemyProjectRepository(ProjectRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: UUID) -> Project | None:
        result = await self._session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_owner(
        self,
        owner_id: UUID,
        status: ProjectStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Project]:
        # Build the WHERE clause first, then ORDER BY / pagination so the
        # generated SQL reads naturally and the intent is immediately clear.
        query = select(ProjectModel).where(ProjectModel.owner_id == owner_id)
        if status is not None:
            query = query.where(ProjectModel.status == status.value)
        query = query.order_by(ProjectModel.created_at.desc()).offset(offset).limit(limit)

        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_by_owner(
        self,
        owner_id: UUID,
        status: ProjectStatus | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ProjectModel)
            .where(ProjectModel.owner_id == owner_id)
        )
        if status is not None:
            query = query.where(ProjectModel.status == status.value)

        result = await self._session.execute(query)
        return result.scalar_one()

    async def create(self, project: Project) -> Project:
        model = ProjectModel(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
            description=project.description,
            requirements=project.requirements,
            tech_stack=project.tech_stack,
            status=project.status.value,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def update(self, project: Project) -> Project:
        result = await self._session.execute(
            select(ProjectModel).where(ProjectModel.id == project.id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            # Guard against the race condition where the project was deleted
            # between the service's ownership check and this UPDATE.
            raise NotFoundException(f"Project {project.id} not found")

        model.name = project.name
        model.description = project.description
        model.requirements = project.requirements
        model.tech_stack = project.tech_stack
        model.status = project.status.value
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, project_id: UUID) -> None:
        result = await self._session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            # Already deleted — treat as idempotent; the service already
            # confirmed existence, so this can only happen on a race condition.
            return
        await self._session.delete(model)
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ProjectModel) -> Project:
        return Project(
            id=model.id,
            owner_id=model.owner_id,
            name=model.name,
            description=model.description,
            requirements=model.requirements,
            tech_stack=model.tech_stack or {},
            status=ProjectStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
