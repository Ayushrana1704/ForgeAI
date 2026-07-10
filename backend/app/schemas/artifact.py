from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ArtifactResponse(BaseModel):
    id: UUID
    project_id: UUID
    run_id: UUID | None
    step_id: UUID | None
    artifact_type: str
    file_path: str
    language: str | None
    size_bytes: int
    created_at: datetime
    description: str | None = None

    model_config = {"from_attributes": True}
