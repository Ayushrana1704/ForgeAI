from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.project import Project
from app.domain.value_objects.project_status import ProjectStatus


class ProjectRepository(ABC):
    @abstractmethod
    async def get_by_id(self, project_id: UUID) -> Project | None: ...

    @abstractmethod
    async def list_by_owner(
        self,
        owner_id: UUID,
        status: ProjectStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Project]: ...

    @abstractmethod
    async def count_by_owner(
        self,
        owner_id: UUID,
        status: ProjectStatus | None = None,
    ) -> int: ...

    @abstractmethod
    async def create(self, project: Project) -> Project: ...

    @abstractmethod
    async def update(self, project: Project) -> Project: ...

    @abstractmethod
    async def delete(self, project_id: UUID) -> None: ...
