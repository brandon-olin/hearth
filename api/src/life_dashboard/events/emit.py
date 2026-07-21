"""Universal producer: publish an invalidation event on every committed change.

realtime-001. Instead of asking each domain service to remember to call the bus,
a single pair of SQLAlchemy listeners does it for all of them:

  after_flush  — capture the household-scoped rows touched by this flush, as
                 plain descriptors (read while the objects are still live).
  after_commit — publish those descriptors, once the transaction is durable.

Capturing in ``after_flush`` and publishing in ``after_commit`` is deliberate:
it guarantees we never emit an event for a change that then rolls back, and it
avoids touching (possibly expired) ORM attributes after commit.

Only tables that carry a ``household_id`` column emit events — that is the
marker of a household-scoped domain entity. A small deny-set removes internal
bookkeeping tables (audit log, etc.) that a UI never caches.

Coverage caveat: child tables scoped only through a parent (e.g. grocery_items,
habit_occurrences, taggings) have no ``household_id`` of their own and so do not
emit directly. In practice their parent row is usually touched in the same
transaction (and does emit); where a child-only write must invalidate a parent
view, the follow-up is either to add the parent to that write or to publish an
explicit event for it. The universal producer here intentionally stays
zero-configuration for the 25 household-scoped parent tables.

Semantic events (webhook-001) ride the same two listeners: domain services queue
them on ``session.info`` under their own key (events/semantic.py) and they are
published here, alongside the invalidations, once the transaction is durable.
This file owns the *timing* for both kinds; nothing about the invalidation
producer changes.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session

from life_dashboard.events.bus import InvalidationEvent, SemanticEvent, bus
from life_dashboard.events.semantic import SEMANTIC_PENDING_KEY

logger = logging.getLogger(__name__)

#: Session.info key under which per-transaction pending descriptors accumulate.
_PENDING_KEY = "_realtime_pending_invalidations"

#: household_id-bearing tables that should NOT emit UI invalidations — internal
#: bookkeeping a client never renders or caches.
_DENYLIST_TABLES = frozenset({"audit_log"})


def _describe(obj, action: str) -> InvalidationEvent | None:
    """Build a skinny event descriptor from a mapped instance, or None if the
    object is not a household-scoped domain entity we should broadcast.

    Reads only already-loaded attributes (safe inside after_flush)."""
    table = getattr(obj, "__tablename__", None)
    if table is None or table in _DENYLIST_TABLES:
        return None

    household_id = getattr(obj, "household_id", None)
    entity_id = getattr(obj, "id", None)
    if household_id is None or entity_id is None:
        return None

    shared = getattr(obj, "shared_with_user_ids", None) or []
    return InvalidationEvent(
        household_id=household_id,
        entity_type=table,
        entity_id=entity_id,
        action=action,
        visibility=getattr(obj, "visibility", "household"),
        created_by_user_id=getattr(obj, "created_by_user_id", None),
        # Freeze to a tuple of strings so the event stays hashable/immutable and
        # matches how can_see compares membership.
        shared_with_user_ids=tuple(str(u) for u in shared),
    )


@event.listens_for(Session, "after_flush")
def _capture_changes(session: Session, flush_context) -> None:
    """Record household-scoped inserts/updates/deletes from this flush.

    A transaction can flush several times; descriptors accumulate and are
    de-duplicated at publish time (last action per entity wins)."""
    pending: list[InvalidationEvent] = session.info.setdefault(_PENDING_KEY, [])
    for obj in session.new:
        if (desc := _describe(obj, "created")) is not None:
            pending.append(desc)
    for obj in session.dirty:
        # session.dirty can include objects with no net change; over-emitting an
        # invalidation is harmless (the client just refetches), so we don't
        # gate on session.is_modified here.
        if (desc := _describe(obj, "updated")) is not None:
            pending.append(desc)
    for obj in session.deleted:
        if (desc := _describe(obj, "deleted")) is not None:
            pending.append(desc)


@event.listens_for(Session, "after_commit")
def _publish_changes(session: Session) -> None:
    """Publish everything captured during this transaction, now it is durable.

    Invalidations de-duplicate by (entity_type, entity_id) keeping the last
    action seen, so a create-then-update in one transaction emits a single
    event. Semantic events are NOT de-duplicated: each one is a distinct thing
    that happened, and a receiver dedupes on the delivery id instead.

    Never raises — publication is best-effort and must not break the committed
    write."""
    pending: list[InvalidationEvent] = session.info.pop(_PENDING_KEY, [])
    semantic: list[SemanticEvent] = session.info.pop(SEMANTIC_PENDING_KEY, [])

    deduped: dict[tuple[str, uuid.UUID], InvalidationEvent] = {}
    for ev in pending:
        deduped[(ev.entity_type, ev.entity_id)] = ev

    for ev in deduped.values():
        try:
            bus.publish(ev)
        except Exception:  # noqa: BLE001 — telemetry must never break a write
            logger.warning(
                "Failed to publish invalidation for %s/%s",
                ev.entity_type,
                ev.entity_id,
                exc_info=True,
            )

    for sev in semantic:
        try:
            bus.publish_semantic(sev)
        except Exception:  # noqa: BLE001 — telemetry must never break a write
            logger.warning(
                "Failed to publish semantic event %s for %s/%s",
                sev.event,
                sev.entity_type,
                sev.entity_id,
                exc_info=True,
            )


@event.listens_for(Session, "after_rollback")
@event.listens_for(Session, "after_soft_rollback")
def _discard_changes(session: Session, *args) -> None:
    """Drop captured descriptors on rollback — the changes never happened.

    Covers both kinds: a semantic event queued in a transaction that then rolls
    back must never reach a webhook receiver."""
    session.info.pop(_PENDING_KEY, None)
    session.info.pop(SEMANTIC_PENDING_KEY, None)
