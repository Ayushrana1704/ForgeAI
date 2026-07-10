import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("idx_artifacts_project", "project_id"),
        Index("idx_artifacts_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Column name 'metadata' is a reserved SQLAlchemy attribute — use alias
    artifact_metadata: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False, key="artifact_metadata", name="metadata"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["ProjectModel"] = relationship(  # type: ignore[name-defined]
        "ProjectModel", back_populates="artifacts"
    )
    run: Mapped["AgentRunModel | None"] = relationship(  # type: ignore[name-defined]
        "AgentRunModel", back_populates="artifacts"
    )
    step: Mapped["AgentStepModel | None"] = relationship(  # type: ignore[name-defined]
        "AgentStepModel", back_populates="artifacts"
    )
