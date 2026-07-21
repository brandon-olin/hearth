"""Semantic event producer — named domain events on the commit-time plumbing.

webhook-001. The universal producer (events/emit.py) knows only that a row in a
household-scoped table changed; it deliberately discards *which* fields moved,
so a completion is indistinguishable from a title edit, and child tables with no
``household_id`` of their own (grocery_items, habit_occurrences) emit nothing at
all. Outbound webhooks need meaning, so domain service functions name the event
themselves by calling :func:`record` here.

The mechanism is deliberately the SAME one the invalidation producer uses rather
than a parallel path: a pending list on ``session.info``, published by the
existing ``after_commit`` listener and dropped by the existing rollback listener.
That inherits two proven guarantees for free —

  * nothing is published for a transaction that rolls back, and
  * a publish failure never breaks a write that already committed.

Child-table events pass the PARENT row as ``descriptor_from``: the service
function is the only layer that knows a grocery item's list or an occurrence's
habit, so it supplies the parent's ``household_id`` and the parent's visibility
descriptor. Scope is then decided by the one function every event kind goes
through, ``events.scope.can_see``.

Call this AFTER the row exists (``db.flush()`` so ``entity_id`` is real) and
BEFORE the commit that makes it durable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from life_dashboard.core.visibility import VISIBILITY_HOUSEHOLD
from life_dashboard.events.bus import SemanticEvent

#: Session.info key under which per-transaction pending semantic events
#: accumulate. Mirrors emit.py's ``_PENDING_KEY`` — same lifecycle, own list, so
#: neither producer can interfere with the other.
SEMANTIC_PENDING_KEY = "_semantic_pending_events"


def record(
    db: Any,
    *,
    event: str,
    entity_type: str,
    entity_id: uuid.UUID,
    summary: dict[str, Any],
    household_id: uuid.UUID | None = None,
    descriptor_from: Any = None,
    occurred_at: datetime | None = None,
) -> None:
    """Queue a semantic event for publication when this transaction commits.

    :param db: the ``AsyncSession`` (or sync ``Session``) the write is happening
        on — ``.info`` is shared with the commit listener either way.
    :param event: dotted catalog name, e.g. ``"todo.completed"``. Names outside
        the catalog in webhooks/summaries.py are published but delivered to
        nobody, so adding an event means adding it there too.
    :param entity_id: the id of the row the event is *about* — the child row for
        a child event, so a receiver can fetch exactly that entity back.
    :param summary: the domain's display digest. Filtered through the central
        allowlist before delivery; anything not listed there never leaves.
    :param household_id: required unless ``descriptor_from`` carries one.
    :param descriptor_from: a mapped row whose visibility descriptor (and
        ``household_id``, when not given explicitly) this event inherits. For a
        child event this is the PARENT row — the grocery list, the habit.
    """
    visibility = VISIBILITY_HOUSEHOLD
    created_by_user_id: uuid.UUID | None = None
    shared: tuple[str, ...] = ()

    if descriptor_from is not None:
        if household_id is None:
            household_id = getattr(descriptor_from, "household_id", None)
        visibility = getattr(descriptor_from, "visibility", VISIBILITY_HOUSEHOLD)
        created_by_user_id = getattr(descriptor_from, "created_by_user_id", None)
        shared = tuple(
            str(u) for u in (getattr(descriptor_from, "shared_with_user_ids", None) or [])
        )

    if household_id is None:
        raise ValueError(
            f"semantic event {event!r} needs a household_id, either directly or "
            "via descriptor_from"
        )

    pending: list[SemanticEvent] = db.info.setdefault(SEMANTIC_PENDING_KEY, [])
    pending.append(
        SemanticEvent(
            household_id=household_id,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            summary=dict(summary),
            visibility=visibility,
            created_by_user_id=created_by_user_id,
            shared_with_user_ids=shared,
        )
    )
