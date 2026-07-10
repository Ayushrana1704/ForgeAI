from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.artifact_repository import ArtifactRepository
from app.domain.entities.artifact import Artifact
from app.domain.value_objects.artifact_type import ArtifactType
from app.infrastructure.database.models.artifact import ArtifactModel


class SQLAlchemyArtifactRepository(ArtifactRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, artifact_id: UUID) -> Artifact | None:
        result = await self._session.execute(
            select(ArtifactModel).where(ArtifactModel.id == artifact_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_project(
        self,
        project_id: UUID,
        run_id: UUID | None = None,
        artifact_type: ArtifactType | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Artifact]:
        query = (
            select(ArtifactModel)
            .where(ArtifactModel.project_id == project_id)
            .order_by(ArtifactModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        if run_id is not None:
            query = query.where(ArtifactModel.run_id == run_id)
        if artifact_type is not None:
            query = query.where(ArtifactModel.artifact_type == artifact_type.value)

        result = await self._session.execute(query)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def create(self, artifact: Artifact) -> Artifact:
        model = ArtifactModel(
            id=artifact.id,
            project_id=artifact.project_id,
            run_id=artifact.run_id,
            step_id=artifact.step_id,
            artifact_type=artifact.artifact_type.value,
            file_path=artifact.file_path,
            language=artifact.language,
            size_bytes=artifact.size_bytes,
            checksum=artifact.checksum,
            storage_key=artifact.storage_key,
            content=artifact.content,
            artifact_metadata=artifact.metadata,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete_by_run(self, run_id: UUID) -> None:
        await self._session.execute(
            delete(ArtifactModel).where(ArtifactModel.run_id == run_id)
        )
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ArtifactModel) -> Artifact:
        return Artifact(
            id=model.id,
            project_id=model.project_id,
            run_id=model.run_id,
            step_id=model.step_id,
            artifact_type=ArtifactType(model.artifact_type),
            file_path=model.file_path,
            language=model.language,
            size_bytes=model.size_bytes,
            checksum=model.checksum,
            storage_key=model.storage_key,
            content=model.content,
            metadata=model.artifact_metadata or {},
            created_at=model.created_at,
        )
