import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentKind = Literal["page", "template"]


class DocumentCreate(BaseModel):
    parent_id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    kind: DocumentKind = "page"
    source_markdown: str | None = None
    editor_json: dict[str, Any] | None = None


class DocumentUpdate(BaseModel):
    parent_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    kind: DocumentKind | None = None
    source_markdown: str | None = None
    editor_json: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    title: str
    slug: str
    description: str | None
    kind: DocumentKind
    source_markdown: str | None
    editor_json: dict[str, Any] | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentSummary(BaseModel):
    """Lightweight shape used in tree listings — omits large content fields."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    title: str
    slug: str
    description: str | None
    kind: DocumentKind
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentTreeResponse(BaseModel):
    """Flat list of all unarchived documents; client builds the tree from parent_id."""
    items: list[DocumentSummary]
    total: int


class DocumentChildrenResponse(BaseModel):
    items: list[DocumentSummary]
