from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class ErrorResponse(BaseModel):
    detail: str


class MessageResponse(BaseModel):
    message: str = Field(..., description="Human-readable status message")
