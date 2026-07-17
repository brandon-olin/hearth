"""Internal event bus + real-time invalidation stream (realtime-001).

An in-process asyncio pub/sub keyed by ``household_id``. The first (and so far
only) consumer is a Server-Sent-Events stream that pushes *skinny* invalidation
events — ``entity_type`` + ``id`` only, never row payloads — to connected
clients, scope-filtered per connection so a member never learns about data they
cannot see. The frontend maps each event to a React Query cache invalidation so
other devices refetch.

Producers are wired once, centrally: a SQLAlchemy ``after_commit`` listener
(events/emit.py) publishes an event for every committed change to a
household-scoped table, so no domain service has to remember to call the bus.

The bus is deliberately swappable to Postgres LISTEN/NOTIFY later without
changing producers or consumers — publish/subscribe is the only contract.
Cross-cutting decision recorded in plans/open-hearth.md (track 4 / event bus).

Importing this package installs the commit listener as a side effect (see
``events.emit``), so ``import life_dashboard.events`` in the app factory is what
turns producers on.
"""
from life_dashboard.events import emit  # noqa: F401  (registers the commit listener)
from life_dashboard.events.bus import InvalidationEvent, bus

__all__ = ["bus", "InvalidationEvent"]
