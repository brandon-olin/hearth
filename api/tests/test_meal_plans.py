"""meal-001 — the weekly meal planner and its grocery generation.

The interesting behaviour is all in two places: a week is addressed rather than
created (so nothing double-submits into two plans), and the grocery generator
merges ingredients *across* recipes — which is precisely what the pre-existing
per-recipe helper cannot do.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from life_dashboard.auth.models import Household, User
from life_dashboard.core.visibility import VISIBILITY_HOUSEHOLD, VISIBILITY_PERSONAL
from life_dashboard.domains.grocery_lists import service as grocery_service
from life_dashboard.domains.grocery_lists.models import GroceryItem
from life_dashboard.domains.meal_plans import service
from life_dashboard.domains.meal_plans.schemas import (
    GenerateGroceryListRequest,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntryUpdate,
)
from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient

# 2026-07-22 is a Wednesday; its week starts Monday the 20th.
WEDNESDAY = date(2026, 7, 22)
MONDAY = date(2026, 7, 20)


async def _household(db):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    alice = User(email="a@example.com", password_hash="x", display_name="Alice")
    bob = User(email="b@example.com", password_hash="x", display_name="Bob")
    db.add_all([alice, bob])
    await db.flush()
    return hh, alice, bob


async def _recipe(db, hh, user, name, ingredients, *, servings=None,
                  visibility=VISIBILITY_HOUSEHOLD):
    """A recipe plus its ingredient rows. ``ingredients`` is (name, qty, unit)."""
    recipe = Recipe(
        household_id=hh.id, created_by_user_id=user.id, name=name,
        servings=servings, visibility=visibility,
    )
    db.add(recipe)
    await db.flush()
    for i, (ing_name, qty, unit) in enumerate(ingredients):
        db.add(RecipeIngredient(
            recipe_id=recipe.id, name=ing_name,
            quantity=None if qty is None else Decimal(str(qty)),
            unit=unit, sort_order=i,
        ))
    await db.flush()
    return recipe


async def _items_on(db, list_id):
    rows = (await db.execute(
        select(GroceryItem).where(GroceryItem.list_id == list_id)
    )).scalars().all()
    return {(r.name.lower(), (r.unit or "").lower()): r for r in rows}


# ── Weeks ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("day", [date(2026, 7, 20), WEDNESDAY, date(2026, 7, 26)])
async def test_any_day_in_the_week_addresses_the_same_plan(db_session, day):
    hh, alice, _ = await _household(db_session)
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=day)
    )
    assert plan.week_start == MONDAY

    again = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    assert again.id == plan.id      # get-or-create, never a second row


async def test_unplanned_week_reads_as_none(db_session):
    hh, alice, _ = await _household(db_session)
    assert await service.get_plan_for_week(db_session, hh.id, alice.id, WEDNESDAY) is None


async def test_plan_is_visible_to_another_household_member(db_session):
    """A plan only its author could see would be useless to whoever cooks."""
    hh, alice, bob = await _household(db_session)
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    seen = await service.get_plan_for_week(db_session, hh.id, bob.id, WEDNESDAY)
    assert seen is not None and seen.id == plan.id


async def test_personal_plan_is_not_visible_to_another_member(db_session):
    hh, alice, bob = await _household(db_session)
    await service.get_or_create_plan(
        db_session, hh.id, alice.id,
        MealPlanCreate(week_start=WEDNESDAY, visibility=VISIBILITY_PERSONAL),
    )
    assert await service.get_plan_for_week(db_session, hh.id, bob.id, WEDNESDAY) is None
    assert await service.get_plan_for_week(db_session, hh.id, alice.id, WEDNESDAY)


# ── Entries ───────────────────────────────────────────────────────────────────

async def test_planning_the_same_cell_twice_is_idempotent(db_session):
    hh, alice, _ = await _household(db_session)
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    payload = MealPlanEntryCreate(
        recipe_id=recipe.id, entry_date=WEDNESDAY, meal_slot="dinner"
    )

    first, created, error = await service.add_entry(
        db_session, plan.id, hh.id, alice.id, payload
    )
    assert created is True and error is None
    second, created_again, _ = await service.add_entry(
        db_session, plan.id, hh.id, alice.id, payload
    )
    assert created_again is False
    assert second.id == first.id


async def test_same_recipe_on_two_days_is_two_entries(db_session):
    hh, alice, _ = await _household(db_session)
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    for day in (WEDNESDAY, date(2026, 7, 23)):
        _, created, _ = await service.add_entry(
            db_session, plan.id, hh.id, alice.id,
            MealPlanEntryCreate(recipe_id=recipe.id, entry_date=day, meal_slot="dinner"),
        )
        assert created is True

    week = await service.get_plan_for_week(db_session, hh.id, alice.id, WEDNESDAY)
    assert len(week.entries) == 2


async def test_entry_outside_the_plan_week_is_refused(db_session):
    hh, alice, _ = await _household(db_session)
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    entry, created, error = await service.add_entry(
        db_session, plan.id, hh.id, alice.id,
        MealPlanEntryCreate(
            recipe_id=recipe.id, entry_date=date(2026, 8, 5), meal_slot="dinner"
        ),
    )
    assert entry is None and created is False
    assert "outside the plan week" in error


async def test_recipe_from_another_household_is_refused(db_session):
    hh, alice, _ = await _household(db_session)
    other_hh = Household(name="Other")
    db_session.add(other_hh)
    await db_session.flush()
    foreign = await _recipe(db_session, other_hh, alice, "Not yours", [("x", 1, "cup")])

    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    entry, _, error = await service.add_entry(
        db_session, plan.id, hh.id, alice.id,
        MealPlanEntryCreate(
            recipe_id=foreign.id, entry_date=WEDNESDAY, meal_slot="dinner"
        ),
    )
    assert entry is None
    assert "not found" in error.lower()


async def test_entry_moves_between_cells(db_session):
    hh, alice, _ = await _household(db_session)
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    entry, _, _ = await service.add_entry(
        db_session, plan.id, hh.id, alice.id,
        MealPlanEntryCreate(recipe_id=recipe.id, entry_date=WEDNESDAY, meal_slot="dinner"),
    )
    moved = await service.update_entry(
        db_session, plan.id, entry.id, hh.id, alice.id,
        MealPlanEntryUpdate(entry_date=date(2026, 7, 24), meal_slot="lunch"),
    )
    assert moved.entry_date == date(2026, 7, 24)
    assert moved.meal_slot == "lunch"


async def test_moving_onto_an_occupied_cell_merges_into_it(db_session):
    """The destination already holds this recipe, so the move collapses into it.

    Regression guard: the survivor lookup has to use the *destination* cell. It
    runs after a rollback, which expires the entry, so reading entry.entry_date
    there would reload the row's pre-move values and search the origin cell —
    finding nothing and 404-ing a move that actually succeeded.
    """
    hh, alice, _ = await _household(db_session)
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])
    # Bound up front on purpose: the merge below rolls back, and a rollback
    # expires every ORM object in this shared test session regardless of
    # expire_on_commit. Reading hh.id afterwards would be lazy IO from a sync
    # frame — a fixture artifact, not something a request-scoped session hits.
    hh_id, alice_id = hh.id, alice.id
    plan = await service.get_or_create_plan(
        db_session, hh_id, alice_id, MealPlanCreate(week_start=WEDNESDAY)
    )
    thursday = date(2026, 7, 23)
    origin, _, _ = await service.add_entry(
        db_session, plan.id, hh_id, alice_id,
        MealPlanEntryCreate(recipe_id=recipe.id, entry_date=WEDNESDAY, meal_slot="dinner"),
    )
    destination, _, _ = await service.add_entry(
        db_session, plan.id, hh_id, alice_id,
        MealPlanEntryCreate(recipe_id=recipe.id, entry_date=thursday, meal_slot="dinner"),
    )

    merged = await service.update_entry(
        db_session, plan.id, origin.id, hh_id, alice_id,
        MealPlanEntryUpdate(entry_date=thursday, meal_slot="dinner"),
    )
    assert merged is not None
    assert merged.id == destination.id
    assert merged.entry_date == thursday

    week = await service.get_plan_for_week(db_session, hh_id, alice_id, WEDNESDAY)
    assert [e.id for e in week.entries] == [destination.id]


async def test_entry_of_an_invisible_plan_cannot_be_removed(db_session):
    """An entry id alone grants nothing — the parent plan's scope decides."""
    hh, alice, bob = await _household(db_session)
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id,
        MealPlanCreate(week_start=WEDNESDAY, visibility=VISIBILITY_PERSONAL),
    )
    entry, _, _ = await service.add_entry(
        db_session, plan.id, hh.id, alice.id,
        MealPlanEntryCreate(recipe_id=recipe.id, entry_date=WEDNESDAY, meal_slot="dinner"),
    )
    assert await service.remove_entry(db_session, plan.id, entry.id, hh.id, bob.id) is False
    assert await service.remove_entry(db_session, plan.id, entry.id, hh.id, alice.id) is True


# ── Grocery generation ────────────────────────────────────────────────────────

async def _planned_week(db, hh, user):
    """Two recipes sharing garlic (same unit) and olive oil (different units)."""
    chili = await _recipe(db, hh, user, "Chili", [
        ("garlic", 2, "cloves"),
        ("olive oil", 2, "tbsp"),
        ("beans", 1, "can"),
        ("salt", None, None),
    ])
    pasta = await _recipe(db, hh, user, "Pasta", [
        ("garlic", 3, "cloves"),
        ("olive oil", 50, "ml"),
        ("spaghetti", 500, "g"),
        ("salt", None, None),
    ])
    plan = await service.get_or_create_plan(
        db, hh.id, user.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    for recipe, day in ((chili, WEDNESDAY), (pasta, date(2026, 7, 23))):
        await service.add_entry(
            db, plan.id, hh.id, user.id,
            MealPlanEntryCreate(
                recipe_id=recipe.id, entry_date=day, meal_slot="dinner"
            ),
        )
    return plan, chili, pasta


async def test_shared_ingredient_combines_rather_than_duplicating(db_session):
    hh, alice, _ = await _household(db_session)
    plan, _, _ = await _planned_week(db_session, hh, alice)

    result, error = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    assert error is None
    assert result.created_list is True
    assert result.recipes_planned == 2

    items = await _items_on(db_session, result.list_id)
    # 5 garlic cloves on ONE line, not two lines of 2 and 3.
    assert items[("garlic", "cloves")].quantity == Decimal("5")
    assert len([k for k in items if k[0] == "garlic"]) == 1

    # Different units cannot be summed honestly, so they stay separate lines.
    assert items[("olive oil", "tbsp")].quantity == Decimal("2")
    assert items[("olive oil", "ml")].quantity == Decimal("50")

    # An unquantified line in either recipe leaves the merged line unquantified
    # rather than inventing a total.
    assert items[("salt", "")].quantity is None

    garlic_line = next(i for i in result.items if i.name == "garlic")
    assert garlic_line.from_recipes == 2


async def test_generating_twice_does_not_double_the_list(db_session):
    hh, alice, _ = await _household(db_session)
    plan, _, _ = await _planned_week(db_session, hh, alice)

    first, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    second, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id,
        GenerateGroceryListRequest(list_id=first.list_id),
    )
    assert second.added == 0
    assert second.skipped == first.added

    items = await _items_on(db_session, first.list_id)
    assert items[("garlic", "cloves")].quantity == Decimal("5")   # not 10


async def test_generating_twice_without_a_list_id_reuses_the_same_list(db_session):
    """The button sends no list_id, so this is the path a double-tap takes."""
    hh, alice, _ = await _household(db_session)
    plan, _, _ = await _planned_week(db_session, hh, alice)

    first, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    second, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    assert second.list_id == first.list_id
    assert second.created_list is False
    assert second.added == 0

    lists = await grocery_service.list_grocery_lists(db_session, hh.id, alice.id)
    assert lists.total == 1
    items = await _items_on(db_session, first.list_id)
    assert items[("garlic", "cloves")].quantity == Decimal("5")   # not 10


async def test_generating_twice_without_a_target_reuses_one_list(db_session):
    """The double-tap case. Without get-or-create on the generated name this is
    the one path in the feature that mints a second list every press."""
    hh, alice, _ = await _household(db_session)
    plan, _, _ = await _planned_week(db_session, hh, alice)

    first, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    second, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    assert first.created_list is True
    assert second.created_list is False
    assert second.list_id == first.list_id
    assert second.added == 0 and second.skipped == first.added

    all_lists = await grocery_service.list_grocery_lists(db_session, hh.id, alice.id)
    assert all_lists.total == 1

    items = await _items_on(db_session, first.list_id)
    assert items[("garlic", "cloves")].quantity == Decimal("5")   # not 10


async def test_removed_recipe_no_longer_contributes(db_session):
    hh, alice, _ = await _household(db_session)
    plan, _, pasta = await _planned_week(db_session, hh, alice)

    week = await service.get_plan_for_week(db_session, hh.id, alice.id, WEDNESDAY)
    pasta_entry = next(e for e in week.entries if e.recipe_id == pasta.id)
    assert await service.remove_entry(
        db_session, plan.id, pasta_entry.id, hh.id, alice.id
    )

    result, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id,
        GenerateGroceryListRequest(name="After removal"),
    )
    items = await _items_on(db_session, result.list_id)
    assert ("spaghetti", "g") not in items              # pasta-only ingredient
    assert items[("garlic", "cloves")].quantity == Decimal("2")   # chili's share only


async def test_servings_override_scales_quantities(db_session):
    """An entry's servings is how many people it feeds, against the recipe's own
    yield — 6 planned against a recipe for 4 is 1.5x the ingredients."""
    hh, alice, _ = await _household(db_session)
    recipe = await _recipe(
        db_session, hh, alice, "Stew", [("carrots", 4, "whole")], servings=4
    )
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    await service.add_entry(
        db_session, plan.id, hh.id, alice.id,
        MealPlanEntryCreate(
            recipe_id=recipe.id, entry_date=WEDNESDAY, meal_slot="dinner", servings=6
        ),
    )
    result, _ = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    items = await _items_on(db_session, result.list_id)
    assert items[("carrots", "whole")].quantity == Decimal("6")


async def test_empty_week_generates_nothing(db_session):
    hh, alice, _ = await _household(db_session)
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    result, error = await service.generate_grocery_list(
        db_session, plan.id, hh.id, alice.id, GenerateGroceryListRequest()
    )
    assert result is None
    assert "no planned meals" in error


async def test_generate_on_an_invisible_plan_is_refused(db_session):
    hh, alice, bob = await _household(db_session)
    plan = await service.get_or_create_plan(
        db_session, hh.id, alice.id,
        MealPlanCreate(week_start=WEDNESDAY, visibility=VISIBILITY_PERSONAL),
    )
    result, error = await service.generate_grocery_list(
        db_session, plan.id, hh.id, bob.id, GenerateGroceryListRequest()
    )
    assert result is None and "not found" in error.lower()


async def test_plan_of_another_household_is_not_reachable(db_session):
    hh, alice, _ = await _household(db_session)
    other_hh = Household(name="Other")
    db_session.add(other_hh)
    await db_session.flush()
    foreign_plan = await service.get_or_create_plan(
        db_session, other_hh.id, alice.id, MealPlanCreate(week_start=WEDNESDAY)
    )
    recipe = await _recipe(db_session, hh, alice, "Chili", [("beans", 2, "cups")])

    entry, _, error = await service.add_entry(
        db_session, foreign_plan.id, hh.id, alice.id,
        MealPlanEntryCreate(
            recipe_id=recipe.id, entry_date=WEDNESDAY, meal_slot="dinner"
        ),
    )
    assert entry is None and "not found" in error.lower()


async def test_events_are_registered_in_the_catalog(db_session):
    """A semantic event outside webhooks/summaries.py is published to nobody."""
    from life_dashboard.webhooks.summaries import is_known_event

    assert is_known_event("meal.planned")
    assert is_known_event("meal.grocery_list_generated")


async def test_meals_scope_maps_to_the_meal_plans_router(db_session):
    """A router unmapped in pat_scopes is unreachable with a PAT — deny by
    default. This is the line that makes the MCP tools usable at all."""
    from life_dashboard.auth.pat_scopes import resolve_required_scope

    assert resolve_required_scope("/meal-plans", "GET") == ("meals", "read")
    assert resolve_required_scope(
        f"/meal-plans/{uuid.uuid4()}/entries", "POST"
    ) == ("meals", "write")
