"""Tests for the event bus + SSE invalidation stream (realtime-001).

Covers the five verification steps in feature_list.json:

  1. In-process asyncio bus keyed by household_id (fan-out + unsubscribe).
  2. Authenticated SSE endpoint streams events for the connected member only.
  3. Events are skinny (type + id + action, no payload/visibility) and scope-
     filtered per connection.
  4. A committed write publishes an event (the after_commit producer) — the
     signal the frontend turns into a React Query invalidation.
  5. A member never receives an event for data outside their scope.
"""
import asyncio
import json
import uuid

import pytest

from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.visibility import (
    VISIBILITY_HOUSEHOLD,
    VISIBILITY_MEMBERS,
    VISIBILITY_PERSONAL,
)
from life_dashboard.domains.tags.models import Tag
from life_dashboard.events.bus import RESYNC, EventBus, InvalidationEvent, bus
from life_dashboard.events.scope import can_see

# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db, household=None, role=MembershipRole.member) -> User:
    if household is None:
        household = Household(name="Test Household")
        db.add(household)
        await db.flush()
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="x",
        display_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(HouseholdMembership(household_id=household.id, user_id=user.id, role=role))
    await db.commit()
    user.household_id = household.id
    user.role = role.value
    return user


def _event(hid, **kw) -> InvalidationEvent:
    return InvalidationEvent(
        household_id=hid,
        entity_type=kw.get("entity_type", "todos"),
        entity_id=kw.get("entity_id", uuid.uuid4()),
        action=kw.get("action", "created"),
        visibility=kw.get("visibility", VISIBILITY_HOUSEHOLD),
        created_by_user_id=kw.get("created_by_user_id"),
        shared_with_user_ids=kw.get("shared_with_user_ids", ()),
    )


# ── Bus fan-out (step 1) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bus_fans_out_to_subscribers_of_that_household():
    b = EventBus()
    hid = uuid.uuid4()
    other = uuid.uuid4()
    q1 = b.subscribe(hid)
    q2 = b.subscribe(hid)
    q_other = b.subscribe(other)

    ev = _event(hid)
    b.publish(ev)

    assert q1.get_nowait() is ev
    assert q2.get_nowait() is ev
    # A subscriber on a different household hears nothing.
    assert q_other.empty()


@pytest.mark.asyncio
async def test_bus_unsubscribe_stops_delivery():
    b = EventBus()
    hid = uuid.uuid4()
    q = b.subscribe(hid)
    assert b.subscriber_count(hid) == 1
    b.unsubscribe(hid, q)
    assert b.subscriber_count(hid) == 0
    b.publish(_event(hid))
    assert q.empty()
    # Idempotent — double unsubscribe is harmless.
    b.unsubscribe(hid, q)


@pytest.mark.asyncio
async def test_bus_full_queue_gets_resync_sentinel():
    b = EventBus()
    hid = uuid.uuid4()
    q = b.subscribe(hid)
    # Fill the queue to capacity, then one more to overflow.
    for _ in range(q.maxsize):
        b.publish(_event(hid))
    b.publish(_event(hid))  # overflow → resync sentinel replaces the drop

    # Drain: the tail should contain the RESYNC sentinel.
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert RESYNC in items


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop():
    b = EventBus()
    b.publish(_event(uuid.uuid4()))  # must not raise


# ── Scope filter (steps 3 & 5) ─────────────────────────────────────────────────

def test_can_see_household_visible_to_everyone():
    hid, uid = uuid.uuid4(), uuid.uuid4()
    assert can_see(_event(hid, visibility=VISIBILITY_HOUSEHOLD), uid)


def test_can_see_personal_only_creator():
    hid, creator, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ev = _event(hid, visibility=VISIBILITY_PERSONAL, created_by_user_id=creator)
    assert can_see(ev, creator)
    assert not can_see(ev, other)


def test_can_see_members_creator_or_listed():
    hid, creator, listed, outsider = (uuid.uuid4() for _ in range(4))
    ev = _event(
        hid,
        visibility=VISIBILITY_MEMBERS,
        created_by_user_id=creator,
        shared_with_user_ids=(str(listed),),
    )
    assert can_see(ev, creator)
    assert can_see(ev, listed)
    assert not can_see(ev, outsider)


def test_can_see_unknown_visibility_denied():
    ev = _event(uuid.uuid4(), visibility="bogus", created_by_user_id=uuid.uuid4())
    assert not can_see(ev, uuid.uuid4())


# ── Skinny wire form (step 3) ──────────────────────────────────────────────────

def test_client_dict_is_skinny():
    ev = _event(
        uuid.uuid4(),
        entity_type="todos",
        action="updated",
        visibility=VISIBILITY_PERSONAL,
        created_by_user_id=uuid.uuid4(),
        shared_with_user_ids=("a", "b"),
    )
    d = ev.to_client_dict()
    assert d == {"type": "todos", "id": str(ev.entity_id), "action": "updated"}
    # No visibility descriptor or owner leaks to the client.
    assert "visibility" not in d
    assert "created_by_user_id" not in d
    assert "household_id" not in d
    assert "shared_with_user_ids" not in d


# ── after_commit producer (step 4) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_commit_publishes_invalidation(db_session):
    """A committed write to a household-scoped table publishes an event via the
    after_commit listener — no service code called the bus explicitly."""
    household = Household(name="H")
    db_session.add(household)
    await db_session.flush()

    q = bus.subscribe(household.id)
    try:
        tag = Tag(household_id=household.id, name="groceries")
        db_session.add(tag)
        await db_session.commit()

        ev = q.get_nowait()
        assert ev.entity_type == "tags"
        assert ev.entity_id == tag.id
        assert ev.action == "created"
        assert ev.visibility == VISIBILITY_HOUSEHOLD  # Tag has no VisibilityMixin
    finally:
        bus.unsubscribe(household.id, q)


@pytest.mark.asyncio
async def test_rollback_publishes_nothing(db_session):
    household = Household(name="H")
    db_session.add(household)
    await db_session.flush()

    q = bus.subscribe(household.id)
    try:
        db_session.add(Tag(household_id=household.id, name="rolled-back"))
        await db_session.flush()  # captured by after_flush…
        await db_session.rollback()  # …but discarded on rollback
        assert q.empty()
    finally:
        bus.unsubscribe(household.id, q)


@pytest.mark.asyncio
async def test_denylisted_and_non_household_tables_do_not_emit(db_session):
    """audit_log is denylisted; users has no household_id — neither emits."""
    from life_dashboard.events.emit import _describe

    class _Fake:
        __tablename__ = "audit_log"
        id = uuid.uuid4()
        household_id = uuid.uuid4()

    assert _describe(_Fake(), "created") is None

    class _NoHousehold:
        __tablename__ = "users"
        id = uuid.uuid4()

    assert _describe(_NoHousehold(), "created") is None


# ── SSE stream generator (steps 2, 3, 5) ───────────────────────────────────────
#
# The generator is driven directly rather than through httpx/ASGITransport: an
# infinite text/event-stream generator deadlocks ASGITransport (it buffers the
# whole body), so exercising _event_stream in-process is both deterministic and
# a truer unit of the consumer logic — subscription, scope filter, skinny frame.

class _FakeRequest:
    """Minimal Request stand-in — _event_stream only awaits is_disconnected()."""
    def __init__(self):
        self._disconnected = False

    async def is_disconnected(self) -> bool:
        return self._disconnected


class _FakeUser:
    def __init__(self, user_id, household_id):
        self.id = user_id
        self.household_id = household_id


async def _drain_frame(agen, timeout=2.0):
    """Pull SSE chunks from the generator until one carries an event frame.

    Skips comment/heartbeat chunks (': ...'). Returns (event_name, data)."""
    async def _read():
        while True:
            chunk = await agen.__anext__()
            # Heartbeats / the initial connect comment start with ':'.
            if chunk.startswith(":"):
                continue
            event_name = None
            data = None
            for line in chunk.split("\n"):
                if line.startswith("event:"):
                    event_name = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[len("data:"):].strip())
            if data is not None:
                return event_name, data
    return await asyncio.wait_for(_read(), timeout=timeout)


@pytest.mark.asyncio
async def test_sse_generator_delivers_visible_event_skinny():
    """Steps 2 + 3: the stream forwards a visible event as a skinny frame."""
    from life_dashboard.events.router import _event_stream

    hid, uid = uuid.uuid4(), uuid.uuid4()
    agen = _event_stream(_FakeRequest(), _FakeUser(uid, hid))

    # First chunk is the connect comment; subscription is now live.
    first = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert first.startswith(":")
    assert bus.subscriber_count(hid) == 1

    entity_id = uuid.uuid4()
    bus.publish(_event(hid, entity_type="todos", entity_id=entity_id, action="updated"))

    name, data = await _drain_frame(agen)
    assert name == "invalidate"
    assert data == {"type": "todos", "id": str(entity_id), "action": "updated"}

    await agen.aclose()  # runs the finally → unsubscribe
    assert bus.subscriber_count(hid) == 0


@pytest.mark.asyncio
async def test_sse_generator_scope_filters_other_members_personal_event():
    """Step 5: a personal item owned by member B never reaches member A's
    stream. Proven by publishing B's personal event then a household event and
    asserting A's first frame is the household one."""
    from life_dashboard.events.router import _event_stream

    hid, a_id, b_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    agen = _event_stream(_FakeRequest(), _FakeUser(a_id, hid))
    await agen.__anext__()  # connect comment; now subscribed

    # B's personal note (A must not see it) then a shared todo (A must see it).
    bus.publish(
        _event(hid, entity_type="notes", visibility=VISIBILITY_PERSONAL, created_by_user_id=b_id)
    )
    visible_id = uuid.uuid4()
    bus.publish(_event(hid, entity_type="todos", entity_id=visible_id))

    name, data = await _drain_frame(agen)
    assert name == "invalidate"
    assert data["type"] == "todos"
    assert data["id"] == str(visible_id)

    await agen.aclose()


@pytest.mark.asyncio
async def test_sse_generator_translates_resync_sentinel():
    from life_dashboard.events.router import _event_stream

    hid = uuid.uuid4()
    agen = _event_stream(_FakeRequest(), _FakeUser(uuid.uuid4(), hid))
    await agen.__anext__()

    bus.publish(_event(hid))  # a normal event first
    await _drain_frame(agen)
    # Inject the sentinel directly onto the connection's queue.
    list(bus._subscribers[hid])[0].put_nowait(RESYNC)
    name, data = await _drain_frame(agen)
    assert name == "resync"
    assert data == {}

    await agen.aclose()


@pytest.mark.asyncio
async def test_sse_generator_unsubscribes_if_closed_before_first_loop():
    """Regression: a teardown while suspended at the initial connect comment —
    before the loop ever runs — must still unsubscribe (no leaked subscriber).
    This is the exact race the frontend's AbortController hits on unmount."""
    from life_dashboard.events.router import _event_stream

    hid = uuid.uuid4()
    agen = _event_stream(_FakeRequest(), _FakeUser(uuid.uuid4(), hid))
    await agen.__anext__()  # suspended right after ": connected", loop not entered
    assert bus.subscriber_count(hid) == 1
    await agen.aclose()  # close at that suspension point
    assert bus.subscriber_count(hid) == 0


@pytest.mark.asyncio
async def test_still_a_member_reflects_membership(db_session):
    """The periodic re-auth check sees a member, then sees them gone once their
    household membership is removed mid-stream."""
    from sqlalchemy import delete

    from life_dashboard.events.router import _still_a_member

    user = await _make_user(db_session)
    assert await _still_a_member(db_session, user.household_id, user.id) is True

    await db_session.execute(
        delete(HouseholdMembership).where(HouseholdMembership.user_id == user.id)
    )
    await db_session.commit()
    assert await _still_a_member(db_session, user.household_id, user.id) is False


@pytest.mark.asyncio
async def test_sse_requires_auth(db_session):
    """A non-streaming check that the endpoint is auth-gated: get_current_user
    raises 401 before any streaming begins (safe to call without httpx stream)."""
    from fastapi import HTTPException

    from life_dashboard.auth.dependencies import get_current_user

    class _NoAuthURL:
        path = "/realtime/stream"

    class _NoAuthRequest:
        method = "GET"
        url = _NoAuthURL()
        headers: dict = {}

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_NoAuthRequest(), db_session)
    assert exc.value.status_code == 401
