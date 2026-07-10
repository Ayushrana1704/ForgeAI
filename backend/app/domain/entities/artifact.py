from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.artifact_type import ArtifactType


@dataclass
class Artifact:
    id: UUID
    project_id: UUID
    artifact_type: ArtifactType
    file_path: str
    created_at: datetime
    run_id: UUID | None = None
    step_id: UUID | None = None
    language: str | None = None
    size_bytes: int = 0
    checksum: str | None = None
    storage_key: str | None = None
    content: str | None = None
    metadata: dict = field(default_factory=dict)
