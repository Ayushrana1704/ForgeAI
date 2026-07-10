import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin


class ProjectModel(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        Index("idx_projects_owner", "owner_id"),
        Index("idx_projects_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str] = mapped_column(Text, nullable=False)
    tech_stack: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)

    owner: Mapped["UserModel"] = relationship(  # type: ignore[name-defined]
        "UserModel", back_populates="projects"
    )
    runs: Mapped[list["AgentRunModel"]] = relationship(  # type: ignore[name-defined]
        "AgentRunModel",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["ArtifactModel"]] = relationship(  # type: ignore[name-defined]
        "ArtifactModel",
        back_populates="project",
        cascade="all, delete-orphan",
    )
