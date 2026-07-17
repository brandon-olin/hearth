"""Per-connection scope filtering for invalidation events (realtime-001).

The Python mirror of core.visibility.apply_visibility_filter: that function
decides which *rows* a SELECT returns for a user; this decides which
*invalidation events* an SSE connection may forward to that same user. The two
must agree — an event is only delivered if the underlying row would be visible —
so a member never learns that an entity they cannot see was created or changed.

Kept as a pure function so it is trivially testable against the same cases as
the SQL filter.
"""
from __future__ import annotations

import uuid

from life_dashboard.core.visibility import (
    VISIBILITY_HOUSEHOLD,
    VISIBILITY_MEMBERS,
    VISIBILITY_PERSONAL,
)
from life_dashboard.events.bus import InvalidationEvent


def can_see(event: InvalidationEvent, user_id: uuid.UUID) -> bool:
    """True if the member ``user_id`` may be told about ``event``.

    Household routing is assumed already handled by the bus (a subscriber only
    receives events for its own household), so this is purely the intra-
    household visibility decision:

      household → every member
      personal  → the creator only
      members   → the creator, or a member listed in shared_with_user_ids

    Unknown/legacy visibility values fall through to False (deny) rather than
    leaking — the same conservative default the app applies elsewhere.
    """
    if event.visibility == VISIBILITY_HOUSEHOLD:
        return True

    if event.visibility == VISIBILITY_PERSONAL:
        return event.created_by_user_id == user_id

    if event.visibility == VISIBILITY_MEMBERS:
        if event.created_by_user_id == user_id:
            return True
        return str(user_id) in event.shared_with_user_ids

    return False
