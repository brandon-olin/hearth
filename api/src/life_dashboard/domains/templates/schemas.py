import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TemplateScope = Literal["household", "user"]
TemplateDomain = Literal["notes", "documents"]


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    scope: TemplateScope = "household"
    domain: TemplateDomain
    # Optional: pre-fills the entry title on creation; supports {{variable}} syntax
    title_template: str | None = None
    # For domain="notes"
    content_md: str | None = None
    # For domain="documents"
    content_json: dict[str, Any] | None = None


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    scope: TemplateScope | None = None
    title_template: str | None = None
    content_md: str | None = None
    content_json: dict[str, Any] | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    scope: TemplateScope
    name: str
    description: str | None
    domain: TemplateDomain
    title_template: str | None
    content_md: str | None
    content_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class TemplateListResponse(BaseModel):
    items: list[TemplateResponse]
    total: int


# ── Collection-template assignment ────────────────────────────────────────────

class CollectionTemplateAssign(BaseModel):
    """Body for POST /collections/{id}/templates"""
    template_id: uuid.UUID
    is_default: bool = False


class CollectionTemplateResponse(BaseModel):
    """A template as returned within a collection's template list."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID          # CollectionTemplate join row id
    template_id: uuid.UUID
    collection_id: uuid.UUID
    is_default: bool
    created_at: datetime
    # Embedded template details for display
    template: TemplateResponse


class CollectionTemplateListResponse(BaseModel):
    items: list[CollectionTemplateResponse]
    total: int
