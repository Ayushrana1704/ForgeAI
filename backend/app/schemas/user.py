from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateMeRequest(BaseModel):
    full_name: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
