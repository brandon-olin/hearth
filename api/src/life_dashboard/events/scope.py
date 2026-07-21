"""Scope filtering for events (realtime-001, webhook-001).

The Python mirror of core.visibility.apply_visibility_filter: that function
decides which *rows* a SELECT returns for a user; this decides which *events* may
be forwarded to that same user. The two must agree — an event is only delivered
if the underlying row would be visible — so a member never learns that an entity
they cannot see was created or changed.

**This is the single scope mechanism for every event kind.** The SSE stream
filters :class:`~life_dashboard.events.bus.InvalidationEvent` through it per
connection; the outbound-webhook worker filters
:class:`~life_dashboard.events.bus.SemanticEvent` through it per subscription,
against that subscription's owning member. ``can_see`` therefore types on the
visibility descriptor those two share (:class:`VisibilityDescriptor`) rather than
on either concrete class, so neither consumer needs — or is allowed — a filter of
its own. Any per-consumer filter added later (webhook event patterns, for
instance) runs strictly *after* this one: a filter narrows, it can never widen.

Kept as a pure function so it is trivially testable against the same cases as
the SQL filter.
"""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from life_dashboard.core.visibility import (
    VISIBILITY_HOUSEHOLD,
    VISIBILITY_MEMBERS,
    VISIBILITY_PERSONAL,
)


@runtime_checkable
class VisibilityDescriptor(Protocol):
    """The three fields that decide who may be told about something.

    Structural, not nominal: any event carrying these — an invalidation, a
    semantic event, or a future third kind — is filterable by ``can_see``
    without this module changing.
    """

    visibility: str
    created_by_user_id: uuid.UUID | None
    shared_with_user_ids: tuple[str, ...]


def can_see(event: VisibilityDescriptor, user_id: uuid.UUID) -> bool:
    """True if the member ``user_id`` may be told about ``event``.

    Household routing is assumed already handled by the caller — an SSE
    subscriber only receives events for its own household, and a webhook
    subscription is matched on household_id before this is reached — so this is
    purely the intra-household visibility decision:

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
