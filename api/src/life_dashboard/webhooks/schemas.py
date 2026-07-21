"""Request/response schemas for webhook subscription management (webhook-001)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WebhookSubscriptionCreate(BaseModel):
    """Create a subscription. The secret is generated server-side and shown once."""

    url: str = Field(..., description="Absolute http(s) URL to POST events to.")
    event_patterns: list[str] = Field(
        ...,
        description=(
            "Event names or wildcards to deliver, e.g. ['todo.completed', 'grocery.*']. "
            "GET /webhooks/events lists the catalog."
        ),
    )
    description: str | None = Field(
        default=None, max_length=200, description="Optional label shown in settings."
    )


class WebhookSubscriptionUpdate(BaseModel):
    """Partial update. Setting ``active`` re-enables an auto-disabled subscription."""

    active: bool | None = None
    event_patterns: list[str] | None = None
    description: str | None = Field(default=None, max_length=200)


class WebhookSubscriptionResponse(BaseModel):
    """A subscription as read back. The secret is never included."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID
    description: str | None
    url: str
    event_patterns: list[str]
    active: bool
    consecutive_failures: int
    disabled_reason: str | None
    last_delivery_at: datetime | None
    created_at: datetime


class WebhookSubscriptionCreated(WebhookSubscriptionResponse):
    """The create response — the ONLY time the signing secret is returned."""

    secret: str


class WebhookSubscriptionListResponse(BaseModel):
    items: list[WebhookSubscriptionResponse]
    total: int


class WebhookEventInfo(BaseModel):
    """One entry of the deliverable event catalog."""

    event: str
    description: str
    summary_fields: list[str]


class WebhookEventCatalogResponse(BaseModel):
    items: list[WebhookEventInfo]
