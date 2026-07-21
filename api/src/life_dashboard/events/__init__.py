"""Internal event bus, invalidation stream, and semantic events (realtime-001,
webhook-001).

An in-process asyncio pub/sub. Two kinds of event travel over it:

* **Invalidations** — keyed by ``household_id``, consumed by a Server-Sent-Events
  stream that pushes *skinny* signals (``entity_type`` + ``id`` only, never row
  payloads) to connected clients, scope-filtered per connection so a member never
  learns about data they cannot see. The frontend maps each to a React Query
  cache invalidation so other devices refetch.
* **Semantic events** — named domain facts ("todo.completed"), consumed by the
  outbound-webhook delivery worker (webhooks/).

Producers for invalidations are wired once, centrally: a SQLAlchemy
``after_commit`` listener (events/emit.py) publishes an event for every committed
change to a household-scoped table, so no domain service has to remember to call
the bus. Semantic events are named explicitly by domain services (events/
semantic.py) but ride that same commit-time listener.

The bus is deliberately swappable to Postgres LISTEN/NOTIFY later without
changing producers or consumers — publish/subscribe is the only contract.
Cross-cutting decision recorded in plans/open-hearth.md (track 4 / event bus).

Importing this package installs the commit listener as a side effect (see
``events.emit``), so ``import life_dashboard.events`` in the app factory is what
turns producers on.
"""
from life_dashboard.events import (  # noqa: F401  (emit registers the commit listener)
    emit,
    semantic,
)
from life_dashboard.events.bus import InvalidationEvent, SemanticEvent, bus

__all__ = ["bus", "InvalidationEvent", "SemanticEvent", "semantic"]
