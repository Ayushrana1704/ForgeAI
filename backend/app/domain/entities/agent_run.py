from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.run_status import RunStatus


@dataclass
class AgentRun:
    id: UUID
    project_id: UUID
    status: RunStatus
    trigger: str
    created_at: datetime
    graph_state: dict = field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
