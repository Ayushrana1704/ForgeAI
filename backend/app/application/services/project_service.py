from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from app.application.interfaces.project_repository import ProjectRepository
from app.core.exceptions import ForbiddenException, NotFoundException
from app.domain.entities.project import Project
from app.domain.entities.user import User
from app.domain.value_objects.project_status import ProjectStatus
from app.schemas.project import CreateProjectRequest, UpdateProjectRequest

logger = structlog.get_logger(__name__)


class ProjectService:
    def __init__(self, project_repo: ProjectRepository) -> None:
        self._project_repo = project_repo

    async def create(self, request: CreateProjectRequest, owner: User) -> Project:
        now = datetime.now(timezone.utc)
        project = Project(
            id=uuid4(),
            owner_id=owner.id,
            name=request.name,          # already stripped by schema validator
            description=request.description,
            requirements=request.requirements,
            tech_stack=request.tech_stack,
            status=ProjectStatus.DRAFT,  # every new project starts in DRAFT
            created_at=now,
            updated_at=now,
        )
        created = await self._project_repo.create(project)
        logger.info("project_created", project_id=str(created.id), owner_id=str(owner.id))
        return created

    async def get_by_id(self, project_id: UUID, caller: User) -> Project:
        project = await self._project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")
        if project.owner_id != caller.id and not caller.is_superuser:
            raise ForbiddenException("You do not have access to this project")
        return project

    async def list_for_owner(
        self,
        caller: User,
        status: ProjectStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Project], int]:
        projects = await self._project_repo.list_by_owner(
            caller.id,
            status=status,
            offset=offset,
            limit=limit,
        )
        total = await self._project_repo.count_by_owner(caller.id, status=status)
        return projects, total

    async def update(
        self,
        project_id: UUID,
        request: UpdateProjectRequest,
        caller: User,
    ) -> Project:
        project = await self.get_by_id(project_id, caller)

        if request.name is not None:
            project.name = request.name          # already stripped by schema validator
        if request.description is not None:
            project.description = request.description
        if request.requirements is not None:
            project.requirements = request.requirements
        if request.tech_stack is not None:
            project.tech_stack = request.tech_stack

        # updated_at is managed by TimestampMixin's onupdate=func.now() at the
        # DB level — setting it here is redundant and uses a potentially skewed
        # application clock instead of the authoritative database clock.
        updated = await self._project_repo.update(project)
        logger.info("project_updated", project_id=str(project_id), owner_id=str(caller.id))
        return updated

    async def delete(self, project_id: UUID, caller: User) -> None:
        project = await self.get_by_id(project_id, caller)
        await self._project_repo.delete(project.id)
        logger.info("project_deleted", project_id=str(project_id), owner_id=str(caller.id))
