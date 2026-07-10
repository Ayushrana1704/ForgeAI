from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.value_objects.project_status import ProjectStatus


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    requirements: str = Field(..., min_length=10, max_length=50_000)
    tech_stack: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        """Strip surrounding whitespace and reject a name that is only whitespace."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)
    requirements: str | None = Field(None, min_length=10, max_length=50_000)
    tech_stack: dict | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class ProjectResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    requirements: str
    tech_stack: dict
    status: ProjectStatus   # StrEnum serialises to its string value in JSON
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    offset: int
    limit: int
