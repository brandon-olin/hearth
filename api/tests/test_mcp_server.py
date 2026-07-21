"""Tests for the read-only MCP server (mcp-001).

Covers the five verification steps in feature_list.json:

  1. The streamable-HTTP endpoint responds (initialize handshake).
  2. Token scope gates tools — a token lacking the domain scope is refused.
  3. Each read tool returns household-scoped data via the domain services.
  4. Budget / documents / notes are not exposed by any v1 tool.
  5. The agent permission model = the visibility model: an agent sees shared +
     the owning member's personal scope, never another member's personal data.

The tools resolve their own DB session from ``mcp.server.AsyncSessionLocal``, so
the suite points that name at a StaticPool in-memory engine whose data persists
across the auth session and the data session within one tool call.
"""
import uuid
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.mcp.server as mcp_server_module
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_service import create_token
from life_dashboard.core.database import Base
from life_dashboard.domains.calendar_events.models import CalendarEvent
from life_dashboard.domains.grocery_lists.models import GroceryItem, GroceryList
from life_dashboard.domains.habits.models import Habit, HabitOccurrence
from life_dashboard.domains.todos.models import Todo
from life_dashboard.mcp.auth import MCPAuthError
from life_dashboard.mcp.pseudo_member import get_or_create_household_agent
from life_dashboard.mcp.server import (
    add_grocery_item,
    add_todo,
    check_in_habit,
    create_calendar_event,
    get_grocery_list,
    get_household_summary,
    list_calendar_events,
    list_habits,
    list_todos,
    mcp_server,
)

ALL_SCOPES = {
    "todos": "read",
    "habits": "read",
    "grocery": "read",
    "calendar": "read",
    "household": "read",
}


# ── Fake MCP request context ──────────────────────────────────────────────────

class _FakeCtx:
    """Minimal stand-in for FastMCP's Context — the tool only reads the Bearer
    header off ctx.request_context.request.headers."""

    def __init__(self, raw_token: str | None):
        headers = {"authorization": f"Bearer {raw_token}"} if raw_token else {}
        request = type("Req", (), {"headers": headers})()
        self.request_context = type("RC", (), {"request": request})()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def env(monkeypatch):
    """Seed a household with two members and shared/personal data, and point the
    MCP tools' session factory at the shared in-memory engine.

    Returns a dict of everything the tests need, including raw PATs.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # The tools call AsyncSessionLocal() themselves — redirect it to our engine.
    monkeypatch.setattr(mcp_server_module, "AsyncSessionLocal", maker)

    async with maker() as db:
        household = Household(name="The Olins")
        db.add(household)
        await db.flush()

        alice = User(email="a@x.com", password_hash="x", display_name="Alice", is_active=True)
        bob = User(email="b@x.com", password_hash="x", display_name="Bob", is_active=True)
        db.add_all([alice, bob])
        await db.flush()
        db.add_all([
            HouseholdMembership(
                household_id=household.id, user_id=alice.id, role=MembershipRole.owner
            ),
            HouseholdMembership(
                household_id=household.id, user_id=bob.id, role=MembershipRole.member
            ),
        ])

        # Todos: one shared, one private to Alice, one private to Bob.
        db.add_all([
            Todo(household_id=household.id, created_by_user_id=alice.id,
                 title="Shared: buy stamps", status="pending", visibility="household"),
            Todo(household_id=household.id, created_by_user_id=alice.id,
                 title="Alice private: therapy", status="pending", visibility="personal"),
            Todo(household_id=household.id, created_by_user_id=bob.id,
                 title="Bob private: surprise gift", status="pending", visibility="personal"),
        ])
        db.add(Habit(household_id=household.id, created_by_user_id=alice.id,
                     name="Floss", frequency="daily", status="active", visibility="household"))
        db.add(Habit(household_id=household.id, created_by_user_id=bob.id,
                     name="Bob meditation", frequency="daily", status="active",
                     visibility="personal"))
        db.add(GroceryList(household_id=household.id, created_by_user_id=alice.id,
                           name="Weekly shop", status="active", visibility="household"))
        await db.commit()

        _, raw_alice_full = await create_token(db, alice.id, "Alice agent", ALL_SCOPES, None)
        _, raw_todos_only = await create_token(
            db, alice.id, "Todos only", {"todos": "read"}, None
        )
        _, raw_bob = await create_token(db, bob.id, "Bob agent", ALL_SCOPES, None)
        write_scopes = {
            "todos": "write", "grocery": "write",
            "habits": "write", "calendar": "write",
        }
        _, raw_alice_write = await create_token(db, alice.id, "Alice write", write_scopes, None)
        alice_id, bob_id, hh_id = alice.id, bob.id, household.id

    yield {
        "raw_alice_full": raw_alice_full,
        "raw_todos_only": raw_todos_only,
        "raw_bob": raw_bob,
        "raw_alice_write": raw_alice_write,
        "household_name": "The Olins",
        "maker": maker,
        "alice_id": alice_id,
        "bob_id": bob_id,
        "household_id": hh_id,
    }
    await engine.dispose()


# ── Step 5: data-scope = visibility model ─────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_sees_shared_and_own_personal_never_others_personal(env):
    ctx = _FakeCtx(env["raw_alice_full"])
    result = await list_todos(ctx)
    titles = {item["title"] for item in result["items"]}

    assert "Shared: buy stamps" in titles          # shared → visible
    assert "Alice private: therapy" in titles       # own personal → visible
    assert "Bob private: surprise gift" not in titles  # other's personal → hidden


@pytest.mark.asyncio
async def test_bobs_agent_sees_bobs_personal_not_alices(env):
    ctx = _FakeCtx(env["raw_bob"])
    result = await list_todos(ctx)
    titles = {item["title"] for item in result["items"]}

    assert "Shared: buy stamps" in titles
    assert "Bob private: surprise gift" in titles
    assert "Alice private: therapy" not in titles


# ── Step 3: each tool returns household-scoped data ───────────────────────────

@pytest.mark.asyncio
async def test_list_habits_returns_streaks(env):
    ctx = _FakeCtx(env["raw_alice_full"])
    result = await list_habits(ctx)
    names = {h["name"] for h in result["items"]}
    assert "Floss" in names
    # HabitWithStats adds computed streak fields.
    assert "current_streak" in result["items"][0]


@pytest.mark.asyncio
async def test_get_grocery_list_returns_lists(env):
    ctx = _FakeCtx(env["raw_alice_full"])
    result = await get_grocery_list(ctx)
    assert any(gl["name"] == "Weekly shop" for gl in result["items"])


@pytest.mark.asyncio
async def test_list_calendar_events_returns_household_events(env):
    ctx = _FakeCtx(env["raw_alice_full"])
    result = await list_calendar_events(ctx)
    assert "items" in result and "total" in result


@pytest.mark.asyncio
async def test_household_summary_counts(env):
    ctx = _FakeCtx(env["raw_alice_full"])
    summary = await get_household_summary(ctx)
    assert summary["household_name"] == env["household_name"]
    # Alice sees the shared todo + her own personal todo = 2 pending.
    assert summary["pending_todos"] == 2
    assert summary["active_habits"] == 1
    assert summary["grocery_lists"] == 1


@pytest.mark.asyncio
async def test_household_summary_gates_each_count_by_token_scope(env):
    """A token scoped to todos only must not learn habit / grocery / calendar
    counts through the summary — those come back null, not a real count."""
    ctx = _FakeCtx(env["raw_todos_only"])
    summary = await get_household_summary(ctx)

    assert summary["household_name"] == env["household_name"]
    assert summary["pending_todos"] == 2       # todos is in scope → real count
    assert summary["active_habits"] is None     # out of scope → withheld
    assert summary["grocery_lists"] is None
    assert summary["events_next_7_days"] is None


@pytest.mark.asyncio
async def test_household_summary_respects_member_ceiling(env):
    """Even with a todos-scoped token, a member whose household permissions deny
    todos read gets null for the todo count — the layer-2 ceiling applies to the
    summary exactly as it does to list_todos."""
    async with env["maker"]() as db:
        # A viewer in a household that restricts todos read to member-and-above.
        household = (await db.execute(select(Household))).scalars().first()
        household.permissions_config = {"todos": {"read": "member"}}

        viewer = User(email="v@x.com", password_hash="x", display_name="Viewer", is_active=True)
        db.add(viewer)
        await db.flush()
        db.add(HouseholdMembership(
            household_id=household.id, user_id=viewer.id, role=MembershipRole.viewer
        ))
        await db.commit()
        _, raw_viewer = await create_token(db, viewer.id, "Viewer agent", {"todos": "read"}, None)

    summary = await get_household_summary(_FakeCtx(raw_viewer))
    # Token has the todos scope, but the viewer's ceiling denies todos read.
    assert summary["pending_todos"] is None


# ── Step 2: token scope gates tools ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_todos_only_token_can_list_todos(env):
    ctx = _FakeCtx(env["raw_todos_only"])
    result = await list_todos(ctx)  # in scope — allowed
    assert "items" in result


@pytest.mark.asyncio
async def test_todos_only_token_cannot_list_habits(env):
    ctx = _FakeCtx(env["raw_todos_only"])
    with pytest.raises(MCPAuthError, match="read access to habits"):
        await list_habits(ctx)


@pytest.mark.asyncio
async def test_missing_credential_is_refused(env):
    ctx = _FakeCtx(None)
    with pytest.raises(MCPAuthError, match="Not authenticated"):
        await list_todos(ctx)


@pytest.mark.asyncio
async def test_garbage_token_is_refused(env):
    ctx = _FakeCtx("hearth_pat_not-a-real-token")
    with pytest.raises(MCPAuthError, match="Invalid or expired"):
        await list_todos(ctx)


@pytest.mark.asyncio
async def test_non_pat_credential_is_refused(env):
    ctx = _FakeCtx("eyJhbGciOiJIUzI1NiJ9.session.jwt")
    with pytest.raises(MCPAuthError, match="not a Hearth personal access token"):
        await list_todos(ctx)


# ── Step 4: excluded domains have no tool ─────────────────────────────────────

@pytest.mark.asyncio
async def test_no_tools_for_budget_documents_or_notes():
    tools = {t.name for t in await mcp_server.list_tools()}
    assert tools == {
        # read (mcp-001)
        "list_todos",
        "list_habits",
        "get_grocery_list",
        "list_calendar_events",
        "get_household_summary",
        # write (mcp-002)
        "add_todo",
        "add_grocery_item",
        "check_in_habit",
        "create_calendar_event",
        # workouts (workouts-001)
        "list_exercises",
        "list_workout_templates",
        "create_workout_template",
        "log_workout_session",
        # workouts (workouts-004)
        "get_exercise_progress",
    }
    # Sensitive domains are unreachable — no read *or* write tool touches them.
    for forbidden in ("budget", "document", "note"):
        assert not any(forbidden in name for name in tools)


# ── Step 1: streamable-HTTP endpoint responds ─────────────────────────────────

def _mcp_headers(raw_token: str | None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if raw_token:
        headers["Authorization"] = f"Bearer {raw_token}"
    return headers


_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1.0"},
    },
}


def _tool_call(call_id: int, name: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }


@pytest.mark.asyncio
async def test_streamable_http_end_to_end(env):
    """Everything that can only be observed over the wire, in one session.

    The SDK's session manager may be run only once per process, so all HTTP
    assertions share a single ``session_manager.run()``:

      * initialize returns a JSON-RPC result (transport wired at exactly /mcp,
        no trailing-slash redirect);
      * a real tools/call runs the full stack — FastMCP dispatch → ctx
        injection → authorize() reading the live Bearer header → domain service
        → visibility filter;
      * scope and data-scope hold over the wire, not just in direct calls.
    """
    from life_dashboard.main import app

    # session_manager.run() is normally driven by the app lifespan; start it
    # explicitly since ASGITransport does not run lifespans.
    async with mcp_server.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            init = await client.post("/mcp", json=_INIT, headers=_mcp_headers(None))

            alice = await client.post(
                "/mcp", json=_tool_call(2, "list_todos"),
                headers=_mcp_headers(env["raw_alice_full"]),
            )
            bob = await client.post(
                "/mcp", json=_tool_call(3, "list_todos"),
                headers=_mcp_headers(env["raw_bob"]),
            )
            in_scope = await client.post(
                "/mcp", json=_tool_call(4, "list_todos"),
                headers=_mcp_headers(env["raw_todos_only"]),
            )
            out_of_scope = await client.post(
                "/mcp", json=_tool_call(5, "list_habits"),
                headers=_mcp_headers(env["raw_todos_only"]),
            )

    # initialize — 200, not 307, and it's really the Hearth server.
    assert init.status_code == 200
    assert "Hearth" in init.text

    # Alice's agent sees the shared todo and her own private one, never Bob's.
    assert alice.status_code == 200
    assert "Shared: buy stamps" in alice.text
    assert "Alice private: therapy" in alice.text
    assert "Bob private: surprise gift" not in alice.text

    # Bob's agent, over the same wire, sees his own private todo and not Alice's.
    assert "Bob private: surprise gift" in bob.text
    assert "Alice private: therapy" not in bob.text

    # A todos-only token reads todos fine but is refused habits at call time.
    assert "Shared: buy stamps" in in_scope.text
    assert "read access to habits" in out_of_scope.text


# ══ mcp-002: write tools ══════════════════════════════════════════════════════

async def _count(maker, model, **filters):
    async with maker() as db:
        q = select(func.count()).select_from(model)
        for col, val in filters.items():
            q = q.where(getattr(model, col) == val)
        return (await db.execute(q)).scalar_one()


# ── Writes create shared data + are idempotent ────────────────────────────────

@pytest.mark.asyncio
async def test_add_todo_creates_shared_and_is_idempotent(env):
    ctx = _FakeCtx(env["raw_alice_write"])
    first = await add_todo(ctx, title="Mow the lawn", priority="medium")
    assert first["created"] is True
    assert first["visibility"] == "household"      # MCP never writes personal

    # Same title, no due date → deduped, not a second row.
    second = await add_todo(ctx, title="Mow the lawn")
    assert second["created"] is False
    assert second["id"] == first["id"]
    assert await _count(env["maker"], Todo, title="Mow the lawn") == 1


@pytest.mark.asyncio
async def test_add_grocery_item_defaults_list_and_dedupes(env):
    ctx = _FakeCtx(env["raw_alice_write"])
    first = await add_grocery_item(ctx, item="Milk", quantity=1, unit="gal")
    assert first["created"] is True

    # "add milk" twice → one un-checked milk line.
    second = await add_grocery_item(ctx, item="milk")   # case-insensitive
    assert second["created"] is False
    assert second["id"] == first["id"]
    assert await _count(env["maker"], GroceryItem, name="Milk") == 1


@pytest.mark.asyncio
async def test_check_in_habit_by_name_is_idempotent(env):
    ctx = _FakeCtx(env["raw_alice_write"])
    first = await check_in_habit(ctx, habit_name="Floss")
    assert first["created"] is True
    assert first["status"] == "completed"

    second = await check_in_habit(ctx, habit_name="floss")   # case-insensitive
    assert second["created"] is False
    assert second["id"] == first["id"]
    # Exactly one occurrence for today — a double check-in never double-counts.
    assert await _count(env["maker"], HabitOccurrence, id=uuid.UUID(first["id"])) == 1


@pytest.mark.asyncio
async def test_create_calendar_event_is_idempotent(env):
    ctx = _FakeCtx(env["raw_alice_write"])
    when = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
    first = await create_calendar_event(ctx, title="Dentist", starts_at=when)
    assert first["created"] is True

    second = await create_calendar_event(ctx, title="Dentist", starts_at=when)
    assert second["created"] is False
    assert second["id"] == first["id"]
    assert await _count(env["maker"], CalendarEvent, title="Dentist") == 1


# ── Write scope + member ceiling ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_only_token_cannot_write(env):
    ctx = _FakeCtx(env["raw_todos_only"])   # {todos: read}
    with pytest.raises(MCPAuthError, match="write access to todos"):
        await add_todo(ctx, title="Should fail")


@pytest.mark.asyncio
async def test_write_refused_when_member_ceiling_denies_create(env):
    """A write-scoped token still can't create where the household raised the
    create bar above the member's role — effective permission = scope ∩ ceiling."""
    async with env["maker"]() as db:
        household = (await db.execute(select(Household))).scalars().first()
        household.permissions_config = {"todos": {"create": "member"}}

        viewer = User(email="kid@x.com", password_hash="x", display_name="Kid", is_active=True)
        db.add(viewer)
        await db.flush()
        db.add(HouseholdMembership(
            household_id=household.id, user_id=viewer.id, role=MembershipRole.viewer
        ))
        await db.commit()
        _, raw_kid = await create_token(db, viewer.id, "Kid speaker", {"todos": "write"}, None)

    with pytest.raises(MCPAuthError, match="create permission for todos"):
        await add_todo(_FakeCtx(raw_kid), title="Prank todo")


# ── Household-agent pseudo-member ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_household_agent_writes_shared_scope(env):
    """A shared-device household-agent token creates shared data and is attributed
    to the agent pseudo-member (role=agent, viewer-rank)."""
    async with env["maker"]() as db:
        agent = await get_or_create_household_agent(db, env["household_id"])
        # Idempotent provisioning — a second call returns the same pseudo-member.
        agent2 = await get_or_create_household_agent(db, env["household_id"])
        assert agent.id == agent2.id
        membership = (await db.execute(
            select(HouseholdMembership).where(HouseholdMembership.user_id == agent.id)
        )).scalar_one()
        assert membership.role == MembershipRole.agent
        _, raw_agent = await create_token(
            db, agent.id, "Kitchen speaker", {"grocery": "write"}, None
        )

    result = await add_grocery_item(_FakeCtx(raw_agent), item="Eggs")
    assert result["created"] is True   # grocery create defaults to viewer → agent allowed


@pytest.mark.asyncio
async def test_household_agent_cannot_write_where_create_is_restricted(env):
    """The agent is viewer-rank, so an admin raising todos.create to member+
    locks the shared speaker out of creating todos — the kid-mischief guard."""
    async with env["maker"]() as db:
        household = (await db.execute(select(Household))).scalars().first()
        household.permissions_config = {"todos": {"create": "member"}}
        await db.commit()
        agent = await get_or_create_household_agent(db, env["household_id"])
        _, raw_agent = await create_token(db, agent.id, "Speaker", {"todos": "write"}, None)

    with pytest.raises(MCPAuthError, match="create permission for todos"):
        await add_todo(_FakeCtx(raw_agent), title="agent todo")


# ── Write-side data scope ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cannot_check_in_another_members_personal_habit_by_id(env):
    """Alice's token can't complete Bob's *personal* habit even knowing its id —
    write paths honor the visibility model just like reads."""
    async with env["maker"]() as db:
        bob_habit = (await db.execute(
            select(Habit).where(Habit.name == "Bob meditation")
        )).scalar_one()
    ctx = _FakeCtx(env["raw_alice_write"])
    with pytest.raises(MCPAuthError, match="not found or not visible"):
        await check_in_habit(ctx, habit_id=str(bob_habit.id))
    # And nothing was written.
    assert await _count(env["maker"], HabitOccurrence, habit_id=bob_habit.id) == 0


# ── Audit attribution (mcp-002 ⋈ security-008) ────────────────────────────────

@pytest.mark.asyncio
async def test_member_write_records_audit_row_attributed_to_token(env):
    """A genuine write records one audit_log row: source=mcp, actor=the owning
    member, token=the acting PAT."""
    from life_dashboard.audit.models import AuditLog

    async with env["maker"]() as db:
        token, raw = await create_token(
            db, env["alice_id"], "Speaker", {"todos": "write"}, None
        )
        token_id = token.id

    await add_todo(_FakeCtx(raw), title="Audited todo")

    async with env["maker"]() as db:
        row = (await db.execute(
            select(AuditLog).where(AuditLog.entity_type == "todo")
        )).scalar_one()
        assert row.source == "mcp"
        assert row.action == "create"
        assert row.actor_user_id == env["alice_id"]
        assert row.token_id == token_id


@pytest.mark.asyncio
async def test_deduped_write_records_no_audit_row(env):
    """A double-submit that dedupes writes nothing new, so it must not add a
    second audit row — only genuine mutations are logged."""
    from life_dashboard.audit.models import AuditLog

    ctx = _FakeCtx(env["raw_alice_write"])
    await add_todo(ctx, title="Once")
    await add_todo(ctx, title="Once")   # deduped no-op

    assert await _count(env["maker"], AuditLog, entity_type="todo") == 1


@pytest.mark.asyncio
async def test_household_agent_write_records_null_actor_with_token(env):
    """A shared-device pseudo-member write is attributed to the token, with a
    null actor — the audit trail says "the kitchen speaker did it", not a person."""
    from life_dashboard.audit.models import AuditLog

    async with env["maker"]() as db:
        agent = await get_or_create_household_agent(db, env["household_id"])
        token, raw = await create_token(
            db, agent.id, "Kitchen speaker", {"grocery": "write"}, None
        )
        token_id = token.id

    await add_grocery_item(_FakeCtx(raw), item="Butter")

    async with env["maker"]() as db:
        row = (await db.execute(
            select(AuditLog).where(AuditLog.entity_type == "grocery_item")
        )).scalar_one()
        assert row.actor_user_id is None      # pseudo-member → no person
        assert row.token_id == token_id       # …but the token is on record
        assert row.source == "mcp"
