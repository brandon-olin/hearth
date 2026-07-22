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

The notes exclusion covers **guided journaling** (journal-001/002) too, and
that is the deliberate answer to the "no feature ships without its MCP verb"
rule rather than an oversight. A journal session is the most sensitive text in
the app; a tool that could start one, read the transcript, or save an entry
would hand exactly that to any PAT holder. The agent surface for the feature is
therefore the ``journal.session_saved`` bus event (webhooks/summaries.py), which
carries the fact of a session and its check-in mode but no entry text — the same
"receiver fetches the entity back with its own credentials" shape the rest of
the catalog uses. Revisit this only alongside a per-domain consent model, not by
adding a tool here.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from life_dashboard.audit.decorator import resolve_actor_user_id
from life_dashboard.audit.schemas import AuditSource
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.core.database import AsyncSessionLocal
from life_dashboard.domains.calendar_events import service as calendar_service
from life_dashboard.domains.calendar_events.schemas import CalendarEventCreate
from life_dashboard.domains.grocery_lists import service as grocery_service
from life_dashboard.domains.grocery_lists.schemas import GroceryItemAdd
from life_dashboard.domains.habits import service as habits_service
from life_dashboard.domains.meal_plans import service as meal_plans_service
from life_dashboard.domains.meal_plans.schemas import (
    MEAL_SLOTS,
    MealPlanCreate,
    MealPlanEntryCreate,
)
from life_dashboard.domains.recipes import service as recipes_service
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.schemas import TodoCreate
from life_dashboard.domains.workouts import (
    exercises_service,
    progress_service,
    sessions_service,
    templates_service,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseCreate,
    TemplateExerciseCreate,
    WorkoutSessionCreate,
    WorkoutTemplateCreate,
)
from life_dashboard.mcp.audit_hook import record_mcp_write
from life_dashboard.mcp.auth import MCPAuthError, authorize, can_read, resolve_pat
from life_dashboard.onboarding import service as onboarding_service
from life_dashboard.proposals import service as proposals_service
from life_dashboard.proposals.executors import register_executor
from life_dashboard.proposals.labels import label_one
from life_dashboard.proposals.schemas import PROPOSAL_STATUS_VALUES, ProposalResponse

#: streamable_http_path="/mcp" so the single route the sub-app registers is
#: "/mcp"; main.py grafts that route straight onto the FastAPI app (no Mount, so
#: no trailing-slash 307 — agents get a clean https://host/mcp). stateless_http
#: keeps each tool call an independent HTTP request, which suits long-lived
#: agent tokens and needs no server-side session store. json_response returns
#: plain JSON rather than an SSE stream.
mcp_server = FastMCP(
    "Hearth",
    instructions=(
        "Access to a Hearth household: to-dos, habits, grocery lists, calendar "
        "events, and workouts (the exercise library, shared templates, and the "
        "member's own logged sessions). All results are scoped to the "
        "authenticated member — you see shared household data plus that member's "
        "own personal items, never another member's private data. Workout "
        "templates and the exercise catalog are shared household-wide; logged "
        "workout sessions are personal to each member. Budget, documents, and "
        "notes are intentionally not exposed. "
        "Some households require human approval for some actions: a write may "
        "answer `status: \"proposed\"` instead of doing the thing. That is a "
        "pending request, not an error and not a refusal — say so, and follow it "
        "with get_proposal_status or list_my_proposals rather than retrying. "
        "Approving is a human action taken in the Hearth app; no tool here can "
        "do it."
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


def _as_uuid(value: str, field: str) -> uuid.UUID:
    """Parse an id argument, failing with an agent-readable message rather than
    letting a ValueError surface as an opaque 500."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise MCPAuthError(
            f"{field} must be a UUID, e.g. "
            f"'3fa85f64-5717-4562-b3fc-2c963f66afa6'; got {value!r}."
        ) from None


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
async def get_meal_plan(ctx: Context, week_of: date | None = None) -> dict:
    """Get the household's meal plan for a week — which recipes are scheduled
    for which day and meal slot (breakfast, lunch, dinner, snack).

    `week_of` is any date inside the week you want, in ISO format
    (e.g. "2026-07-22"); it is normalised to that week's Monday. Omit it for
    the current week.

    Returns null when nothing has been planned for that week yet — an empty
    week, not an error. Meal plans are shared household data."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "meals")
        plan = await meal_plans_service.get_plan_for_week(
            db, ident.household_id, ident.user_id, week_of or date.today()
        )
    return plan.model_dump(mode="json") if plan else {"plan": None}


@mcp_server.tool()
async def list_recipes(ctx: Context, search: str | None = None, limit: int = 50) -> dict:
    """List the household's recipes, optionally filtered by a name substring.

    This is how an agent turns "plan the chili for Wednesday" into the
    `recipe_id` that `plan_meal` needs."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "recipes")
        result = await recipes_service.list_recipes(
            db,
            ident.household_id,
            ident.user_id,
            search=search,
            limit=min(limit, 200),
        )
    return result.model_dump(mode="json")


async def _resolve_recipe_id(db, ident, recipe_id: str | None, recipe_name: str | None):
    """A recipe's id from either an id or a name.

    A name that matches several recipes is refused with the candidates listed
    rather than picking one — guessing which chili the household meant is
    exactly the kind of silent wrong answer an approval queue exists to avoid.
    """
    if recipe_id:
        return _as_uuid(recipe_id, "recipe_id")
    if not recipe_name:
        raise MCPAuthError("Provide recipe_name or recipe_id.")

    found = await recipes_service.list_recipes(
        db, ident.household_id, ident.user_id, search=recipe_name, limit=25
    )
    if not found.items:
        raise MCPAuthError(
            f"No recipe matching {recipe_name!r}. Call list_recipes to see what exists."
        )
    exact = [r for r in found.items if r.name.strip().lower() == recipe_name.strip().lower()]
    if len(exact) == 1:
        return exact[0].id
    if len(found.items) == 1:
        return found.items[0].id
    names = ", ".join(f"{r.name!r}" for r in found.items[:10])
    raise MCPAuthError(
        f"{recipe_name!r} matches {len(found.items)} recipes ({names}). "
        f"Pass recipe_id to choose one."
    )


@register_executor("plan_meal")
async def _perform_plan_meal(
    db, ident, *, recipe_id: str | None = None, recipe_name: str | None = None,
    on_date=None, meal_slot: str = "dinner",
) -> dict:
    entry_date = _coerce_date(on_date) or date.today()
    resolved_recipe_id = await _resolve_recipe_id(db, ident, recipe_id, recipe_name)
    plan = await meal_plans_service.get_or_create_plan(
        db,
        ident.household_id,
        ident.user_id,
        MealPlanCreate(week_start=entry_date),
    )
    entry, created, error = await meal_plans_service.add_entry(
        db,
        plan.id,
        ident.household_id,
        ident.user_id,
        MealPlanEntryCreate(
            recipe_id=resolved_recipe_id,
            entry_date=entry_date,
            meal_slot=meal_slot,
        ),
    )
    if entry is None:
        raise MCPAuthError(error or "Could not plan that meal.")
    if created:
        await record_mcp_write(
            db, ident, action="create", entity_type="meal_plan_entry",
            entity_id=entry.id,
            payload={
                "recipe_id": str(entry.recipe_id),
                "entry_date": entry.entry_date.isoformat(),
                "meal_slot": entry.meal_slot,
            },
        )
    return {**entry.model_dump(mode="json"), "created": created, "plan_id": str(plan.id)}


@mcp_server.tool()
async def plan_meal(
    ctx: Context,
    on_date: date,
    recipe_name: str | None = None,
    recipe_id: str | None = None,
    meal_slot: str = "dinner",
) -> dict:
    """Schedule a recipe onto a day of the household's meal plan.

    Identify the recipe by name or id — a name is matched case-insensitively,
    and an ambiguous one comes back with the candidates rather than a guess.
    `on_date` is ISO (e.g. "2026-07-22"); the week's plan is created
    automatically if it does not exist yet. `meal_slot` must be one of:
    breakfast, lunch, dinner, snack.

    Idempotent: planning the same recipe on the same day and slot twice returns
    the existing entry with `created: false` rather than duplicating it.

    If this household requires approval for recipe writes, the result is
    `status: "proposed"` with a message — a request waiting on a human, not an
    error."""
    if meal_slot not in MEAL_SLOTS:
        raise MCPAuthError(
            f"meal_slot must be one of: {', '.join(MEAL_SLOTS)}; got {meal_slot!r}."
        )
    args = {
        "recipe_id": recipe_id,
        "recipe_name": recipe_name,
        "on_date": on_date,
        "meal_slot": meal_slot,
    }
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "meals", "write")
        if decision.proposed:
            label = recipe_name or recipe_id or "a recipe"
            return await _propose(
                db, decision, domain="meals", tool="plan_meal", args=args,
                summary=f"Plan “{label}” for {on_date.isoformat()} {meal_slot}",
            )
        return await _perform_plan_meal(db, decision, **args)


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
            now = datetime.now(UTC)
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


# ── Write tools (mcp-002, propose tier from proposal-001) ─────────────────────
#
# Every write authorizes action="write" (token scope ∩ member ceiling), creates
# SHARED (household-visibility) data only — so a household-agent pseudo-member
# can never write personal or sensitive scope — is idempotent against
# double-submits, and records an audit row via record_mcp_write on a genuine
# create (a deduped no-op writes nothing and is not audited).
#
# proposal-001 changes each of them in exactly one way: when authorize resolves
# to the `propose` tier, the tool records a Proposal and returns
# `{"status": "proposed", ...}` instead of executing. The write itself lives in a
# registered `_perform_*` function so the approval path replays THE SAME code —
# a reimplementation would let an approved write drift from the tool it was
# proposed through.


def _coerce_date(value) -> date | None:
    """Accept either a real date or the ISO string a stored proposal holds.

    Proposal args round-trip through JSON, so an approved replay hands back
    "2026-07-22" where the live call passed a ``date``. Everything downstream
    wants the real type.
    """
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _coerce_datetime(value) -> datetime | None:
    """Datetime counterpart of :func:`_coerce_date`."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def _propose(
    db, decision, *, domain: str, tool: str, args: dict, summary: str
) -> dict:
    """Capture a would-be write as a pending proposal and answer the agent.

    ``proposed_by_user_id`` follows the same rule as audit attribution: NULL for
    a household-agent pseudo-member, whose ``token_id`` is then the only honest
    identity there is. That is exactly why ``proposals.token_id`` must never
    cascade to NULL — see proposals/models.py.
    """
    proposal, _created = await proposals_service.record_proposal(
        db,
        household_id=decision.household_id,
        proposed_by_user_id=resolve_actor_user_id(decision),
        token_id=decision.pat_id,
        source=AuditSource.mcp,
        domain=domain,
        tool=tool,
        args=args,
        summary=summary,
    )
    return proposals_service.proposed_response(proposal)


async def _default_grocery_list_id(db, ident) -> uuid.UUID | None:
    """The caller's most recent visible active grocery list, or None. Lets an
    agent say "add milk" without naming a list — most households keep one."""
    lists = await grocery_service.list_grocery_lists(
        db, ident.household_id, ident.user_id, status="active", limit=1
    )
    return lists.items[0].id if lists.items else None


@register_executor("add_todo")
async def _perform_add_todo(
    db, ident, *, title: str, due_date=None, priority: str | None = None
) -> dict:
    data = TodoCreate(
        title=title,
        due_date=_coerce_date(due_date),
        priority=priority,
        visibility="household",
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
async def add_todo(
    ctx: Context,
    title: str,
    due_date: date | None = None,
    priority: str | None = None,
) -> dict:
    """Add a shared household to-do. Idempotent: re-adding the same title and due
    date returns the existing pending to-do instead of creating a duplicate.
    Always household-visible — MCP never creates personal to-dos.

    If this household requires approval for to-dos, the result is
    `status: "proposed"` with a `message` explaining what happens next. That is
    not an error and not a failure — the request is waiting on a human."""
    args = {"title": title, "due_date": due_date, "priority": priority}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "todos", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="todos", tool="add_todo", args=args,
                summary=f"Add to-do “{title}”",
            )
        return await _perform_add_todo(db, decision, **args)


@register_executor("add_grocery_item")
async def _perform_add_grocery_item(
    db,
    ident,
    *,
    item: str,
    quantity: float | None = None,
    unit: str | None = None,
    list_id: str | None = None,
) -> dict:
    # Resolved at execution time, not at propose time: an approval that lands a
    # week later belongs on whatever list is current then, which is the same
    # list the household would have gotten had the write run immediately.
    target = _as_uuid(list_id, "list_id") if list_id else await _default_grocery_list_id(db, ident)
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
async def add_grocery_item(
    ctx: Context,
    item: str,
    quantity: float | None = None,
    unit: str | None = None,
    list_id: str | None = None,
) -> dict:
    """Add an item to a household grocery list. If list_id is omitted, the most
    recent shared list is used. Idempotent: an un-checked item with the same name
    is returned rather than duplicated ("add milk" twice → one milk).

    A household that requires approval for grocery writes answers
    `status: "proposed"` instead — a pending request, not an error."""
    args = {"item": item, "quantity": quantity, "unit": unit, "list_id": list_id}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "grocery", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="grocery", tool="add_grocery_item", args=args,
                summary=f"Add “{item}” to the grocery list",
            )
        return await _perform_add_grocery_item(db, decision, **args)


@register_executor("check_in_habit")
async def _perform_check_in_habit(
    db, ident, *, habit_name: str | None = None, habit_id: str | None = None, on_date=None
) -> dict:
    if habit_id:
        hid = _as_uuid(habit_id, "habit_id")
    elif habit_name:
        habit = await habits_service.get_habit_by_name(
            db, ident.household_id, ident.user_id, habit_name
        )
        if habit is None:
            raise MCPAuthError(f"No habit named {habit_name!r} found.")
        hid = habit.id
    else:
        raise MCPAuthError("Provide habit_name or habit_id.")

    scheduled = _coerce_date(on_date) or date.today()
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
async def check_in_habit(
    ctx: Context,
    habit_name: str | None = None,
    habit_id: str | None = None,
    on_date: date | None = None,
) -> dict:
    """Mark a habit complete for a date (default today). Identify the habit by
    name or id. Idempotent: checking in twice for the same date is a no-op and
    never double-counts a streak.

    Where the household requires approval, this answers `status: "proposed"` —
    the check-in is queued for a human, not rejected."""
    args = {"habit_name": habit_name, "habit_id": habit_id, "on_date": on_date}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "habits", "write")
        if decision.proposed:
            label = habit_name or habit_id or "a habit"
            return await _propose(
                db, decision, domain="habits", tool="check_in_habit", args=args,
                summary=f"Check in “{label}”",
            )
        return await _perform_check_in_habit(db, decision, **args)


@register_executor("create_calendar_event")
async def _perform_create_calendar_event(
    db, ident, *, title: str, starts_at, ends_at=None, location: str | None = None
) -> dict:
    data = CalendarEventCreate(
        title=title,
        starts_at=_coerce_datetime(starts_at),
        ends_at=_coerce_datetime(ends_at),
        location=location,
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


@mcp_server.tool()
async def create_calendar_event(
    ctx: Context,
    title: str,
    starts_at: datetime,
    ends_at: datetime | None = None,
    location: str | None = None,
) -> dict:
    """Create a shared household calendar event. Idempotent: the same title and
    start time returns the existing event rather than duplicating it.

    A household requiring approval for calendar writes answers
    `status: "proposed"`; the event is pending a human decision, not refused."""
    args = {"title": title, "starts_at": starts_at, "ends_at": ends_at, "location": location}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "calendar", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="calendar", tool="create_calendar_event", args=args,
                summary=f"Add “{title}” to the calendar",
            )
        return await _perform_create_calendar_event(db, decision, **args)


# ── Workouts (workouts-001) ───────────────────────────────────────────────────
#
# The exercise catalog and templates are SHARED household data; logged sessions
# are PERSONAL (owned by, and only ever visible to, the token's member). Reads
# use scope "workouts"; the two write tools add scope "write" and audit genuine
# creates.


@mcp_server.tool()
async def list_exercises(
    ctx: Context,
    search: str | None = None,
    limit: int = 100,
) -> dict:
    """List exercises available to this household: the shared global library
    (~60 seeded movements) plus the household's own custom exercises. Optionally
    filter by a name substring via `search` (case-insensitive). Each exercise
    reports its `tracking_type`, one of: "reps" (weighted/bodyweight strength),
    "duration" (timed holds like planks), or "distance" (cardio like running or
    rowing)."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "workouts")
        result = await exercises_service.list_exercises(
            db, ident.household_id, search=search, limit=min(limit, 200)
        )
    return result.model_dump(mode="json")


@mcp_server.tool()
async def list_workout_templates(
    ctx: Context,
    search: str | None = None,
    limit: int = 50,
) -> dict:
    """List the household's shared workout templates, ordered by how recently
    THIS member last used each (most recent first; never-used last). Optionally
    filter by a name substring via `search`. Every household template is
    returned regardless of who created it — only the ordering is personal.
    `last_used_at` and `exercise_count` are included per template."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "workouts")
        result = await templates_service.list_templates(
            db, ident.household_id, ident.user_id, search=search, limit=min(limit, 200)
        )
    return result.model_dump(mode="json")


@register_executor("create_workout_template")
async def _perform_create_workout_template(
    db,
    ident,
    *,
    name: str,
    exercises: list[str] | None = None,
    description: str | None = None,
    estimated_duration_minutes: int | None = None,
) -> dict:
    slots: list[TemplateExerciseCreate] = []
    for i, ex_name in enumerate(exercises or []):
        if not ex_name or not ex_name.strip():
            continue
        exercise, _ = await exercises_service.create_exercise(
            db, ident.household_id, ident.user_id, ExerciseCreate(name=ex_name)
        )
        slots.append(TemplateExerciseCreate(exercise_id=exercise.id, position=i))
    data = WorkoutTemplateCreate(
        name=name,
        description=description,
        estimated_duration_minutes=estimated_duration_minutes,
        exercises=slots,
    )
    template = await templates_service.create_template(
        db, ident.household_id, ident.user_id, data
    )
    await record_mcp_write(
        db, ident, action="create", entity_type="workout_template",
        entity_id=template.id, payload={"name": template.name,
                                        "exercise_count": template.exercise_count},
    )
    return template.model_dump(mode="json")


@mcp_server.tool()
async def create_workout_template(
    ctx: Context,
    name: str,
    exercises: list[str] | None = None,
    description: str | None = None,
    estimated_duration_minutes: int | None = None,
) -> dict:
    """Create a shared household workout template.

    `exercises` is an ordered list of exercise NAMES (not IDs). Each is matched
    against the catalog case-insensitively; an unknown name creates a new
    household-custom exercise (default tracking_type "reps" — edit it later for
    cardio/timed movements). Example: create_workout_template(name="Push Day",
    exercises=["Barbell Bench Press", "Overhead Press", "Tricep Pushdown"]).
    The template is shared with the whole household.

    Answers `status: "proposed"` where the token may only ask — a pending
    request awaiting a human, not a failure."""
    args = {
        "name": name,
        "exercises": exercises,
        "description": description,
        "estimated_duration_minutes": estimated_duration_minutes,
    }
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "workouts", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="workouts", tool="create_workout_template", args=args,
                summary=f"Create the workout template “{name}”",
            )
        return await _perform_create_workout_template(db, decision, **args)


@register_executor("log_workout_session")
async def _perform_log_workout_session(
    db, ident, *, name: str | None = None, template: str | None = None, notes: str | None = None
) -> dict:
    template_id = None
    if template:
        found = await templates_service.find_template_by_name(
            db, ident.household_id, template
        )
        if found is None:
            raise MCPAuthError(
                f"No workout template named {template!r}. Use "
                "list_workout_templates to see available names."
            )
        template_id = found.id
    data = WorkoutSessionCreate(name=name, template_id=template_id, notes=notes)
    session = await sessions_service.create_session(
        db, ident.household_id, ident.user_id, data
    )
    if session is None:
        raise MCPAuthError("Could not start the session — template not found.")
    await record_mcp_write(
        db, ident, action="create", entity_type="workout_session",
        entity_id=session.id,
        payload={
            "name": session.name,
            "template_id": str(template_id) if template_id else None,
        },
    )
    return session.model_dump(mode="json")


@mcp_server.tool()
async def log_workout_session(
    ctx: Context,
    name: str | None = None,
    template: str | None = None,
    notes: str | None = None,
) -> dict:
    """Log a workout session for THIS member (personal — never visible to other
    members).

    Pass `template` (a template NAME) to start from that template: the session
    is pre-populated with the template's exercises and default sets. Otherwise a
    blank session is created with the given `name`. Provide at least one of
    `name` or `template`. Returns the created session with its materialized
    exercises and sets."""
    if not name and not template:
        raise MCPAuthError("Provide a session name or a template name to log.")
    args = {"name": name, "template": template, "notes": notes}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "workouts", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="workouts", tool="log_workout_session", args=args,
                summary=f"Log the workout “{name or template}”",
            )
        return await _perform_log_workout_session(db, decision, **args)


@mcp_server.tool()
async def get_workout_prefill(
    ctx: Context,
    session_id: str,
) -> dict:
    """Suggest starting weights and reps for an in-progress session — the same
    "ghost values" the app pre-fills each set with.

    `session_id` is the id returned by log_workout_session. For every exercise
    in that session it returns `sets` (set_number, reps, weight, weight_unit,
    is_warmup) plus `source`:
      * "history"  — what THIS member last logged for the same template slot
      * "template" — the template's default_weight / default_reps
      * "none"     — nothing to suggest yet; start from empty

    These are suggestions only; nothing is recorded until sets are logged.
    Suggestions are always personal: another household member's numbers are
    never used, even when the template is shared."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "workouts")
        prefill = await sessions_service.get_session_prefill(
            db, _as_uuid(session_id, "session_id"), ident.household_id, ident.user_id
        )
        if prefill is None:
            raise MCPAuthError(
                "No such workout session for this member. Sessions are personal "
                "— use list_workout_sessions ids belonging to this token."
            )
    return prefill.model_dump(mode="json")


@register_executor("finish_workout_session")
async def _perform_finish_workout_session(db, ident, *, session_id: str) -> dict:
    summary = await sessions_service.finish_session(
        db, _as_uuid(session_id, "session_id"), ident.household_id, ident.user_id
    )
    if summary is None:
        raise MCPAuthError("No such workout session for this member.")
    await record_mcp_write(
        db, ident, action="update", entity_type="workout_session",
        entity_id=summary.session_id,
        payload={"ended_at": summary.ended_at.isoformat() if summary.ended_at else None},
    )
    return summary.model_dump(mode="json")


@mcp_server.tool()
async def finish_workout_session(
    ctx: Context,
    session_id: str,
) -> dict:
    """Mark a workout session finished and return its summary.

    Reports `duration_seconds`, `working_volume` (Σ weight × reps over completed
    sets, warmups excluded) with its `volume_unit`, `working_sets_completed`,
    `warmup_sets_completed`, `exercises_completed`, and `from_template`.

    Only sets that were checked off (completed) count. Safe to call twice: a
    session that is already finished keeps its original end time."""
    args = {"session_id": session_id}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "workouts", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="workouts", tool="finish_workout_session", args=args,
                summary="Finish the in-progress workout session",
            )
        return await _perform_finish_workout_session(db, decision, **args)


@register_executor("save_session_as_template")
async def _perform_save_session_as_template(
    db, ident, *, session_id: str, name: str | None = None
) -> dict:
    template = await sessions_service.save_session_as_template(
        db, _as_uuid(session_id, "session_id"), ident.household_id, ident.user_id, name,
    )
    if template is None:
        raise MCPAuthError("No such workout session for this member.")
    await record_mcp_write(
        db, ident, action="create", entity_type="workout_template",
        entity_id=template.id,
        payload={"name": template.name, "from_session": session_id},
    )
    return template.model_dump(mode="json")


@mcp_server.tool()
async def save_session_as_template(
    ctx: Context,
    session_id: str,
    name: str | None = None,
) -> dict:
    """Turn a logged session into a reusable, household-shared workout template.

    Each exercise becomes a template slot whose defaults are derived from what
    was logged: default_sets = the number of working sets, default_reps = the
    most common rep count, default_weight = the heaviest working set. Warmup
    sets are excluded. `name` defaults to the session's name.

    The session itself is not modified, so calling this twice creates two
    templates rather than altering history."""
    args = {"session_id": session_id, "name": name}
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "workouts", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="workouts", tool="save_session_as_template", args=args,
                summary=f"Save a workout session as the template “{name or 'untitled'}”",
            )
        return await _perform_save_session_as_template(db, decision, **args)


@mcp_server.tool()
async def get_exercise_progress(
    ctx: Context,
    exercise: str,
    limit: int = 20,
) -> dict:
    """Return how THIS member's performance on one exercise has changed over
    time — the same personal history the Progress tab charts.

    `exercise` is an exercise NAME (not an ID), matched case-insensitively
    against the catalog; use list_exercises to see valid names. `limit` caps how
    many of the most recent sessions come back (default 20, max 200).

    Sessions are ordered OLDEST to NEWEST, each with its `session_date` and the
    working sets logged that day (`reps`, `weight`, `target_reps`). Warmup sets
    are excluded, as are sets with nothing logged — so timed and cardio
    movements (tracking_type "duration" or "distance") return no sessions here.

    Nothing is precomputed: derive trends from the sets. Volume is
    sum(weight × reps); estimated 1RM is the Epley formula, weight × (1 +
    reps / 30), and is only meaningful for sets of 10 reps or fewer. A set whose
    `reps` is below its `target_reps` was a failed set; a NULL `target_reps` is
    not a failure. A NULL `weight` throughout means a bodyweight exercise —
    track reps instead.

    Another household member's sessions are never included: workout history is
    personal even though the exercise catalog is shared."""
    async with AsyncSessionLocal() as db:
        ident = await authorize(db, ctx, "workouts")
        found = await exercises_service.find_exercise_by_name(
            db, ident.household_id, exercise
        )
        if found is None:
            raise MCPAuthError(
                f"No exercise named {exercise!r}. Use list_exercises to see "
                "available names."
            )
        result = await progress_service.get_exercise_progress(
            db, found.id, ident.household_id, ident.user_id, limit=min(limit, 200)
        )
    return result.model_dump(mode="json")


# ── Proposal status tools (proposal-002) ──────────────────────────────────────
#
# The other half of the propose tier: an agent that gets `status: "proposed"`
# needs somewhere to look afterwards, or it goes silent and its user never learns
# why nothing happened. Both tools are READ-ONLY and confined to the calling
# token's own proposals — approving is a human act on an authenticated surface
# (the /proposals routes are unreachable with a PAT by construction), because an
# agent approving its own proposals defeats the entire mechanism.
#
# They authorize on the PAT alone rather than on a domain scope. A token must be
# able to check what it itself asked for regardless of which domains it holds:
# the scope check already happened when the proposal was recorded, and re-gating
# the follow-up would strand a request the household is actively deciding.


def _own_proposal_filters(ident) -> dict:
    """The filters that confine a query to THIS token's own proposals.

    ``token_id`` always, because "belongs to this token" is what the agent-facing
    copy promises. ``proposed_by_user_id`` as well for a real member, which is
    defence in depth rather than the primary gate — a household-agent proposal
    has none (that is the whole point of the column being nullable), so it cannot
    be the only filter.
    """
    return {
        "token_id": ident.pat_id,
        "proposed_by_user_id": resolve_actor_user_id(ident),
    }


@mcp_server.tool()
async def list_my_proposals(
    ctx: Context,
    status: str | None = None,
    limit: int = 20,
) -> dict:
    """List the requests you have submitted on this member's behalf that are still
    awaiting a human decision, plus recently decided ones. Returns only your own
    proposals — never the household's full approval queue, and never another
    member's.

    Use this when the user asks what you are waiting on, or after a write
    returned `status: "proposed"`.

    Filter with `status`: `pending` (awaiting a decision), `approved` (executed),
    `rejected` (declined, with a reason), `expired` (nobody decided before
    `expires_at`). Omit `status` for all four.

    Each item carries a `message` written for you to relay, and a `summary`
    describing what was asked for. You cannot approve a proposal — approval is a
    human action taken in the Hearth app."""
    async with AsyncSessionLocal() as db:
        _pat, ident = await resolve_pat(db, ctx)
        if status is not None and status not in PROPOSAL_STATUS_VALUES:
            raise MCPAuthError(proposals_service.unknown_status_message(status))
        result = await proposals_service.list_proposals(
            db,
            ident.household_id,
            status=status,
            limit=min(limit, 100),
            **_own_proposal_filters(ident),
        )
    payload = result.model_dump(mode="json")
    for item, raw in zip(payload["items"], result.items, strict=True):
        item["message"] = proposals_service.status_message(raw)
    return payload


@mcp_server.tool()
async def get_proposal_status(ctx: Context, proposal_id: str) -> dict:
    """Check what happened to one proposal you submitted, by `proposal_id`.

    Returns its status, who decided it and when, and — for a rejection — the
    reason the approver gave, which you should relay to the user in their own
    words rather than quoting verbatim. The `message` field says exactly that in
    context; prefer it over interpreting the status string yourself.

    Statuses are `pending` (nobody has decided yet — do NOT resubmit the
    underlying action, as an identical request returns this same proposal rather
    than creating a second one), `approved` (the action has been carried out),
    `rejected` (a human declined it) and `expired` (nobody decided in time, or
    the credential that asked is gone).

    Unknown id: see `list_my_proposals` for the ids you own."""
    async with AsyncSessionLocal() as db:
        _pat, ident = await resolve_pat(db, ctx)
        proposal = await proposals_service.get_proposal(
            db,
            ident.household_id,
            _as_uuid(proposal_id, "proposal_id"),
            **_own_proposal_filters(ident),
        )
        if proposal is None:
            raise MCPAuthError(proposals_service.UNKNOWN_PROPOSAL_MESSAGE)
        item = await label_one(db, ProposalResponse.model_validate(proposal))
    return {**item.model_dump(mode="json"), "message": proposals_service.status_message(item)}


# ── Onboarding & sample data (onboarding-001 / onboarding-002) ───────────────


@mcp_server.tool()
async def get_onboarding_status(ctx: Context) -> dict:
    """Where this household and member stand in first-run setup: whether the
    member has finished the welcome wizard, which modules they said they care
    about, whether the household holds any real content yet, and whether it is
    still showing sample data.

    Useful before suggesting anything to a new household — a household that is
    still exploring sample data has not told you anything about itself yet, and
    `household_has_data: false` means every to-do and habit you can see was put
    there by the seeder, not by a person.

    `modules` is a subset of: finance, habits, meals, tasks, health, notes,
    planning, contacts. Empty means the member skipped the question, which is
    "no preference", not "none of them"."""
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "household", "read")
        user = await get_user_by_id(db, decision.user_id)
        if user is None:
            raise MCPAuthError("Token owner no longer exists.")
        return {
            "household_id": str(decision.household_id),
            "household_name": decision.household_name,
            "wizard_completed": onboarding_service.wizard_completed(user),
            "modules": onboarding_service.wizard_modules(user),
            "household_has_data": await onboarding_service.household_has_real_data(
                db, decision.household_id
            ),
            "sample_data": (
                await onboarding_service.demo_data_status(db, decision.household_id)
            ).model_dump(mode="json"),
        }


@register_executor("clear_sample_data")
async def _perform_clear_sample_data(db, ident) -> dict:
    result = await onboarding_service.clear_demo_data(db, ident.household_id)
    if result.cleared:
        await record_mcp_write(
            db, ident, action="delete", entity_type="household_demo_data",
            entity_id=ident.household_id, payload={"counts": result.counts},
        )
    return result.model_dump(mode="json")


@mcp_server.tool()
async def clear_sample_data(ctx: Context) -> dict:
    """Remove the sample content Hearth seeds into a brand-new household, once
    the household has started entering its own.

    Deletes only what the seeder created — every to-do, habit, recipe, note and
    transaction the household wrote itself survives, including anything filed
    inside a sample project. Idempotent: with nothing seeded it answers
    `cleared: false` and deletes nothing, which is a success, not an error.

    Check `get_onboarding_status` first if you are unsure there is anything to
    clear. A household that requires approval for this answers
    `status: "proposed"` — a pending request waiting on a human, not a refusal.

    This is the one tool that reaches budget and notes rows, and it does so
    without ever reading one: it deletes seeded rows by id from the sample-data
    manifest. No budget or note content is returned, and anything a person wrote
    is out of its reach by construction — which is why it does not breach the
    exclusion those two domains have from the tool surface."""
    async with AsyncSessionLocal() as db:
        decision = await authorize(db, ctx, "household", "write")
        if decision.proposed:
            return await _propose(
                db, decision, domain="household", tool="clear_sample_data", args={},
                summary="Clear the household's sample data",
            )
        return await _perform_clear_sample_data(db, decision)


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
