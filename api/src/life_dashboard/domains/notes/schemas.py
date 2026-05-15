import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from life_dashboard.core.pydantic_types import CoercedList


# ── Tag reference (embedded in note responses) ────────────────────────────────

class TagRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None


# ── Backlink references ───────────────────────────────────────────────────────

class BacklinkRef(BaseModel):
    """A note that links to (or is linked from) this note."""
    id: uuid.UUID
    title: str
    alias: str | None  # The [[...]] text as written in the source


# ── Note schemas ──────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    title: str
    content_md: str | None = None
    content_json: dict[str, Any] | None = None
    tag_ids: list[uuid.UUID] = []
    collection_id: uuid.UUID | None = None
    # Notes are always personal — visibility and sharing are not exposed.


class NoteUpdate(BaseModel):
    title: str | None = None
    content_md: str | None = None
    content_json: dict[str, Any] | None = None
    tag_ids: list[uuid.UUID] | None = None
    collection_id: uuid.UUID | None = None
    # Notes are always personal — visibility and sharing are not exposed.


class NoteSummary(BaseModel):
    """Lightweight representation used in list/search results."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content_md: str | None
    collection_id: uuid.UUID | None
    visibility: str
    shared_with_user_ids: CoercedList
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NoteResponse(BaseModel):
    """Full note with tags and backlinks."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content_md: str | None
    content_json: dict[str, Any] | None
    collection_id: uuid.UUID | None
    visibility: str
    shared_with_user_ids: CoercedList
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    tags: list[TagRef] = []
    backlinks: list[BacklinkRef] = []   # Notes that link TO this one


class NoteListResponse(BaseModel):
    items: list[NoteSummary]
    total: int
