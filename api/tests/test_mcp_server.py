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
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.mcp.server as mcp_server_module
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_service import create_token
from life_dashboard.core.database import Base
from life_dashboard.domains.grocery_lists.models import GroceryList
from life_dashboard.domains.habits.models import Habit
from life_dashboard.domains.todos.models import Todo
from life_dashboard.mcp.auth import MCPAuthError
from life_dashboard.mcp.server import (
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
        db.add(GroceryList(household_id=household.id, created_by_user_id=alice.id,
                           name="Weekly shop", status="active", visibility="household"))
        await db.commit()

        _, raw_alice_full = await create_token(db, alice.id, "Alice agent", ALL_SCOPES, None)
        _, raw_todos_only = await create_token(
            db, alice.id, "Todos only", {"todos": "read"}, None
        )
        _, raw_bob = await create_token(db, bob.id, "Bob agent", ALL_SCOPES, None)

    yield {
        "raw_alice_full": raw_alice_full,
        "raw_todos_only": raw_todos_only,
        "raw_bob": raw_bob,
        "household_name": "The Olins",
        "maker": maker,
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
        "list_todos",
        "list_habits",
        "get_grocery_list",
        "list_calendar_events",
        "get_household_summary",
    }
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
