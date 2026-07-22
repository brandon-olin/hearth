"""Tests for the semantic event layer (webhook-001).

Covers the first four verification steps of the feature:

  1. A completion publishes exactly one ``todo.completed`` — not a bare
     "todos row updated" — and the universal invalidation still fires for SSE.
  2. Child tables with no ``household_id`` (grocery_items, habit_occurrences)
     emit, borrowing their parent's household and visibility descriptor.
  3. A transaction that rolls back after queueing an event publishes nothing.
  4. ``events.scope.can_see`` is the one scope mechanism: it accepts both event
     kinds because it types on the shared visibility descriptor.
"""
import uuid
from datetime import UTC, date, datetime

import pytest

from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.visibility import (
    VISIBILITY_HOUSEHOLD,
    VISIBILITY_MEMBERS,
    VISIBILITY_PERSONAL,
)
from life_dashboard.domains.calendar_events import service as calendar_service
from life_dashboard.domains.calendar_events.schemas import CalendarEventCreate
from life_dashboard.domains.grocery_lists import service as grocery_service
from life_dashboard.domains.grocery_lists.models import GroceryList
from life_dashboard.domains.grocery_lists.schemas import GroceryItemAdd, GroceryItemUpdate
from life_dashboard.domains.habits import service as habits_service
from life_dashboard.domains.habits.models import Habit
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import TodoCreate, TodoUpdate
from life_dashboard.events import semantic
from life_dashboard.events.bus import InvalidationEvent, SemanticEvent, bus
from life_dashboard.events.scope import can_see

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _make_user(db, household=None) -> User:
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
    db.add(
        HouseholdMembership(
            household_id=household.id, user_id=user.id, role=MembershipRole.member
        )
    )
    await db.commit()
    user.household_id = household.id
    return user


def _drain(queue) -> list[SemanticEvent]:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def _drain_invalidations(queue) -> list[InvalidationEvent]:
    out = []
    while not queue.empty():
        item = queue.get_nowait()
        if isinstance(item, InvalidationEvent):
            out.append(item)
    return out


@pytest.fixture
def semantic_queue():
    queue = bus.subscribe_semantic()
    yield queue
    bus.unsubscribe_semantic(queue)


# ── Step: todo.created / todo.completed ───────────────────────────────────────

@pytest.mark.asyncio
async def test_todo_created_publishes_semantic_event(db_session, semantic_queue):
    user = await _make_user(db_session)
    _drain(semantic_queue)

    await todos_service.create_todo(
        db_session,
        user.household_id,
        user.id,
        TodoCreate(title="Take out bins"),
    )

    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["todo.created"]
    assert events[0].entity_type == "todo"
    assert events[0].summary["title"] == "Take out bins"
    assert events[0].household_id == user.household_id


@pytest.mark.asyncio
async def test_completion_publishes_todo_completed_and_still_invalidates(
    db_session, semantic_queue
):
    """A completion is a named event AND still a plain invalidation for SSE."""
    user = await _make_user(db_session)
    todo = await todos_service.create_todo(
        db_session, user.household_id, user.id, TodoCreate(title="Floss")
    )
    _drain(semantic_queue)
    invalidations = bus.subscribe(user.household_id)
    try:
        await todos_service.update_todo(
            db_session, todo.id, user.household_id, TodoUpdate(status="done")
        )

        events = _drain(semantic_queue)
        assert [e.event for e in events] == ["todo.completed"]
        assert events[0].entity_id == todo.id
        assert events[0].summary["completed_at"] is not None

        # The universal producer is untouched — SSE still sees the row change.
        invalidated = _drain_invalidations(invalidations)
        assert any(
            ev.entity_type == "todos" and ev.action == "updated" for ev in invalidated
        )
    finally:
        bus.unsubscribe(user.household_id, invalidations)


@pytest.mark.asyncio
async def test_repeated_done_patch_emits_once(db_session, semantic_queue):
    """A double-tap / retried PATCH must not emit a second completion."""
    user = await _make_user(db_session)
    todo = await todos_service.create_todo(
        db_session, user.household_id, user.id, TodoCreate(title="Water plants")
    )
    await todos_service.update_todo(
        db_session, todo.id, user.household_id, TodoUpdate(status="done")
    )
    _drain(semantic_queue)

    await todos_service.update_todo(
        db_session, todo.id, user.household_id, TodoUpdate(status="done")
    )
    assert _drain(semantic_queue) == []


@pytest.mark.asyncio
async def test_title_edit_does_not_emit_a_completion(db_session, semantic_queue):
    user = await _make_user(db_session)
    todo = await todos_service.create_todo(
        db_session, user.household_id, user.id, TodoCreate(title="Old title")
    )
    _drain(semantic_queue)

    await todos_service.update_todo(
        db_session, todo.id, user.household_id, TodoUpdate(title="New title")
    )
    assert _drain(semantic_queue) == []


# ── Step: child-table emits ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grocery_item_events_borrow_the_lists_household(db_session, semantic_queue):
    """grocery_items has no household_id — the event carries the list's."""
    user = await _make_user(db_session)
    glist = GroceryList(
        household_id=user.household_id,
        created_by_user_id=user.id,
        name="Weekly shop",
        visibility=VISIBILITY_HOUSEHOLD,
    )
    db_session.add(glist)
    await db_session.commit()
    _drain(semantic_queue)

    item = await grocery_service.add_grocery_item(
        db_session, glist.id, user.household_id, GroceryItemAdd(name="Milk")
    )
    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["grocery.item_added"]
    assert events[0].household_id == user.household_id
    assert events[0].entity_type == "grocery_item"
    assert events[0].entity_id == item.id
    assert events[0].summary["name"] == "Milk"
    assert events[0].summary["list_name"] == "Weekly shop"

    await grocery_service.update_grocery_item(
        db_session, glist.id, item.id, user.household_id, GroceryItemUpdate(is_checked=True)
    )
    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["grocery.item_checked"]

    # Re-checking an already-checked item is a no-op, not a second event.
    await grocery_service.update_grocery_item(
        db_session, glist.id, item.id, user.household_id, GroceryItemUpdate(is_checked=True)
    )
    assert _drain(semantic_queue) == []


@pytest.mark.asyncio
async def test_grocery_item_event_inherits_a_personal_lists_visibility(
    db_session, semantic_queue
):
    user = await _make_user(db_session)
    glist = GroceryList(
        household_id=user.household_id,
        created_by_user_id=user.id,
        name="Private list",
        visibility=VISIBILITY_PERSONAL,
    )
    db_session.add(glist)
    await db_session.commit()
    _drain(semantic_queue)

    await grocery_service.add_grocery_item(
        db_session, glist.id, user.household_id, GroceryItemAdd(name="Gift")
    )
    event = _drain(semantic_queue)[0]
    assert event.visibility == VISIBILITY_PERSONAL
    assert event.created_by_user_id == user.id


@pytest.mark.asyncio
async def test_habit_check_in_emits_with_the_habits_descriptor(db_session, semantic_queue):
    """habit_occurrences has no household_id — the event carries the habit's."""
    user = await _make_user(db_session)
    habit = Habit(
        household_id=user.household_id,
        created_by_user_id=user.id,
        name="Floss",
        visibility=VISIBILITY_PERSONAL,
    )
    db_session.add(habit)
    await db_session.commit()
    _drain(semantic_queue)

    occ, created = await habits_service.check_in_habit(
        db_session, habit.id, user.household_id, user.id, date(2026, 7, 21)
    )
    assert created is True
    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["habit.checked_in"]
    assert events[0].household_id == user.household_id
    assert events[0].entity_id == occ.id
    assert events[0].visibility == VISIBILITY_PERSONAL
    assert events[0].summary["habit_name"] == "Floss"

    # Idempotent re-check-in emits nothing.
    await habits_service.check_in_habit(
        db_session, habit.id, user.household_id, user.id, date(2026, 7, 21)
    )
    assert _drain(semantic_queue) == []


@pytest.mark.asyncio
async def test_calendar_event_created_emits(db_session, semantic_queue):
    user = await _make_user(db_session)
    _drain(semantic_queue)

    await calendar_service.create_event(
        db_session,
        user.household_id,
        user.id,
        CalendarEventCreate(
            title="Dentist", starts_at=datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
        ),
    )
    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["calendar.event_created"]
    assert events[0].summary["title"] == "Dentist"


# ── Step: rollback safety ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_discards_queued_semantic_events(db_session, semantic_queue):
    user = await _make_user(db_session)
    todo = Todo(household_id=user.household_id, created_by_user_id=user.id, title="Doomed")
    db_session.add(todo)
    await db_session.flush()
    semantic.record(
        db_session,
        event="todo.created",
        entity_type="todo",
        entity_id=todo.id,
        descriptor_from=todo,
        summary={"title": todo.title},
    )
    assert db_session.info.get(semantic.SEMANTIC_PENDING_KEY)

    await db_session.rollback()

    assert not db_session.info.get(semantic.SEMANTIC_PENDING_KEY)
    assert _drain(semantic_queue) == []

    # A later, unrelated commit must not resurrect the discarded event.
    await db_session.commit()
    assert _drain(semantic_queue) == []


# ── Step: one scope mechanism for both event kinds ────────────────────────────

def _semantic(**kw) -> SemanticEvent:
    return SemanticEvent(
        household_id=kw.get("household_id", uuid.uuid4()),
        event="todo.created",
        entity_type="todo",
        entity_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        summary={},
        visibility=kw.get("visibility", VISIBILITY_HOUSEHOLD),
        created_by_user_id=kw.get("created_by_user_id"),
        shared_with_user_ids=kw.get("shared_with_user_ids", ()),
    )


def test_can_see_accepts_semantic_events_with_identical_rules():
    """The SSE filter and the webhook filter are the same function, by design."""
    owner, other = uuid.uuid4(), uuid.uuid4()

    assert can_see(_semantic(visibility=VISIBILITY_HOUSEHOLD), other) is True

    personal = _semantic(visibility=VISIBILITY_PERSONAL, created_by_user_id=owner)
    assert can_see(personal, owner) is True
    assert can_see(personal, other) is False

    members = _semantic(
        visibility=VISIBILITY_MEMBERS,
        created_by_user_id=owner,
        shared_with_user_ids=(str(other),),
    )
    assert can_see(members, other) is True
    assert can_see(members, uuid.uuid4()) is False

    # Unknown visibility denies rather than leaking.
    assert can_see(_semantic(visibility="galaxy-brain"), owner) is False


def test_can_see_gives_the_same_answer_for_both_event_kinds():
    owner, other = uuid.uuid4(), uuid.uuid4()
    hid = uuid.uuid4()
    invalidation = InvalidationEvent(
        household_id=hid,
        entity_type="todos",
        entity_id=uuid.uuid4(),
        action="created",
        visibility=VISIBILITY_PERSONAL,
        created_by_user_id=owner,
    )
    semantic_event = _semantic(
        household_id=hid, visibility=VISIBILITY_PERSONAL, created_by_user_id=owner
    )
    for user_id in (owner, other):
        assert can_see(invalidation, user_id) == can_see(semantic_event, user_id)


# ── Step: meal.planned / meal.grocery_list_generated (meal-001) ───────────────

@pytest.mark.asyncio
async def test_planning_a_meal_publishes_a_semantic_event(db_session, semantic_queue):
    """Registration is not delivery: the event has to reach the bus, carrying
    the parent plan's household and visibility (entries have neither)."""
    from life_dashboard.domains.meal_plans import service as meal_service
    from life_dashboard.domains.meal_plans.schemas import (
        MealPlanCreate,
        MealPlanEntryCreate,
    )
    from life_dashboard.domains.recipes.models import Recipe

    user = await _make_user(db_session)
    recipe = Recipe(
        household_id=user.household_id, created_by_user_id=user.id,
        name="Chili", visibility=VISIBILITY_HOUSEHOLD,
    )
    db_session.add(recipe)
    await db_session.commit()

    plan = await meal_service.get_or_create_plan(
        db_session, user.household_id, user.id,
        MealPlanCreate(week_start=date(2026, 7, 22)),
    )
    _drain(semantic_queue)

    await meal_service.add_entry(
        db_session, plan.id, user.household_id, user.id,
        MealPlanEntryCreate(
            recipe_id=recipe.id, entry_date=date(2026, 7, 22), meal_slot="dinner"
        ),
    )

    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["meal.planned"]
    assert events[0].entity_type == "meal_plan_entry"
    assert events[0].summary["recipe_name"] == "Chili"
    assert events[0].summary["meal_slot"] == "dinner"
    # Borrowed from the plan — an entry has no household_id of its own.
    assert events[0].household_id == user.household_id
    # And a household member is entitled to see it.
    assert can_see(events[0], user.id)


@pytest.mark.asyncio
async def test_generating_a_grocery_list_publishes_a_semantic_event(
    db_session, semantic_queue
):
    from life_dashboard.domains.meal_plans import service as meal_service
    from life_dashboard.domains.meal_plans.schemas import (
        GenerateGroceryListRequest,
        MealPlanCreate,
        MealPlanEntryCreate,
    )
    from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient

    user = await _make_user(db_session)
    recipe = Recipe(
        household_id=user.household_id, created_by_user_id=user.id,
        name="Chili", visibility=VISIBILITY_HOUSEHOLD,
    )
    db_session.add(recipe)
    await db_session.flush()
    db_session.add(RecipeIngredient(recipe_id=recipe.id, name="beans", sort_order=0))
    await db_session.commit()

    plan = await meal_service.get_or_create_plan(
        db_session, user.household_id, user.id,
        MealPlanCreate(week_start=date(2026, 7, 22)),
    )
    await meal_service.add_entry(
        db_session, plan.id, user.household_id, user.id,
        MealPlanEntryCreate(
            recipe_id=recipe.id, entry_date=date(2026, 7, 22), meal_slot="dinner"
        ),
    )
    _drain(semantic_queue)

    result, error = await meal_service.generate_grocery_list(
        db_session, plan.id, user.household_id, user.id, GenerateGroceryListRequest()
    )
    assert error is None

    events = _drain(semantic_queue)
    names = [e.event for e in events]
    assert "meal.grocery_list_generated" in names
    generated = next(e for e in events if e.event == "meal.grocery_list_generated")
    assert generated.summary["list_id"] == str(result.list_id)
    assert generated.summary["added"] == result.added


# ── meal-001: the planner's bus events ────────────────────────────────────────
#
# These are the meal planner's agent surface for the half that has no MCP tool
# (grocery generation), so "it is in the catalog" is not enough — the events have
# to actually reach the bus, carry the parent plan's scope, and stay idempotent.

async def _planned_week(db, user):
    """A plan with one recipe on Wednesday, and the recipe's id."""
    from life_dashboard.domains.meal_plans import service as meal_service
    from life_dashboard.domains.meal_plans.schemas import MealPlanCreate, MealPlanEntryCreate
    from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient

    recipe = Recipe(
        household_id=user.household_id, created_by_user_id=user.id,
        name="Chili", visibility=VISIBILITY_HOUSEHOLD,
    )
    db.add(recipe)
    await db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, name="beans", unit="can", sort_order=0))
    await db.commit()

    plan = await meal_service.get_or_create_plan(
        db, user.household_id, user.id, MealPlanCreate(week_start=date(2026, 7, 22))
    )
    return meal_service, MealPlanEntryCreate, plan, recipe


@pytest.mark.asyncio
async def test_planning_a_meal_publishes_meal_planned(db_session, semantic_queue):
    user = await _make_user(db_session)
    meal_service, EntryCreate, plan, recipe = await _planned_week(db_session, user)
    _drain(semantic_queue)

    entry, created, error = await meal_service.add_entry(
        db_session, plan.id, user.household_id, user.id,
        EntryCreate(recipe_id=recipe.id, entry_date=date(2026, 7, 22), meal_slot="dinner"),
    )
    assert created is True and error is None

    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["meal.planned"]
    assert events[0].entity_type == "meal_plan_entry"
    assert events[0].entity_id == entry.id
    assert events[0].household_id == user.household_id
    assert events[0].summary["recipe_name"] == "Chili"
    assert events[0].summary["meal_slot"] == "dinner"
    # Entries carry no scope of their own — this is the plan's, borrowed.
    assert events[0].visibility == VISIBILITY_HOUSEHOLD


@pytest.mark.asyncio
async def test_replanning_the_same_cell_emits_once(db_session, semantic_queue):
    """An idempotent write must have an idempotent event."""
    user = await _make_user(db_session)
    meal_service, EntryCreate, plan, recipe = await _planned_week(db_session, user)
    payload = EntryCreate(
        recipe_id=recipe.id, entry_date=date(2026, 7, 22), meal_slot="dinner"
    )
    await meal_service.add_entry(db_session, plan.id, user.household_id, user.id, payload)
    _drain(semantic_queue)

    await meal_service.add_entry(db_session, plan.id, user.household_id, user.id, payload)
    assert _drain(semantic_queue) == []


@pytest.mark.asyncio
async def test_generating_a_grocery_list_publishes_its_event(db_session, semantic_queue):
    from life_dashboard.domains.meal_plans.schemas import GenerateGroceryListRequest

    user = await _make_user(db_session)
    meal_service, EntryCreate, plan, recipe = await _planned_week(db_session, user)
    await meal_service.add_entry(
        db_session, plan.id, user.household_id, user.id,
        EntryCreate(recipe_id=recipe.id, entry_date=date(2026, 7, 22), meal_slot="dinner"),
    )
    _drain(semantic_queue)

    result, error = await meal_service.generate_grocery_list(
        db_session, plan.id, user.household_id, user.id, GenerateGroceryListRequest()
    )
    assert error is None

    events = _drain(semantic_queue)
    assert [e.event for e in events] == ["meal.grocery_list_generated"]
    assert events[0].entity_type == "meal_plan"
    assert events[0].entity_id == plan.id
    assert events[0].summary["list_id"] == str(result.list_id)
    assert events[0].summary["added"] == result.added


@pytest.mark.asyncio
async def test_meal_events_deliver_only_the_allowlisted_fields(db_session):
    """The summary is a proposal; webhooks/summaries.py decides what leaves."""
    from life_dashboard.webhooks.summaries import filter_summary

    planned = filter_summary("meal.planned", {
        "recipe_name": "Chili", "entry_date": "2026-07-22", "meal_slot": "dinner",
        "plan_id": "leak-me", "notes": "secret",
    })
    assert planned == {
        "recipe_name": "Chili", "entry_date": "2026-07-22", "meal_slot": "dinner",
    }

    generated = filter_summary("meal.grocery_list_generated", {
        "week_start": "2026-07-20", "list_id": "abc", "added": 4,
        "items": ["beans", "garlic"],          # the shopping list never leaves
    })
    assert generated == {"week_start": "2026-07-20", "list_id": "abc", "added": 4}
