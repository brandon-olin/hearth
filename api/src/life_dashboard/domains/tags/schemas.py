import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TagSummary(BaseModel):
    """Minimal tag shape embedded in any domain response that supports tagging."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = None


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    color: str | None
    created_at: datetime


class TagListResponse(BaseModel):
    items: list[TagResponse]
    total: int
    limit: int
    offset: int
