"""The approval queue, its realtime events, and the agent status tools (proposal-002).

proposal-001 proved a proposal gets *recorded*. This suite is about everyone who
has to hear about it afterwards: the admins who decide it, the second admin who
arrives late, the member who asked, the webhook receiver, and the agent that has
to tell its user what happened.

The load-bearing assertions are again about what did NOT happen — the member who
is neither an admin nor the proposer never learns a proposal exists, household B
never hears household A's queue, and a second approve executes no second write.

The router functions are called directly with a stub member rather than over
HTTP: the gate being tested lives in the router and service, and the HTTP layer
in between adds nothing but a serialisation round trip. The one thing HTTP *does*
decide — that a PAT cannot reach these routes at all — is asserted against the
path-mapping table that actually enforces it.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.mcp.server as mcp_server_module
from life_dashboard.audit.models import AuditLog
from life_dashboard.auth.models import (
    Household,
    HouseholdMembership,
    MembershipRole,
    User,
)
from life_dashboard.auth.pat_scopes import resolve_required_scope
from life_dashboard.auth.pat_service import create_token
from life_dashboard.core.database import Base
from life_dashboard.domains.todos.models import Todo
from life_dashboard.events.bus import SemanticEvent, bus
from life_dashboard.events.scope import can_see
from life_dashboard.mcp.auth import MCPAuthError
from life_dashboard.mcp.pseudo_member import get_or_create_household_agent
from life_dashboard.mcp.server import (
    add_todo,
    get_proposal_status,
    list_my_proposals,
    mcp_server,
)
from life_dashboard.proposals import events as proposal_events
from life_dashboard.proposals import router as proposals_router
from life_dashboard.proposals import service as proposals_service
from life_dashboard.proposals.models import Proposal
from life_dashboard.proposals.schemas import ProposalStatus
from life_dashboard.voice import schemas as voice_schemas
from life_dashboard.voice import service as voice_service
from life_dashboard.webhooks import service as webhooks_service
from life_dashboard.webhooks import summaries
from life_dashboard.webhooks.models import WebhookSubscription

#: Same household config proposal-001 uses: todos may be created from member rank
#: up, and viewers may ask. This is the shape the whole feature exists to serve.
PROPOSE_CONFIG = {"todos": {"read": "viewer", "create": "member", "propose": "viewer"}}


class _FakeCtx:
    """Minimal stand-in for FastMCP's Context (see test_proposals.py)."""

    def __init__(self, raw_token: str | None):
        headers = {"authorization": f"Bearer {raw_token}"} if raw_token else {}
        request = type("Req", (), {"headers": headers})()
        self.request_context = type("RC", (), {"request": request})()


class _Member:
    """What ``get_current_user`` hands a router: a user plus the three runtime
    attributes the auth dependency attaches (household_id, household_name, role)."""

    def __init__(self, user_id, household_id, role):
        self.id = user_id
        self.household_id = household_id
        self.role = role


@pytest_asyncio.fixture
async def env(monkeypatch):
    """Two households, so every scope assertion has a real other side.

    Household A: Alice (owner), Bob (admin) — both approvers; Dana (member) — an
    ordinary member who proposes nothing; Kid (viewer) — may only ask; and the
    household-agent pseudo-member behind the kitchen speaker.
    Household B: Carol (owner), with her own agent.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mcp_server_module, "AsyncSessionLocal", maker)

    async with maker() as db:
        a = Household(name="The Olins", permissions_config=PROPOSE_CONFIG)
        b = Household(name="The Neighbours", permissions_config=PROPOSE_CONFIG)
        db.add_all([a, b])
        await db.flush()

        people = {}
        for key, email, name in [
            ("alice", "a@x.com", "Alice"),
            ("bob", "b@x.com", "Bob"),
            ("dana", "d@x.com", "Dana"),
            ("kid", "k@x.com", "Kid"),
            ("carol", "c@x.com", "Carol"),
        ]:
            u = User(email=email, password_hash="x", display_name=name, is_active=True)
            db.add(u)
            people[key] = u
        await db.flush()

        db.add_all([
            HouseholdMembership(household_id=a.id, user_id=people["alice"].id,
                                role=MembershipRole.owner),
            HouseholdMembership(household_id=a.id, user_id=people["bob"].id,
                                role=MembershipRole.admin),
            HouseholdMembership(household_id=a.id, user_id=people["dana"].id,
                                role=MembershipRole.member),
            HouseholdMembership(household_id=a.id, user_id=people["kid"].id,
                                role=MembershipRole.viewer),
            HouseholdMembership(household_id=b.id, user_id=people["carol"].id,
                                role=MembershipRole.owner),
        ])
        await db.commit()

        agent_a = await get_or_create_household_agent(db, a.id)
        agent_b = await get_or_create_household_agent(db, b.id)

        _, raw_kid = await create_token(db, people["kid"].id, "Kid phone",
                                        {"todos": "write"}, None)
        _, raw_agent_a = await create_token(db, agent_a.id, "Kitchen speaker",
                                            {"todos": "write"}, None)
        _, raw_agent_b = await create_token(db, agent_b.id, "Their speaker",
                                            {"todos": "write"}, None)
        _, raw_alice_write = await create_token(db, people["alice"].id, "Alice laptop",
                                                {"todos": "write"}, None)

        ids = {k: v.id for k, v in people.items()}

    yield {
        "maker": maker,
        "household_a": a.id,
        "household_b": b.id,
        "agent_a": agent_a.id,
        "raw_kid": raw_kid,
        "raw_agent_a": raw_agent_a,
        "raw_agent_b": raw_agent_b,
        "raw_alice_write": raw_alice_write,
        **ids,
    }
    await engine.dispose()


def _alice(env):
    return _Member(env["alice"], env["household_a"], "owner")


def _bob(env):
    return _Member(env["bob"], env["household_a"], "admin")


def _dana(env):
    return _Member(env["dana"], env["household_a"], "member")


def _kid(env):
    return _Member(env["kid"], env["household_a"], "viewer")


def _carol(env):
    return _Member(env["carol"], env["household_b"], "owner")


async def _propose(raw_token: str, title: str) -> dict:
    """Make one proposal through the real MCP write tool."""
    result = await add_todo(_FakeCtx(raw_token), title=title)
    assert result["status"] == "proposed", result
    return result


async def _queue(env, member, **kw):
    async with env["maker"]() as db:
        return await proposals_router.list_proposals(
            db=db, current_user=member, **{"status": None, "limit": 50, "offset": 0, **kw}
        )


async def _todo_count(env, title: str) -> int:
    async with env["maker"]() as db:
        return (await db.execute(
            select(func.count()).select_from(Todo).where(Todo.title == title)
        )).scalar_one()


# ── The queue itself ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_queue_lists_pending_with_everything_a_decision_needs(env):
    await _propose(env["raw_kid"], "Take out the bins")

    page = await _queue(env, _alice(env), status="pending")

    assert page.total == 1
    row = page.items[0]
    assert row.summary == "Add to-do “Take out the bins”"
    assert row.domain == "todos"
    assert row.status == "pending"
    # Who asked, and from what — a row without this is not decidable.
    assert row.proposed_by_label == "Kid"
    assert row.proposed_via_label == "Kid phone"
    assert row.created_at is not None and row.expires_at is not None


@pytest.mark.asyncio
async def test_household_agent_proposal_is_labelled_by_its_device(env):
    """A shared speaker is not a person; the device IS its whole identity."""
    await _propose(env["raw_agent_a"], "Buy milk")

    row = (await _queue(env, _alice(env), status="pending")).items[0]
    assert row.proposed_by_user_id is None
    assert row.proposed_by_label == "Kitchen speaker"


@pytest.mark.asyncio
async def test_pending_count_is_the_widgets_number(env):
    await _propose(env["raw_kid"], "One")
    await _propose(env["raw_agent_a"], "Two")

    page = await _queue(env, _alice(env), status="pending", limit=1)
    assert page.total == 2
    assert len(page.items) == 1  # the widget fetches a count, not the whole queue


@pytest.mark.asyncio
async def test_approve_executes_the_underlying_write(env):
    proposed = await _propose(env["raw_kid"], "Take out the bins")
    assert await _todo_count(env, "Take out the bins") == 0

    async with env["maker"]() as db:
        decided = await proposals_router.approve_proposal(
            proposal_id=uuid.UUID(proposed["proposal_id"]), db=db, current_user=_alice(env)
        )

    assert decided.status == ProposalStatus.approved.value
    assert decided.decided_by_label == "Alice"
    assert await _todo_count(env, "Take out the bins") == 1


@pytest.mark.asyncio
async def test_reject_persists_the_reason_and_clears_the_pending_queue(env):
    proposed = await _propose(env["raw_kid"], "Buy a pony")

    async with env["maker"]() as db:
        decided = await proposals_router.reject_proposal(
            proposal_id=uuid.UUID(proposed["proposal_id"]),
            data=proposals_router.ProposalRejectRequest(reason="Not this month."),
            db=db,
            current_user=_alice(env),
        )

    assert decided.status == ProposalStatus.rejected.value
    assert decided.reject_reason == "Not this month."
    assert (await _queue(env, _alice(env), status="pending")).total == 0
    assert await _todo_count(env, "Buy a pony") == 0


@pytest.mark.asyncio
async def test_second_admin_sees_the_decision_not_a_stale_approve_button(env):
    """Routing is all-admins and first-to-decide wins, so the late arrival must
    read the decision — never a control that is guaranteed to 409."""
    proposed = await _propose(env["raw_kid"], "Take out the bins")
    pid = uuid.UUID(proposed["proposal_id"])

    async with env["maker"]() as db:
        await proposals_router.approve_proposal(
            proposal_id=pid, db=db, current_user=_alice(env)
        )

    # Bob opens the same proposal.
    async with env["maker"]() as db:
        seen = await proposals_router.get_proposal(
            proposal_id=pid, db=db, current_user=_bob(env)
        )
    assert seen.status == ProposalStatus.approved.value
    assert seen.decided_by_label == "Alice"

    # And if he had a stale button and pressed it anyway, he is told he was
    # second rather than executing the write again.
    async with env["maker"]() as db:
        with pytest.raises(HTTPException) as exc:
            await proposals_router.approve_proposal(
                proposal_id=pid, db=db, current_user=_bob(env)
            )
    assert exc.value.status_code == 409
    assert "already approved" in str(exc.value.detail)
    assert await _todo_count(env, "Take out the bins") == 1


@pytest.mark.asyncio
async def test_double_approve_executes_the_write_exactly_once(env):
    """The double-tap / retried-request case, which is the same race as two
    admins pressing approve at once."""
    proposed = await _propose(env["raw_kid"], "Take out the bins")
    pid = uuid.UUID(proposed["proposal_id"])

    async with env["maker"]() as db:
        await proposals_router.approve_proposal(
            proposal_id=pid, db=db, current_user=_alice(env)
        )
    async with env["maker"]() as db:
        with pytest.raises(HTTPException):
            await proposals_router.approve_proposal(
                proposal_id=pid, db=db, current_user=_alice(env)
            )

    assert await _todo_count(env, "Take out the bins") == 1
    async with env["maker"]() as db:
        assert (await db.execute(
            select(func.count()).select_from(Proposal)
        )).scalar_one() == 1


# ── Scope ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_viewer_sees_only_their_own_proposals(env):
    await _propose(env["raw_kid"], "Kid's ask")
    await _propose(env["raw_agent_a"], "The speaker's ask")

    kid_queue = await _queue(env, _kid(env))
    assert kid_queue.total == 1
    assert kid_queue.items[0].summary == "Add to-do “Kid's ask”"

    # …and the admin sees both.
    assert (await _queue(env, _alice(env))).total == 2


@pytest.mark.asyncio
async def test_an_ordinary_member_sees_nothing_and_cannot_open_a_proposal(env):
    proposed = await _propose(env["raw_kid"], "Kid's ask")

    assert (await _queue(env, _dana(env))).total == 0

    async with env["maker"]() as db:
        with pytest.raises(HTTPException) as exc:
            await proposals_router.get_proposal(
                proposal_id=uuid.UUID(proposed["proposal_id"]),
                db=db,
                current_user=_dana(env),
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_proposal_never_crosses_a_household_boundary(env):
    proposed = await _propose(env["raw_kid"], "Kid's ask")

    assert (await _queue(env, _carol(env))).total == 0
    async with env["maker"]() as db:
        with pytest.raises(HTTPException):
            await proposals_router.get_proposal(
                proposal_id=uuid.UUID(proposed["proposal_id"]),
                db=db,
                current_user=_carol(env),
            )


@pytest.mark.asyncio
async def test_a_viewer_cannot_approve_even_their_own_proposal(env):
    """The proposer may *see* their request — that is how they learn what
    happened to it — but seeing it is not deciding it."""
    proposed = await _propose(env["raw_kid"], "Kid's ask")

    async with env["maker"]() as db:
        with pytest.raises(HTTPException) as exc:
            await proposals_router.approve_proposal(
                proposal_id=uuid.UUID(proposed["proposal_id"]),
                db=db,
                current_user=_kid(env),
            )
    assert exc.value.status_code == 409
    assert "permission" in str(exc.value.detail)
    assert await _todo_count(env, "Kid's ask") == 0


# ── Realtime ──────────────────────────────────────────────────────────────────

def _drain(queue) -> list:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


@pytest.mark.asyncio
async def test_proposal_created_reaches_every_admin_and_the_proposer_only(env):
    """NOTIFICATION ROUTING: both admins, plus the member who asked. Dana — an
    ordinary member — must never learn the proposal exists."""
    q_a = bus.subscribe(env["household_a"])
    q_b = bus.subscribe(env["household_b"])
    try:
        await _propose(env["raw_kid"], "Take out the bins")
        await asyncio.sleep(0)

        events = [e for e in _drain(q_a) if getattr(e, "entity_type", None) == "proposals"]
        assert len(events) == 1
        ev = events[0]
        assert ev.action == "created"

        assert can_see(ev, env["alice"]) is True
        assert can_see(ev, env["bob"]) is True
        assert can_see(ev, env["kid"]) is True      # the proposer
        assert can_see(ev, env["dana"]) is False    # neither admin nor proposer

        # Household B's stream never carried it at all.
        assert [e for e in _drain(q_b) if getattr(e, "entity_type", None) == "proposals"] == []
    finally:
        bus.unsubscribe(env["household_a"], q_a)
        bus.unsubscribe(env["household_b"], q_b)


@pytest.mark.asyncio
async def test_the_universal_producer_never_broadcasts_a_proposal(env):
    """The denylist, tested where it bites.

    ``events/emit.py`` reads only the columns already on a row, so if proposals
    emitted automatically the descriptor would default to household visibility —
    telling every member that *something* is awaiting approval. Any future write
    to this table must go through the service's scoped event or say nothing at
    all; a bare insert says nothing.
    """
    q = bus.subscribe(env["household_a"])
    try:
        async with env["maker"]() as db:
            db.add(Proposal(
                household_id=env["household_a"],
                proposed_by_user_id=env["kid"],
                token_id=None,
                source="web",
                domain="todos",
                tool="add_todo",
                args={"title": "Written by hand"},
                args_fingerprint=uuid.uuid4().hex,
                summary="Written by hand",
                status=ProposalStatus.pending.value,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            ))
            await db.commit()
        await asyncio.sleep(0)

        assert [e for e in _drain(q) if getattr(e, "entity_type", None) == "proposals"] == []
    finally:
        bus.unsubscribe(env["household_a"], q)


@pytest.mark.asyncio
async def test_a_household_agent_proposal_reaches_admins_only(env):
    """No creator means nobody is waiting on the answer but the admins."""
    q = bus.subscribe(env["household_a"])
    try:
        await _propose(env["raw_agent_a"], "Buy milk")
        await asyncio.sleep(0)
        ev = [e for e in _drain(q) if getattr(e, "entity_type", None) == "proposals"][0]

        assert can_see(ev, env["alice"]) is True
        assert can_see(ev, env["bob"]) is True
        assert can_see(ev, env["kid"]) is False
        assert can_see(ev, env["dana"]) is False
    finally:
        bus.unsubscribe(env["household_a"], q)


@pytest.mark.asyncio
async def test_a_decision_publishes_its_own_event_so_open_queues_update(env):
    proposed = await _propose(env["raw_kid"], "Take out the bins")

    q = bus.subscribe(env["household_a"])
    try:
        async with env["maker"]() as db:
            await proposals_router.approve_proposal(
                proposal_id=uuid.UUID(proposed["proposal_id"]),
                db=db,
                current_user=_alice(env),
            )
        await asyncio.sleep(0)
        events = [e for e in _drain(q) if getattr(e, "entity_type", None) == "proposals"]
        assert [e.action for e in events] == ["updated"]
        assert can_see(events[0], env["bob"]) is True
    finally:
        bus.unsubscribe(env["household_a"], q)


@pytest.mark.asyncio
async def test_a_deduped_proposal_does_not_re_notify(env):
    """An identical retry is the same pending request the admins already saw;
    announcing it again would train them to ignore the queue."""
    q = bus.subscribe(env["household_a"])
    try:
        first = await _propose(env["raw_kid"], "Take out the bins")
        await asyncio.sleep(0)
        _drain(q)

        second = await _propose(env["raw_kid"], "Take out the bins")
        await asyncio.sleep(0)

        assert second["proposal_id"] == first["proposal_id"]
        assert [e for e in _drain(q) if getattr(e, "entity_type", None) == "proposals"] == []
    finally:
        bus.unsubscribe(env["household_a"], q)


@pytest.mark.asyncio
async def test_the_expiry_sweep_announces_once_and_only_once(env):
    proposed = await _propose(env["raw_kid"], "Take out the bins")

    async with env["maker"]() as db:
        row = await db.get(Proposal, uuid.UUID(proposed["proposal_id"]))
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

    q = bus.subscribe(env["household_a"])
    try:
        async with env["maker"]() as db:
            assert await proposals_service.sweep_expired_proposals(db) == 1
        await asyncio.sleep(0)
        assert len([e for e in _drain(q)
                    if getattr(e, "entity_type", None) == "proposals"]) == 1

        # The second sweep matches nothing, so it announces nothing.
        async with env["maker"]() as db:
            assert await proposals_service.sweep_expired_proposals(db) == 0
        await asyncio.sleep(0)
        assert [e for e in _drain(q) if getattr(e, "entity_type", None) == "proposals"] == []
    finally:
        bus.unsubscribe(env["household_a"], q)


# ── Webhook catalog ───────────────────────────────────────────────────────────

def test_proposal_events_are_in_the_catalog_with_descriptions():
    for event in ("proposal.created", "proposal.decided"):
        assert summaries.is_known_event(event)
        assert event in summaries.EVENT_DESCRIPTIONS
        assert event in summaries.CATALOG
    assert summaries.validate_patterns(["proposal.*"]) == ["proposal.*"]


def test_the_allowlist_strips_anything_it_does_not_name():
    """`args` is the exact replayable service call. It is not in the allowlist,
    so it can never reach a receiver however it got into a summary."""
    filtered = summaries.filter_summary(
        "proposal.created",
        {
            "summary": "Add to-do “Milk”",
            "domain": "todos",
            "args": {"title": "Milk", "secret_note": "do not send"},
            "reject_reason": "not a created field",
        },
    )
    assert filtered == {"summary": "Add to-do “Milk”", "domain": "todos"}


async def _capture_semantic(coro):
    """Run *coro* and return the semantic events it published."""
    q = bus.subscribe_semantic()
    try:
        await coro
        await asyncio.sleep(0)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        return events
    finally:
        bus.unsubscribe_semantic(q)


@pytest.mark.asyncio
async def test_proposal_events_deliver_only_to_subscriptions_their_owner_can_see(env):
    """SCOPE PARITY: dispatch runs the same can_see the SSE stream runs. Alice
    (admin) receives it; Dana (a member who is neither admin nor proposer) does
    not — with no second filter anywhere in the path."""
    events = await _capture_semantic(_propose(env["raw_kid"], "Take out the bins"))
    created = [e for e in events if e.event == "proposal.created"]
    assert len(created) == 1
    event: SemanticEvent = created[0]

    async with env["maker"]() as db:
        db.add_all([
            WebhookSubscription(
                household_id=env["household_a"], created_by_user_id=env["alice"],
                url="http://127.0.0.1:9/admin", secret="s1",
                event_patterns=["proposal.*"], active=True,
            ),
            WebhookSubscription(
                household_id=env["household_a"], created_by_user_id=env["dana"],
                url="http://127.0.0.1:9/member", secret="s2",
                event_patterns=["proposal.*"], active=True,
            ),
            WebhookSubscription(
                household_id=env["household_b"], created_by_user_id=env["carol"],
                url="http://127.0.0.1:9/other-house", secret="s3",
                event_patterns=["*"], active=True,
            ),
        ])
        await db.commit()

        deliveries = await webhooks_service.dispatch_event(db, event)

    urls = set()
    async with env["maker"]() as db:
        for d in deliveries:
            sub = await db.get(WebhookSubscription, d.subscription_id)
            urls.add(sub.url)
    assert urls == {"http://127.0.0.1:9/admin"}

    payload = deliveries[0].payload
    assert payload["event"] == "proposal.created"
    assert payload["entity_type"] == "proposal"
    assert payload["summary"]["summary"] == "Add to-do “Take out the bins”"
    assert payload["summary"]["proposed_by"] == "Kid"
    assert "args" not in payload["summary"]


@pytest.mark.asyncio
async def test_a_rejection_reaches_the_receiver_with_its_reason(env):
    proposed = await _propose(env["raw_kid"], "Buy a pony")

    async def _reject():
        async with env["maker"]() as db:
            await proposals_router.reject_proposal(
                proposal_id=uuid.UUID(proposed["proposal_id"]),
                data=proposals_router.ProposalRejectRequest(reason="Not this month."),
                db=db,
                current_user=_alice(env),
            )

    events = await _capture_semantic(_reject())
    decided = [e for e in events if e.event == "proposal.decided"]
    assert len(decided) == 1
    summary = summaries.filter_summary(decided[0].event, decided[0].summary)
    assert summary["status"] == "rejected"
    assert summary["decided_by"] == "Alice"
    assert summary["reject_reason"] == "Not this month."


# ── Agent status tools ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_my_proposals_returns_only_the_calling_tokens_own(env):
    await _propose(env["raw_kid"], "Kid's ask")
    await _propose(env["raw_agent_a"], "The speaker's ask")

    kid_view = await list_my_proposals(_FakeCtx(env["raw_kid"]))
    assert kid_view["total"] == 1
    assert kid_view["items"][0]["summary"] == "Add to-do “Kid's ask”"

    agent_view = await list_my_proposals(_FakeCtx(env["raw_agent_a"]))
    assert agent_view["total"] == 1
    assert agent_view["items"][0]["summary"] == "Add to-do “The speaker's ask”"


@pytest.mark.asyncio
async def test_list_my_proposals_never_crosses_a_household(env):
    await _propose(env["raw_kid"], "Kid's ask")
    assert (await list_my_proposals(_FakeCtx(env["raw_agent_b"])))["total"] == 0


@pytest.mark.asyncio
async def test_list_my_proposals_rejects_an_unknown_status_by_naming_the_valid_ones(env):
    with pytest.raises(MCPAuthError) as exc:
        await list_my_proposals(_FakeCtx(env["raw_kid"]), status="waiting")
    message = str(exc.value)
    for value in ("pending", "approved", "rejected", "expired"):
        assert value in message
    assert "waiting" in message


@pytest.mark.asyncio
async def test_get_proposal_status_relays_the_rejection_reason(env):
    proposed = await _propose(env["raw_kid"], "Buy a pony")
    async with env["maker"]() as db:
        await proposals_router.reject_proposal(
            proposal_id=uuid.UUID(proposed["proposal_id"]),
            data=proposals_router.ProposalRejectRequest(reason="Not this month."),
            db=db,
            current_user=_alice(env),
        )

    status = await get_proposal_status(_FakeCtx(env["raw_kid"]),
                                       proposal_id=proposed["proposal_id"])

    assert status["status"] == "rejected"
    assert status["reject_reason"] == "Not this month."
    assert status["decided_by_label"] == "Alice"
    # The message is what an agent actually relays: it names the decider, quotes
    # the reason, and says what to do with it.
    assert "Alice" in status["message"]
    assert "Not this month." in status["message"]
    assert "your own words" in status["message"]


@pytest.mark.asyncio
async def test_get_proposal_status_on_a_pending_one_tells_the_agent_not_to_retry(env):
    proposed = await _propose(env["raw_kid"], "Take out the bins")
    status = await get_proposal_status(_FakeCtx(env["raw_kid"]),
                                       proposal_id=proposed["proposal_id"])
    assert status["status"] == "pending"
    assert "Do not resubmit" in status["message"]


@pytest.mark.asyncio
async def test_get_proposal_status_refuses_another_tokens_proposal_with_a_way_forward(env):
    """AGENT UX: never a bare 404 — name the problem and the next tool."""
    proposed = await _propose(env["raw_kid"], "Kid's ask")

    with pytest.raises(MCPAuthError) as exc:
        await get_proposal_status(_FakeCtx(env["raw_agent_a"]),
                                  proposal_id=proposed["proposal_id"])
    message = str(exc.value)
    assert "belongs to this token" in message
    assert "list_my_proposals" in message

    # An id that exists nowhere reads the same way — the difference between
    # "not yours" and "not real" is itself information.
    with pytest.raises(MCPAuthError) as exc:
        await get_proposal_status(_FakeCtx(env["raw_kid"]), proposal_id=str(uuid.uuid4()))
    assert "list_my_proposals" in str(exc.value)


@pytest.mark.asyncio
async def test_get_proposal_status_rejects_a_malformed_id_by_showing_the_shape(env):
    with pytest.raises(MCPAuthError) as exc:
        await get_proposal_status(_FakeCtx(env["raw_kid"]), proposal_id="not-a-uuid")
    assert "must be a UUID" in str(exc.value)


@pytest.mark.asyncio
async def test_the_tool_descriptions_are_agent_UX_not_stubs():
    tools = {t.name: t.description or "" for t in await mcp_server.list_tools()}

    listing = tools["list_my_proposals"]
    for value in ("pending", "approved", "rejected", "expired"):
        assert value in listing
    assert "never the household's full approval queue" in listing
    assert "cannot approve" in listing

    single = tools["get_proposal_status"]
    assert "list_my_proposals" in single
    for value in ("pending", "approved", "rejected", "expired"):
        assert value in single

    # And the proposed-status message a write returns still reads as an
    # instruction, not an error — proposal-001's copy, still load-bearing here.
    message = proposals_service.PROPOSED_MESSAGE
    assert "not yet done" in message
    assert "do not retry" in message
    assert "get_proposal_status" in message


@pytest.mark.asyncio
async def test_an_approved_proposal_tells_the_agent_it_is_done(env):
    proposed = await _propose(env["raw_kid"], "Take out the bins")
    async with env["maker"]() as db:
        await proposals_router.approve_proposal(
            proposal_id=uuid.UUID(proposed["proposal_id"]), db=db, current_user=_alice(env)
        )

    status = await get_proposal_status(_FakeCtx(env["raw_kid"]),
                                       proposal_id=proposed["proposal_id"])
    assert "Approved by Alice" in status["message"]
    assert "carried out" in status["message"]


# ── Audit ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ui_approval_leaves_both_attribution_facts(env):
    """AUDIT DOUBLE-ATTRIBUTION: the agent proposed it, the human approved it,
    and the two are separate rows rather than one conflated actor."""
    proposed = await _propose(env["raw_agent_a"], "Buy milk")
    async with env["maker"]() as db:
        await proposals_router.approve_proposal(
            proposal_id=uuid.UUID(proposed["proposal_id"]), db=db, current_user=_alice(env)
        )

    async with env["maker"]() as db:
        rows = (await db.execute(
            select(AuditLog).where(AuditLog.household_id == env["household_a"])
        )).scalars().all()

    approvals = [r for r in rows if r.action == "approve"]
    assert len(approvals) == 1
    assert approvals[0].actor_user_id == env["alice"]
    assert approvals[0].token_id is None

    # The proposer's own row: no human actor (a shared speaker is not a person),
    # the token as the only honest identity, and the link back to the proposal.
    writes = [r for r in rows if r.entity_type == "todo"]
    assert len(writes) == 1
    assert writes[0].actor_user_id is None
    assert writes[0].token_id is not None
    assert str(proposed["proposal_id"]) in str(writes[0].payload)


# ── Voice ─────────────────────────────────────────────────────────────────────

def _voice_envelope(intent: str, slots: dict, token: str):
    return voice_schemas.AlexaEnvelope.model_validate({
        "version": "1.0",
        "context": {"System": {
            "application": {"applicationId": "amzn1.ask.skill.hearth"},
            "user": {"accessToken": token},
        }},
        "request": {
            "type": "IntentRequest",
            "requestId": "r-1",
            "timestamp": datetime.now(UTC).isoformat(),
            "intent": {
                "name": intent,
                "slots": {k: {"name": k, "value": v} for k, v in slots.items()},
            },
        },
    })


@pytest.mark.asyncio
async def test_voice_speaks_the_ask_instead_of_reading_a_status(env):
    """The bridge renders a proposed result as speech — and as an *ask*, not a
    refusal. A kid told "you don't have permission" stops asking."""
    async with env["maker"]() as db:
        response = await voice_service.dispatch(
            db, _voice_envelope("CreateTodo", {"task": "walk the dog"}, env["raw_kid"])
        )

    speech = response["response"]["outputSpeech"]["text"]
    assert "proposed" not in speech.lower()
    assert "permission" not in speech.lower()
    assert "walk the dog" in speech
    assert "ask" in speech.lower()

    # And it really is in the queue, through the same table and the same
    # executor key an agent's ask would use.
    page = await _queue(env, _alice(env), status="pending")
    assert page.total == 1
    assert page.items[0].tool == "add_todo"
    assert page.items[0].source == "voice"
    assert await _todo_count(env, "walk the dog") == 0


@pytest.mark.asyncio
async def test_voice_still_executes_a_genuine_write(env):
    """The propose tier must not intercept a write the household actually allows."""
    async with env["maker"]() as db:
        response = await voice_service.dispatch(
            db, _voice_envelope("CreateTodo", {"task": "pay rent"}, env["raw_alice_write"])
        )
    assert "added a to-do" in response["response"]["outputSpeech"]["text"].lower()
    assert await _todo_count(env, "pay rent") == 1


def test_no_approval_surface_exists_outside_an_authenticated_session():
    """The hard rule, asserted where it is actually enforced.

    /proposals maps to no PAT scope domain, so ``resolve_required_scope`` answers
    None and the deny-by-default rule refuses every PAT — an agent's, and the
    account-linking token a voice device carries. There is also no approval
    intent and no approval MCP tool, so there is nothing to reach even if the
    path check were bypassed."""
    for path in ("/proposals", "/proposals/x", "/proposals/x/approve", "/proposals/x/reject"):
        for method in ("GET", "POST", "PATCH", "DELETE"):
            assert resolve_required_scope(path, method) is None

    assert set(voice_service._INTENTS) == {
        "AddGroceryItem", "CreateTodo", "CheckInHabit", "QueryTodos"
    }


@pytest.mark.asyncio
async def test_no_mcp_tool_can_decide_a_proposal():
    names = {t.name for t in await mcp_server.list_tools()}
    assert "list_my_proposals" in names and "get_proposal_status" in names
    assert not any("approve" in n or "reject" in n or "decide" in n for n in names)


# ── The audience descriptor itself ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_queue_and_the_event_audience_cannot_disagree(env):
    """SCOPE PARITY, stated directly: everyone the event reaches can open the
    proposal, and everyone who can open it was told. A drift either way is a
    leak or a phantom row."""
    await _propose(env["raw_kid"], "Take out the bins")

    async with env["maker"]() as db:
        proposal = (await db.execute(select(Proposal))).scalars().one()
        for member, expected in [
            (_alice(env), True), (_bob(env), True), (_kid(env), True), (_dana(env), False)
        ]:
            told = await proposal_events.can_see_proposal(db, proposal, member.id)
            listed = any(
                p.id == proposal.id
                for p in (await proposals_service.list_queue(
                    db, member.household_id, member.id, member.role
                )).items
            )
            assert told is expected
            assert listed is expected
