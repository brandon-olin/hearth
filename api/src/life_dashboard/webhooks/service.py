"""Subscription management and event → delivery-row dispatch (webhook-001).

Two responsibilities, both of them the parts that decide what leaves the house:

* **Subscription lifecycle** — create / list / update / delete, each writing one
  ``audit_log`` row, because deciding where household data may egress is a
  human decision worth recording. Delivery *attempts* are not audited here; they
  live in ``webhook_deliveries`` (see models.py for why).

* **Dispatch** — turning one :class:`SemanticEvent` into zero or more queued
  deliveries. The order of the two filters is load-bearing:

      1. ``events.scope.can_see`` against the subscription's OWNER — the single
         scope mechanism, shared with the SSE stream.
      2. the subscription's ``event_patterns``.

  Scope first, always. A pattern narrows what the owner may already see; it can
  never widen it.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.audit import service as audit
from life_dashboard.audit.schemas import AuditSource
from life_dashboard.core.encryption import encryption_enabled
from life_dashboard.events.bus import SemanticEvent
from life_dashboard.events.scope import can_see
from life_dashboard.webhooks import ssrf, summaries
from life_dashboard.webhooks.models import WebhookDelivery, WebhookSubscription
from life_dashboard.webhooks.schemas import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionListResponse,
    WebhookSubscriptionResponse,
    WebhookSubscriptionUpdate,
)

logger = logging.getLogger(__name__)

#: Bytes of entropy in a generated signing secret (URL-safe base64 → ~43 chars).
_SECRET_BYTES = 32


class WebhookEncryptionUnavailable(RuntimeError):
    """FIELD_ENCRYPTION_KEY is not configured, so a secret cannot be stored safely."""


class DuplicateWebhookTarget(ValueError):
    """An active subscription for this household already posts to this URL."""


def _require_encryption() -> None:
    """Refuse to create a subscription when the secret would land in plaintext.

    The signing secret cannot be hashed — it is needed in cleartext to sign every
    delivery — so encryption at rest is the only protection it has. Failing loudly
    here is deliberate: silently storing a plaintext shared secret is exactly the
    kind of thing nobody notices until it matters.
    """
    if not encryption_enabled():
        raise WebhookEncryptionUnavailable(
            "FIELD_ENCRYPTION_KEY is not set, so a webhook signing secret would be "
            "stored in plaintext. Generate one with: python -c \"from "
            "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and set it in the API environment, then try again."
        )


# ── Subscription lifecycle ────────────────────────────────────────────────────

async def create_subscription(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WebhookSubscriptionCreate,
) -> WebhookSubscriptionCreated:
    """Create a subscription owned by ``user_id`` and return its secret once.

    Raises ``WebhookEncryptionUnavailable`` if field encryption is off,
    ``ValueError`` for an unusable event pattern,
    ``ssrf.WebhookTargetRejected`` if this tier forbids the target, and
    ``DuplicateWebhookTarget`` if an active subscription already posts there.
    """
    _require_encryption()
    patterns = summaries.validate_patterns(data.event_patterns)
    url = data.url.strip()
    await ssrf.assert_target_allowed(url)

    # A double-submitted create would otherwise leave a permanent duplicate
    # egress channel, silently doubling every future delivery to that receiver.
    # One subscription can carry many patterns, so a second one to the same URL
    # is almost always an accident rather than an intent.
    duplicate = (await db.execute(
        select(WebhookSubscription.id).where(
            WebhookSubscription.household_id == household_id,
            WebhookSubscription.url == url,
            WebhookSubscription.active.is_(True),
        )
    )).scalar_one_or_none()
    if duplicate is not None:
        raise DuplicateWebhookTarget(
            f"An active webhook already posts to {url}. Edit that subscription's events "
            "instead, or delete it first — its signing secret cannot be shown again."
        )

    secret = secrets.token_urlsafe(_SECRET_BYTES)
    sub = WebhookSubscription(
        household_id=household_id,
        created_by_user_id=user_id,
        description=data.description,
        url=url,
        secret=secret,
        event_patterns=patterns,
        active=True,
    )
    db.add(sub)
    await db.flush()

    await audit.record(
        db,
        household_id=household_id,
        actor_user_id=user_id,
        source=AuditSource.web,
        action="webhook_subscription_created",
        entity_type="webhook_subscription",
        entity_id=sub.id,
        payload={"url": sub.url, "event_patterns": patterns},
    )

    await db.commit()
    await db.refresh(sub)
    return WebhookSubscriptionCreated(
        **WebhookSubscriptionResponse.model_validate(sub).model_dump(), secret=secret
    )


async def list_subscriptions(
    db: AsyncSession, household_id: uuid.UUID
) -> WebhookSubscriptionListResponse:
    """Every subscription in the household, newest first.

    Household-wide rather than owner-filtered on purpose: where household data
    egresses is something members should be able to see, even if only the owner's
    scope decides what each one actually receives."""
    rows = list((await db.execute(
        select(WebhookSubscription)
        .where(WebhookSubscription.household_id == household_id)
        .order_by(WebhookSubscription.created_at.desc())
    )).scalars().all())
    total = (await db.execute(
        select(func.count()).select_from(WebhookSubscription)
        .where(WebhookSubscription.household_id == household_id)
    )).scalar_one()
    return WebhookSubscriptionListResponse(
        items=[WebhookSubscriptionResponse.model_validate(r) for r in rows], total=total
    )


async def update_subscription(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WebhookSubscriptionUpdate,
) -> WebhookSubscriptionResponse | None:
    """Pause, resume, relabel, or re-target the patterns of a subscription.

    Returns None if it does not exist in this household (→ 404). Re-activating
    clears the failure counter and the auto-disable reason, so a fixed receiver
    starts from a clean slate rather than being disabled again immediately.

    Household-wide, like listing: any member may pause or retarget any of the
    household's webhooks. Stopping egress is never a privilege escalation, and a
    member who can see where household data flows should be able to stop it.
    """
    sub = (await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.household_id == household_id,
        )
    )).scalar_one_or_none()
    if sub is None:
        return None

    was_active = sub.active

    if data.event_patterns is not None:
        sub.event_patterns = summaries.validate_patterns(data.event_patterns)
    if data.description is not None:
        sub.description = data.description
    if data.active is not None and data.active != sub.active:
        sub.active = data.active
        if data.active:
            sub.consecutive_failures = 0
            sub.disabled_reason = None
    sub.updated_at = datetime.now(timezone.utc)

    if data.active is not None and data.active != was_active:
        await audit.record(
            db,
            household_id=household_id,
            actor_user_id=user_id,
            source=AuditSource.web,
            action="webhook_subscription_resumed" if data.active else "webhook_subscription_paused",
            entity_type="webhook_subscription",
            entity_id=sub.id,
            payload={"url": sub.url},
        )

    await db.commit()
    await db.refresh(sub)
    return WebhookSubscriptionResponse.model_validate(sub)


async def delete_subscription(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Delete a subscription and every delivery queued for it.

    The queued rows are removed explicitly rather than left to the FK cascade:
    SQLite does not enforce ``ON DELETE CASCADE`` unless ``PRAGMA foreign_keys``
    is on, and "delete the subscription" must mean the same thing on the desktop
    tier as it does on Postgres — no pending egress survives it."""
    sub = (await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.household_id == household_id,
        )
    )).scalar_one_or_none()
    if sub is None:
        return False

    await audit.record(
        db,
        household_id=household_id,
        actor_user_id=user_id,
        source=AuditSource.web,
        action="webhook_subscription_deleted",
        entity_type="webhook_subscription",
        entity_id=sub.id,
        payload={"url": sub.url},
    )
    await db.execute(
        sa_delete(WebhookDelivery).where(WebhookDelivery.subscription_id == sub.id)
    )
    await db.delete(sub)
    await db.commit()
    return True


#: Storage width of webhook_subscriptions.disabled_reason. The reason embeds the
#: last delivery error, which can be long (an SSRF rejection names the host and
#: the resolved address), so it is truncated here rather than raising a DataError
#: on Postgres at exactly the moment we are trying to record a failure.
_DISABLED_REASON_MAX = 200


async def record_auto_disable(
    db: AsyncSession, sub: WebhookSubscription, reason: str
) -> None:
    """Flip a failing subscription off and audit it.

    Auto-disable is a change to where household data egresses — the same class of
    fact as a human pausing it — so it earns an audit row. The caller owns the
    commit."""
    if len(reason) > _DISABLED_REASON_MAX:
        reason = reason[: _DISABLED_REASON_MAX - 1] + "…"
    sub.active = False
    sub.disabled_reason = reason
    sub.updated_at = datetime.now(timezone.utc)
    await audit.record(
        db,
        household_id=sub.household_id,
        actor_user_id=None,
        source=AuditSource.system,
        action="webhook_subscription_auto_disabled",
        entity_type="webhook_subscription",
        entity_id=sub.id,
        payload={"url": sub.url, "reason": reason},
    )


# ── Dispatch ──────────────────────────────────────────────────────────────────

def build_payload(event: SemanticEvent, delivery_id: uuid.UUID) -> dict:
    """The skinny wire body for one delivery.

    ``summary`` has already passed the central allowlist by the time it lands
    here. ``delivery_id`` is stable across retries so a receiver can dedupe.
    """
    return {
        "delivery_id": str(delivery_id),
        "event": event.event,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id),
        "household_id": str(event.household_id),
        "occurred_at": event.occurred_at.isoformat(),
        "summary": summaries.filter_summary(event.event, event.summary),
    }


async def dispatch_event(db: AsyncSession, event: SemanticEvent) -> list[WebhookDelivery]:
    """Queue a delivery row for every subscription entitled to this event.

    Not committed by this function's caller by accident — it commits itself, so a
    queued delivery is durable the moment dispatch returns. Returns the rows it
    created (empty list when nothing matched, which is the common case).
    """
    if not summaries.is_known_event(event.event):
        # An event no allowlist entry covers would deliver an empty summary to
        # everyone matching '*'. Refuse instead, and say so loudly enough to fix.
        logger.warning(
            "Semantic event %r is not in the webhook catalog — not dispatched. "
            "Add it to webhooks/summaries.py to make it deliverable.",
            event.event,
        )
        return []

    subs = list((await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.household_id == event.household_id,
            WebhookSubscription.active.is_(True),
        )
    )).scalars().all())
    if not subs:
        return []

    created: list[WebhookDelivery] = []
    now = datetime.now(timezone.utc)
    for sub in subs:
        # 1. Scope — the single mechanism, against the subscription's owner.
        if not can_see(event, sub.created_by_user_id):
            continue
        # 2. Pattern — narrows what that owner may already see. Never widens.
        if not summaries.matches_patterns(sub.event_patterns, event.event):
            continue

        delivery_id = uuid.uuid4()
        delivery = WebhookDelivery(
            id=delivery_id,
            subscription_id=sub.id,
            household_id=event.household_id,
            event=event.event,
            entity_type=event.entity_type,
            entity_id=str(event.entity_id),
            payload=build_payload(event, delivery_id),
            status="pending",
            attempt_count=0,
            next_attempt_at=now,
        )
        db.add(delivery)
        created.append(delivery)

    if created:
        await db.commit()
        for delivery in created:
            await db.refresh(delivery)
    return created
