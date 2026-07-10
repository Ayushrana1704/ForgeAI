from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.artifact import Artifact
from app.domain.value_objects.artifact_type import ArtifactType


class ArtifactRepository(ABC):
    @abstractmethod
    async def get_by_id(self, artifact_id: UUID) -> Artifact | None: ...

    @abstractmethod
    async def list_by_project(
        self,
        project_id: UUID,
        run_id: UUID | None = None,
        artifact_type: ArtifactType | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Artifact]: ...

    @abstractmethod
    async def create(self, artifact: Artifact) -> Artifact: ...

    @abstractmethod
    async def delete_by_run(self, run_id: UUID) -> None: ...
