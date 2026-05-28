import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CollectionDomain = Literal["notes", "documents"]


class AutoCreateRule(BaseModel):
    """Rule for automatic entry creation inside a collection."""
    frequency: Literal["daily"]
    # {{variable}} syntax — resolved with the creating user's locale settings.
    # Available: {{date}}, {{day}}, {{day_of_week}}, {{week_number}},
    #            {{month}}, {{month_num}}, {{year}}, {{time}}, {{user_name}}
    title_template: str = "{{day_of_week}}, {{month}} {{day}}, {{year}}"


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1)
    icon: str | None = None
    domain: CollectionDomain
    default_tags: list[uuid.UUID] = []
    auto_create_rule: AutoCreateRule | None = None
    show_in_nav: bool = False
    sort_order: int = 0


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    icon: str | None = None
    default_tags: list[uuid.UUID] | None = None
    auto_create_rule: AutoCreateRule | None = None
    show_in_nav: bool | None = None
    sort_order: int | None = None


class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    name: str
    icon: str | None
    domain: CollectionDomain
    kind: str | None
    default_tags: list[uuid.UUID]
    auto_create_rule: AutoCreateRule | None
    show_in_nav: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    # Computed convenience field — the sidebar href for this collection
    @property
    def href(self) -> str:
        return f"/collections/{self.id}"


class CollectionListResponse(BaseModel):
    items: list[CollectionResponse]
    total: int


# ── Ensure-today response ─────────────────────────────────────────────────────

class EnsureTodayResponse(BaseModel):
    """Returned by POST /collections/{id}/ensure-today."""
    created: bool         # True if a new entry was created, False if it already existed
    item_id: uuid.UUID    # ID of today's entry (new or existing)
    item_domain: CollectionDomain
