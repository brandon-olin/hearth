"""In-process asyncio pub/sub keyed by household_id (realtime-001).

Subscribers (one per live SSE connection) get their own bounded queue. Producers
publish an :class:`InvalidationEvent`; the bus fans it out to every subscriber
for that household. Publishing is synchronous and non-blocking (``put_nowait``)
so it is safe to call from a SQLAlchemy ``after_commit`` handler running in the
event-loop thread — no ``await``, no loop scheduling.

Swap target: a Postgres LISTEN/NOTIFY-backed bus would keep this exact
publish/subscribe surface, so neither producers nor the SSE consumer change.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Per-subscriber queue depth. An SSE consumer drains this continuously; the cap
#: only bites if a client stalls. At that point we drop events for that one
#: connection and flag it (see EventBus.publish) rather than growing without
#: bound. A household will not realistically fill 512 pending invalidations.
_QUEUE_MAXSIZE = 512


@dataclass(frozen=True)
class InvalidationEvent:
    """A skinny 'something changed' signal.

    The wire form sent to clients is only ``entity_type`` + ``entity_id`` +
    ``action`` (see :meth:`to_client_dict`). The remaining fields are the
    server-side visibility descriptor used to decide, per connection, whether
    the event may be forwarded at all — they are never serialised to a client.
    """

    household_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str  # "created" | "updated" | "deleted"

    # ── Visibility descriptor (server-side only; never sent to a client) ──────
    visibility: str = "household"  # "household" | "personal" | "members"
    created_by_user_id: uuid.UUID | None = None
    shared_with_user_ids: tuple[str, ...] = ()

    def to_client_dict(self) -> dict:
        """The skinny payload a client receives — type + id + action, nothing
        that would leak a field value or the item's visibility descriptor."""
        return {
            "type": self.entity_type,
            "id": str(self.entity_id),
            "action": self.action,
        }


class EventBus:
    """Fan-out registry of household_id → set of subscriber queues."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}

    def subscribe(self, household_id: uuid.UUID) -> asyncio.Queue:
        """Register a new subscriber for a household and return its queue.

        Called from within the SSE endpoint (inside the request's event loop),
        so the queue binds to that loop. Always pair with :meth:`unsubscribe`
        in a finally block."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.setdefault(household_id, set()).add(queue)
        return queue

    def unsubscribe(self, household_id: uuid.UUID, queue: asyncio.Queue) -> None:
        """Remove a subscriber. Idempotent — a double call is harmless."""
        subs = self._subscribers.get(household_id)
        if not subs:
            return
        subs.discard(queue)
        if not subs:
            del self._subscribers[household_id]

    def subscriber_count(self, household_id: uuid.UUID) -> int:
        """Live subscriber count for a household — used by tests and metrics."""
        return len(self._subscribers.get(household_id, ()))

    def publish(self, event: InvalidationEvent) -> None:
        """Fan an event out to every subscriber of its household.

        Non-blocking: if a subscriber's queue is full (a stalled client), the
        event is dropped for that connection and a resync sentinel is pushed
        instead so the client invalidates broadly on recovery rather than
        silently missing the change. Never raises — a publish failure must not
        break the write that triggered it."""
        subs = self._subscribers.get(event.household_id)
        if not subs:
            return
        for queue in list(subs):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # The connection is stalled. Discard the oldest queued item to
                # make room for a resync sentinel — the client will refetch
                # broadly on recovery, which subsumes whatever we dropped. This
                # guarantees the sentinel lands rather than being dropped too.
                logger.warning(
                    "Invalidation queue full for household=%s — sending resync",
                    event.household_id,
                )
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(RESYNC)
                except asyncio.QueueFull:
                    pass


#: Sentinel meaning "you may have missed events — invalidate everything". The
#: SSE endpoint translates it into a client `resync` event.
RESYNC = object()


#: Process-wide singleton. One bus per API process (per worker on multi-worker
#: cloud deployments — acceptable because subscribers connect to the worker
#: holding their SSE connection, and every worker runs the same commit listener).
bus = EventBus()
