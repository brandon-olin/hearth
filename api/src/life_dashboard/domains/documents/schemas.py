import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentKind = Literal["page", "template"]


class DocumentCreate(BaseModel):
    parent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    icon: str | None = None
    kind: DocumentKind = "page"
    source_markdown: str | None = None
    editor_json: dict[str, Any] | None = None


class DocumentUpdate(BaseModel):
    parent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    icon: str | None = None
    kind: DocumentKind | None = None
    source_markdown: str | None = None
    editor_json: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    collection_id: uuid.UUID | None
    title: str
    slug: str
    description: str | None
    icon: str | None
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
    collection_id: uuid.UUID | None
    title: str
    slug: str
    description: str | None
    icon: str | None
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


# ── Bulk import ───────────────────────────────────────────────────────────────

class DocumentImportItem(BaseModel):
    """One page from a Notion (or other) export.

    client_id / client_parent_id are temporary identifiers assigned by the
    browser so the server can resolve parent → child relationships without
    knowing real UUIDs in advance.
    """
    client_id: str = Field(min_length=1)
    client_parent_id: str | None = None
    title: str = Field(min_length=1)
    icon: str | None = None
    source_markdown: str | None = None
    editor_json: dict[str, Any] | None = None


class DocumentImportRequest(BaseModel):
    items: list[DocumentImportItem] = Field(min_length=1)


class DocumentImportResultItem(DocumentSummary):
    """DocumentSummary extended with the browser-assigned client_id so the
    client can reconcile imported pages with its pre-upload state (e.g. to
    rewrite inter-page links after receiving real UUIDs)."""
    client_id: str


class DocumentImportResponse(BaseModel):
    created: int
    skipped: int
    items: list[DocumentImportResultItem]


# ── Search ────────────────────────────────────────────────────────────────────

class DocumentSearchResult(DocumentSummary):
    """DocumentSummary with match metadata for ranked search results."""
    match_type: Literal["title", "body"]
    snippet: str | None = None  # Short excerpt around the body match


class DocumentSearchResponse(BaseModel):
    items: list[DocumentSearchResult]
    has_more: bool
