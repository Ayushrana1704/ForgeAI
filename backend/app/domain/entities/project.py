from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.project_status import ProjectStatus


@dataclass
class Project:
    id: UUID
    owner_id: UUID
    name: str
    requirements: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    tech_stack: dict = field(default_factory=dict)
