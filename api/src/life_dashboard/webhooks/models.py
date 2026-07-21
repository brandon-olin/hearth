"""Outbound webhook subscriptions and their durable delivery queue (webhook-001)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
)
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.encryption import EncryptedText


class WebhookSubscription(Base):
    """A member-owned promise to POST household events to a URL.

    **Member-owned is the security model, not a detail.** A subscription
    delivers only what its owner is entitled to see under
    ``events.scope.can_see``, so a household-agent-owned subscription receives
    shared-scope events only and one member can never route another member's
    personal to-dos off-box. ``created_by_user_id`` is therefore NOT NULL and
    cascades on member deletion — an ownerless subscription has no defensible
    scope, so it must not be able to exist.

    The secret is **encrypted, not hashed**: it is needed in cleartext to sign
    each delivery. That means field encryption must actually be configured
    before a subscription can be created (see service.create_subscription),
    otherwise the secret would sit in the database in plaintext.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Encrypted at rest via FIELD_ENCRYPTION_KEY; returned to the creator exactly
    # once, at creation, and never readable through the API again.
    secret: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # e.g. ["todo.completed", "grocery.*"] — the entire filter surface in v1.
    event_patterns: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Consecutive failed delivery ATTEMPTS; reset to 0 by any 2xx. Crossing the
    # auto-disable threshold flips `active` off and fills `disabled_reason`.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Why the subscription is inactive: NULL when active or paused by a human;
    # set when the worker auto-disabled it, so the UI can say which it was.
    disabled_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Dispatch reads "the active subscriptions of this household" on every
        # semantic event; the settings page reads the same rows without the
        # active filter.
        Index("ix_webhook_subscriptions_household_active", "household_id", "active"),
    )


class WebhookDelivery(Base):
    """One event queued for one subscription — the durable at-least-once queue.

    The row id IS the delivery id sent to the receiver (``X-Hearth-Delivery`` and
    ``delivery_id`` in the body), and it is stable across retries, so a receiver
    dedupes on it.

    ``payload`` stores the exact body dict that was built for this delivery
    (already filtered through the central allowlist). Retries re-send those same
    bytes rather than re-deriving them from a row that may have changed since —
    a webhook reports what happened *then*.

    Attempts live here and ONLY here. They are machine-generated, high-volume,
    and prunable; ``audit_log`` records subscription lifecycle instead (created /
    paused / resumed / deleted / auto-disabled), because those are the
    human-initiated decisions about where household data may egress.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )

    event: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Plain string, no FK — a delivery record outlives the entity it describes.
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # "pending" | "delivered" | "failed"
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The worker's only hot query: "pending rows whose next_attempt_at is due".
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
        # The per-subscription delivery log (webhook-002 UI) and pruning.
        Index("ix_webhook_deliveries_subscription_created", "subscription_id", "created_at"),
    )
