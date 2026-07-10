import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class AgentStepModel(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        Index("idx_steps_run", "run_id"),
        Index("idx_steps_sequence", "run_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 8), default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    run: Mapped["AgentRunModel"] = relationship(  # type: ignore[name-defined]
        "AgentRunModel", back_populates="steps"
    )
    llm_calls: Mapped[list["LLMCallModel"]] = relationship(  # type: ignore[name-defined]
        "LLMCallModel",
        back_populates="step",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["ArtifactModel"]] = relationship(  # type: ignore[name-defined]
        "ArtifactModel", back_populates="step"
    )
