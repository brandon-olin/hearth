"""
Hearth MCP server — read-only tool surface over household data (mcp-001).

In-process FastMCP (official Python SDK) exposed at ``/mcp`` on the API port.
No separate daemon: :func:`mcp_routes` returns the Starlette route(s) that
``main.py`` grafts onto the FastAPI app, and its session manager is driven from
the app's own lifespan.

Design rules carried from the track doc (plans/open-hearth/mcp-server.md):

* **Read-only in v1.** Tools list/read; nothing mutates. Writes are mcp-002.
* **Services, not the ORM.** Every tool calls a domain service function, the
  same rule routers follow — no ad-hoc queries here.
* **Agent permission model = the visibility model.** Each tool passes the PAT
  owner's ``user_id`` into the service so ``apply_visibility_filter`` restricts
  results to shared + that member's personal scope. Budget, documents, and
  notes have no tool at all (sensitive-data concentration), so they are
  unreachable over MCP regardless of token scope.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from life_dashboard.core.database import AsyncSessionLocal
from life_dashboard.domains.calendar_events import service as calendar_service
from life_dashboard.domains.calendar_events.schemas import CalendarEventCreate
from life_dashboard.domains.grocery_lists import service as grocery_service
from life_dashboard.domains.grocery_lists.schemas import GroceryItemAdd
from life_dashboard.domains.habits import service as habits_service
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.schemas import TodoCreate
from life_dashboard.mcp.audit_hook import record_mcp_write
from life_dashboard.mcp.auth import MCPAuthError, authorize, can_read, resolve_pat

#: streamable_http_path="/mcp" so the single route the sub-app registers is
#: "/mcp"; main.py grafts that route straight onto the FastAPI app (no Mount, so
#: no trailing-slash 307 — agents get a clean https://host/mcp). stateless_http
#: keeps each tool call an independent HTTP request, which suits long-lived
#: agent tokens and needs no server-side session store. json_response returns
#: plain JSON rather than an SSE stream.
mcp_server = FastMCP(
    "Hearth",
    instructions=(
        "Read-only access to a Hearth household: to-dos, habits, grocery lists, "
        "and calendar events. All results are scoped to the authenticated "
        "member — you see shared household data plus that member's own personal "
        "items, never another member's private data. Budget, documents, and "
        "notes are intentionally not exposed."
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    # The SDK's DNS-rebinding protection defaults to a localhost-only Host
    # allowlist, which would 421 every request in the self-hosted and cloud
    # tiers (real domains behind Caddy). It targets browser-driven attacks on
    # localhost-bound dev servers — not our threat model: every tool call
    # requires a Bearer PAT a browser can't read, and the endpoint sits behind
    # the same reverse proxy and CORS policy as the REST API. Disable it so the
    # one code path works identically across all three deployment tiers.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@mcp_server.tool()
async def list_todos(
    ctx: Context,
    status: str | None = None,
    limit: int = 50,
) -> dict:
    """List to-dos in the household (optionally filter by status, e.g. "pending"
    or "completed"). Returns items the authenticated member is allowed to see."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "todos")
        result = await todos_service.list_todos(
            db,
            ident.household_id,
            ident.user_id,
            status=status,
            limit=min(limit, 200),
        )
    return result.model_dump(mode="json")


@mcp_server.tool()
async def list_habits(
    ctx: Context,
    status: str | None = None,
    limit: int = 50,
) -> dict:
    """List habits with current streaks and completion rates. Optionally filter
    by status (e.g. "active"). Scoped to the authenticated member."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "habits")
        result = await habits_service.list_habits(
            db,
            ident.household_id,
            ident.user_id,
            status=status,
            limit=min(limit, 200),
        )
    return result.model_dump(mode="json")


@mcp_server.tool()
async def get_grocery_list(ctx: Context, limit: int = 50) -> dict:
    """Get the household's grocery lists and their items. Most households keep
    a single active list; all visible lists are returned."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "grocery")
        result = await grocery_service.list_grocery_lists(
            db,
            ident.household_id,
            ident.user_id,
            limit=min(limit, 200),
        )
    return result.model_dump(mode="json")


@mcp_server.tool()
async def list_calendar_events(
    ctx: Context,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    limit: int = 50,
) -> dict:
    """List household calendar events, optionally bounded by start time. Times
    are ISO-8601. Calendar is shared household data."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "calendar")
        result = await calendar_service.list_events(
            db,
            ident.household_id,
            starts_after=starts_after,
            starts_before=starts_before,
            limit=min(limit, 200),
        )
    return result.model_dump(mode="json")


@mcp_server.tool()
async def get_household_summary(ctx: Context) -> dict:
    """A quick overview of the household: name, count of pending to-dos, active
    habits, grocery lists, and events in the next 7 days — all within the
    authenticated member's visible scope.

    Each count is a cross-domain read, so it is gated on that domain's own token
    scope (∩ member ceiling): a token not granted a domain gets null for its
    count rather than learning data it was never scoped for. The count is thus
    the same number the corresponding list tool would return for this caller."""
    async with AsyncSessionLocal() as db:
        # Any valid PAT may see its own household's name; per-domain counts below
        # are each authorized independently.
        pat, ident = await resolve_pat(db, ctx)

        pending_todos = None
        if await can_read(db, pat, ident, "todos"):
            pending_todos = (
                await todos_service.list_todos(
                    db, ident.household_id, ident.user_id, status="pending", limit=1
                )
            ).total

        active_habits = None
        if await can_read(db, pat, ident, "habits"):
            active_habits = (
                await habits_service.list_habits(
                    db, ident.household_id, ident.user_id, status="active", limit=1
                )
            ).total

        grocery_lists = None
        if await can_read(db, pat, ident, "grocery"):
            grocery_lists = (
                await grocery_service.list_grocery_lists(
                    db, ident.household_id, ident.user_id, limit=1
                )
            ).total

        events_next_7_days = None
        if await can_read(db, pat, ident, "calendar"):
            now = datetime.now(timezone.utc)
            events_next_7_days = (
                await calendar_service.list_events(
                    db,
                    ident.household_id,
                    starts_after=now,
                    starts_before=now + timedelta(days=7),
                    limit=1,
                )
            ).total

    return {
        "household_id": str(ident.household_id),
        "household_name": ident.household_name,
        "pending_todos": pending_todos,
        "active_habits": active_habits,
        "grocery_lists": grocery_lists,
        "events_next_7_days": events_next_7_days,
    }


# ── Write tools (mcp-002) ─────────────────────────────────────────────────────
#
# Every write authorizes action="write" (token scope "write" ∩ member "create"
# ceiling), creates SHARED (household-visibility) data only — so a household-agent
# pseudo-member can never write personal or sensitive scope — is idempotent
# against double-submits, and records an audit row via record_mcp_write on a
# genuine create (a deduped no-op writes nothing and is not audited).


async def _default_grocery_list_id(db, ident) -> uuid.UUID | None:
    """The caller's most recent visible active grocery list, or None. Lets an
    agent say "add milk" without naming a list — most households keep one."""
    lists = await grocery_service.list_grocery_lists(
        db, ident.household_id, ident.user_id, status="active", limit=1
    )
    return lists.items[0].id if lists.items else None


@mcp_server.tool()
async def add_todo(
    ctx: Context,
    title: str,
    due_date: date | None = None,
    priority: str | None = None,
) -> dict:
    """Add a shared household to-do. Idempotent: re-adding the same title and due
    date returns the existing pending to-do instead of creating a duplicate.
    Always household-visible — MCP never creates personal to-dos."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "todos", "write")
        data = TodoCreate(
            title=title, due_date=due_date, priority=priority, visibility="household"
        )
        todo, created = await todos_service.create_todo_idempotent(
            db, ident.household_id, ident.user_id, data
        )
        if created:
            await record_mcp_write(
                db, ident, action="create", entity_type="todo",
                entity_id=todo.id, payload={"title": todo.title},
            )
    return {**todo.model_dump(mode="json"), "created": created}


@mcp_server.tool()
async def add_grocery_item(
    ctx: Context,
    item: str,
    quantity: float | None = None,
    unit: str | None = None,
    list_id: str | None = None,
) -> dict:
    """Add an item to a household grocery list. If list_id is omitted, the most
    recent shared list is used. Idempotent: an un-checked item with the same name
    is returned rather than duplicated ("add milk" twice → one milk)."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "grocery", "write")
        target = uuid.UUID(list_id) if list_id else await _default_grocery_list_id(db, ident)
        if target is None:
            raise MCPAuthError("No grocery list found. Create one in the app first.")
        data = GroceryItemAdd(name=item, quantity=quantity, unit=unit)
        result, created = await grocery_service.add_grocery_item_idempotent(
            db, target, ident.household_id, ident.user_id, data
        )
        if result is None:
            raise MCPAuthError("Grocery list not found or not visible to this token.")
        if created:
            await record_mcp_write(
                db, ident, action="create", entity_type="grocery_item",
                entity_id=result.id, payload={"name": result.name, "list_id": str(target)},
            )
    return {**result.model_dump(mode="json"), "created": created}


@mcp_server.tool()
async def check_in_habit(
    ctx: Context,
    habit_name: str | None = None,
    habit_id: str | None = None,
    on_date: date | None = None,
) -> dict:
    """Mark a habit complete for a date (default today). Identify the habit by
    name or id. Idempotent: checking in twice for the same date is a no-op and
    never double-counts a streak."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "habits", "write")
        if habit_id:
            hid = uuid.UUID(habit_id)
        elif habit_name:
            habit = await habits_service.get_habit_by_name(
                db, ident.household_id, ident.user_id, habit_name
            )
            if habit is None:
                raise MCPAuthError(f"No habit named {habit_name!r} found.")
            hid = habit.id
        else:
            raise MCPAuthError("Provide habit_name or habit_id.")

        scheduled = on_date or date.today()
        occ, created = await habits_service.check_in_habit(
            db, hid, ident.household_id, ident.user_id, scheduled
        )
        if occ is None:
            raise MCPAuthError("Habit not found or not visible to this token.")
        if created:
            await record_mcp_write(
                db, ident, action="check_in", entity_type="habit_occurrence",
                entity_id=occ.id, payload={"habit_id": str(hid), "date": scheduled.isoformat()},
            )
    return {**occ.model_dump(mode="json"), "created": created}


@mcp_server.tool()
async def create_calendar_event(
    ctx: Context,
    title: str,
    starts_at: datetime,
    ends_at: datetime | None = None,
    location: str | None = None,
) -> dict:
    """Create a shared household calendar event. Idempotent: the same title and
    start time returns the existing event rather than duplicating it."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "calendar", "write")
        data = CalendarEventCreate(
            title=title, starts_at=starts_at, ends_at=ends_at, location=location
        )
        event, created = await calendar_service.create_event_idempotent(
            db, ident.household_id, ident.user_id, data
        )
        if created:
            await record_mcp_write(
                db, ident, action="create", entity_type="calendar_event",
                entity_id=event.id, payload={"title": event.title,
                                             "starts_at": event.starts_at.isoformat()},
            )
    return {**event.model_dump(mode="json"), "created": created}


def mcp_routes():
    """Return the Starlette route(s) exposing the MCP endpoint at ``/mcp``.

    Grafted directly onto the FastAPI app (rather than mounted) so the path is
    exactly ``/mcp`` with no redirect. The sub-app carries no middleware of its
    own, so lifting the routes loses nothing.

    The caller MUST drive ``mcp_server.session_manager.run()`` from its own
    lifespan — the session manager backs these routes and is otherwise never
    started (see the SDK's ASGI mounting guidance).
    """
    return mcp_server.streamable_http_app().routes


__all__ = ["mcp_server", "mcp_routes", "MCPAuthError"]
