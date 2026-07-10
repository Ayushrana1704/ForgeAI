from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.agent_type import AgentType


@dataclass
class AgentStep:
    id: UUID
    run_id: UUID
    agent_type: AgentType
    sequence: int
    status: str
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
