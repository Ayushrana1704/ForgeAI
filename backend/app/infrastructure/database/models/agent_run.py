import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class AgentRunModel(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("idx_runs_project", "project_id"),
        Index("idx_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    graph_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["ProjectModel"] = relationship(  # type: ignore[name-defined]
        "ProjectModel", back_populates="runs"
    )
    steps: Mapped[list["AgentStepModel"]] = relationship(  # type: ignore[name-defined]
        "AgentStepModel",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStepModel.sequence",
    )
    artifacts: Mapped[list["ArtifactModel"]] = relationship(  # type: ignore[name-defined]
        "ArtifactModel", back_populates="run"
    )
