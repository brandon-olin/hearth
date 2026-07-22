"""Weekly meal planner (meal-001).

Two ideas carry the whole domain:

1. **A week is addressed, not created.** Every read and write takes a date and
   normalises it to that week's Monday, and the plan row is get-or-created
   under a `UNIQUE(household_id, week_start)`. There is no "create plan" step a
   user can double-submit, and no way to end up with two plans for one week.

2. **Entries borrow the plan's scope.** `meal_plan_entries` has no household_id
   and no visibility of its own, so every entry operation loads the parent plan
   through the same visibility filter a read would use. An entry id alone never
   grants access to anything.
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.grocery_lists import service as grocery_service
from life_dashboard.domains.grocery_lists.schemas import GroceryListCreate
from life_dashboard.domains.meal_plans.models import MealPlan, MealPlanEntry
from life_dashboard.domains.meal_plans.schemas import (
    GenerateGroceryListRequest,
    GenerateGroceryListResponse,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntryResponse,
    MealPlanEntryUpdate,
    MealPlanListResponse,
    MealPlanResponse,
    MealPlanUpdate,
)
from life_dashboard.domains.recipes.models import Recipe
from life_dashboard.events import semantic


def week_start_for(day: date) -> date:
    """The Monday of *day*'s week.

    Every caller runs through here, so "the week of the 23rd" means one row no
    matter which day the client happened to send.
    """
    return day - timedelta(days=day.weekday())


# ── Loading ───────────────────────────────────────────────────────────────────

async def _load_entries(
    db: AsyncSession, plan_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[MealPlanEntryResponse]]:
    """Entries for several plans in one query, with recipe names joined in.

    The grid renders a name per cell; fetching each recipe separately would be
    an N+1 in the hottest read this domain has.
    """
    if not plan_ids:
        return {}
    rows = (await db.execute(
        select(MealPlanEntry, Recipe.name, Recipe.cover_image_url)
        .join(Recipe, Recipe.id == MealPlanEntry.recipe_id)
        .where(MealPlanEntry.plan_id.in_(plan_ids))
        .order_by(MealPlanEntry.entry_date, MealPlanEntry.sort_order)
    )).all()

    by_plan: dict[uuid.UUID, list[MealPlanEntryResponse]] = {}
    for entry, recipe_name, cover_url in rows:
        response = MealPlanEntryResponse.model_validate(entry)
        response.recipe_name = recipe_name
        response.recipe_cover_image_url = cover_url
        by_plan.setdefault(entry.plan_id, []).append(response)
    return by_plan


def _build_response(
    plan: MealPlan, entries: list[MealPlanEntryResponse]
) -> MealPlanResponse:
    response = MealPlanResponse.model_validate(plan)
    response.entries = entries
    return response


async def _visible_plan(
    db: AsyncSession, plan_id: uuid.UUID, household_id: uuid.UUID, user_id: uuid.UUID
) -> MealPlan | None:
    """The plan row, or None if it is not this household's or not visible."""
    query = apply_visibility_filter(
        select(MealPlan).where(
            MealPlan.id == plan_id, MealPlan.household_id == household_id
        ),
        MealPlan,
        user_id,
    )
    return (await db.execute(query)).scalar_one_or_none()


# ── Plans ─────────────────────────────────────────────────────────────────────

async def get_plan_for_week(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    day: date,
) -> MealPlanResponse | None:
    """The plan covering *day*'s week, or None if nothing is planned yet.

    None is the normal answer for an unplanned week, not an error — the grid
    renders empty and the first drag creates the plan.
    """
    monday = week_start_for(day)
    query = apply_visibility_filter(
        select(MealPlan).where(
            MealPlan.household_id == household_id, MealPlan.week_start == monday
        ),
        MealPlan,
        user_id,
    )
    plan = (await db.execute(query)).scalar_one_or_none()
    if plan is None:
        return None
    entry_map = await _load_entries(db, [plan.id])
    return _build_response(plan, entry_map.get(plan.id, []))


async def get_or_create_plan(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MealPlanCreate,
) -> MealPlanResponse:
    """Get-or-create the plan for a week. Safe to call repeatedly.

    The race between "not found" and "insert" is closed by the unique
    constraint, not by hoping the gap is small: a concurrent creator wins the
    insert and we re-read its row.
    """
    monday = week_start_for(data.week_start)
    existing = (await db.execute(
        select(MealPlan).where(
            MealPlan.household_id == household_id, MealPlan.week_start == monday
        )
    )).scalar_one_or_none()
    if existing is not None:
        entry_map = await _load_entries(db, [existing.id])
        return _build_response(existing, entry_map.get(existing.id, []))

    plan = MealPlan(
        household_id=household_id,
        created_by_user_id=user_id,
        week_start=monday,
        notes=data.notes,
        visibility=data.visibility,
        shared_with_user_ids=[str(u) for u in (data.shared_with_user_ids or [])],
    )
    db.add(plan)
    try:
        await db.flush()
    except IntegrityError:
        # Someone else created this week between the select and the insert.
        await db.rollback()
        plan = (await db.execute(
            select(MealPlan).where(
                MealPlan.household_id == household_id, MealPlan.week_start == monday
            )
        )).scalar_one()
        entry_map = await _load_entries(db, [plan.id])
        return _build_response(plan, entry_map.get(plan.id, []))

    await db.commit()
    await db.refresh(plan)
    return _build_response(plan, [])


async def list_plans(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> MealPlanListResponse:
    base = apply_visibility_filter(
        select(MealPlan).where(MealPlan.household_id == household_id),
        MealPlan,
        user_id,
    )
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    plans = list((await db.execute(
        base.order_by(MealPlan.week_start.desc()).limit(limit).offset(offset)
    )).scalars().all())
    entry_map = await _load_entries(db, [p.id for p in plans])
    return MealPlanListResponse(
        items=[_build_response(p, entry_map.get(p.id, [])) for p in plans],
        total=total,
    )


async def update_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MealPlanUpdate,
) -> MealPlanResponse | None:
    plan = await _visible_plan(db, plan_id, household_id, user_id)
    if plan is None:
        return None
    for field in data.model_fields_set:
        value = getattr(data, field)
        if field == "shared_with_user_ids" and value is not None:
            value = [str(u) for u in value]
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    entry_map = await _load_entries(db, [plan.id])
    return _build_response(plan, entry_map.get(plan.id, []))


async def delete_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    plan = await _visible_plan(db, plan_id, household_id, user_id)
    if plan is None:
        return False
    await db.delete(plan)          # entries cascade
    await db.commit()
    return True


# ── Entries ───────────────────────────────────────────────────────────────────

async def add_entry(
    db: AsyncSession,
    plan_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MealPlanEntryCreate,
) -> tuple[MealPlanEntryResponse | None, bool, str | None]:
    """Drop a recipe into a day+slot.

    Returns ``(entry, created, error)``. ``error`` is a human/agent-readable
    reason when the write is refused; ``entry`` is None only in that case.
    Idempotent: the same recipe dropped on the same cell twice returns the
    existing row with ``created=False`` rather than raising or duplicating.
    """
    plan = await _visible_plan(db, plan_id, household_id, user_id)
    if plan is None:
        return None, False, "Meal plan not found"

    recipe = (await db.execute(
        select(Recipe).where(
            Recipe.id == data.recipe_id, Recipe.household_id == household_id
        )
    )).scalar_one_or_none()
    if recipe is None:
        return None, False, "Recipe not found in this household"

    # A plan covers exactly one week; an entry outside it would be invisible in
    # the grid it belongs to and would quietly skew the grocery generation.
    if not (plan.week_start <= data.entry_date <= plan.week_start + timedelta(days=6)):
        return None, False, (
            f"entry_date {data.entry_date.isoformat()} is outside the plan week "
            f"({plan.week_start.isoformat()} to "
            f"{(plan.week_start + timedelta(days=6)).isoformat()})"
        )

    existing = (await db.execute(
        select(MealPlanEntry).where(
            MealPlanEntry.plan_id == plan_id,
            MealPlanEntry.entry_date == data.entry_date,
            MealPlanEntry.meal_slot == data.meal_slot,
            MealPlanEntry.recipe_id == data.recipe_id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        response = MealPlanEntryResponse.model_validate(existing)
        response.recipe_name = recipe.name
        response.recipe_cover_image_url = recipe.cover_image_url
        return response, False, None

    entry = MealPlanEntry(
        plan_id=plan_id,
        recipe_id=data.recipe_id,
        entry_date=data.entry_date,
        meal_slot=data.meal_slot,
        servings=data.servings,
        notes=data.notes,
        sort_order=data.sort_order,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError:
        # Lost the race with an identical concurrent drop — the unique
        # constraint says the intended state already exists, which is success.
        await db.rollback()
        existing = (await db.execute(
            select(MealPlanEntry).where(
                MealPlanEntry.plan_id == plan_id,
                MealPlanEntry.entry_date == data.entry_date,
                MealPlanEntry.meal_slot == data.meal_slot,
                MealPlanEntry.recipe_id == data.recipe_id,
            )
        )).scalar_one()
        response = MealPlanEntryResponse.model_validate(existing)
        response.recipe_name = recipe.name
        response.recipe_cover_image_url = recipe.cover_image_url
        return response, False, None

    semantic.record(
        db,
        event="meal.planned",
        entity_type="meal_plan_entry",
        entity_id=entry.id,
        descriptor_from=plan,          # entries have no scope of their own
        summary={
            "recipe_name": recipe.name,
            "entry_date": data.entry_date.isoformat(),
            "meal_slot": data.meal_slot,
        },
    )
    await db.commit()
    await db.refresh(entry)
    response = MealPlanEntryResponse.model_validate(entry)
    response.recipe_name = recipe.name
    response.recipe_cover_image_url = recipe.cover_image_url
    return response, True, None


async def update_entry(
    db: AsyncSession,
    plan_id: uuid.UUID,
    entry_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MealPlanEntryUpdate,
) -> MealPlanEntryResponse | None:
    """Move or re-scale a planned meal — the drag-to-another-cell case."""
    plan = await _visible_plan(db, plan_id, household_id, user_id)
    if plan is None:
        return None
    entry = (await db.execute(
        select(MealPlanEntry).where(
            MealPlanEntry.id == entry_id, MealPlanEntry.plan_id == plan_id
        )
    )).scalar_one_or_none()
    if entry is None:
        return None

    for field in data.model_fields_set:
        setattr(entry, field, getattr(data, field))

    # Read the destination cell off the in-memory row NOW, before any commit.
    # A rollback expires the instance, and the next attribute read would reload
    # the row's pre-move values from the database — so a survivor lookup done
    # after the rollback would search the cell the entry came *from*.
    target_recipe_id = entry.recipe_id
    target_date = entry.entry_date
    target_slot = entry.meal_slot

    if not (plan.week_start <= target_date <= plan.week_start + timedelta(days=6)):
        await db.rollback()
        return None

    try:
        await db.commit()
    except IntegrityError:
        # Dragged onto a cell that already holds this recipe. The destination is
        # already in the requested state, so collapse the two rows into it and
        # answer with the survivor — a merge, not a 500 and not a duplicate.
        await db.rollback()
        survivor = (await db.execute(
            select(MealPlanEntry).where(
                MealPlanEntry.plan_id == plan_id,
                MealPlanEntry.entry_date == target_date,
                MealPlanEntry.meal_slot == target_slot,
                MealPlanEntry.recipe_id == target_recipe_id,
                MealPlanEntry.id != entry_id,
            )
        )).scalar_one_or_none()
        await db.execute(
            sa_delete(MealPlanEntry).where(MealPlanEntry.id == entry_id)
        )
        await db.commit()
        if survivor is None:
            return None
        entry = survivor

    await db.refresh(entry)
    recipe_name = (await db.execute(
        select(Recipe.name).where(Recipe.id == entry.recipe_id)
    )).scalar_one_or_none()
    response = MealPlanEntryResponse.model_validate(entry)
    response.recipe_name = recipe_name
    return response


async def remove_entry(
    db: AsyncSession,
    plan_id: uuid.UUID,
    entry_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    plan = await _visible_plan(db, plan_id, household_id, user_id)
    if plan is None:
        return False
    result = await db.execute(
        sa_delete(MealPlanEntry).where(
            MealPlanEntry.id == entry_id, MealPlanEntry.plan_id == plan_id
        )
    )
    await db.commit()
    return result.rowcount > 0


# ── Grocery generation ────────────────────────────────────────────────────────

async def generate_grocery_list(
    db: AsyncSession,
    plan_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GenerateGroceryListRequest,
) -> tuple[GenerateGroceryListResponse | None, str | None]:
    """Turn a planned week into a shopping list.

    The aggregation itself lives in the grocery domain
    (:func:`grocery_service.add_recipes_to_list_aggregated`) — that is where
    "what belongs on a shopping list" is decided, and the planner is only one
    of its callers. Here we do the planner's part: which recipes, at what
    scale.

    Returns ``(response, error)``.
    """
    plan = await _visible_plan(db, plan_id, household_id, user_id)
    if plan is None:
        return None, "Meal plan not found"

    entries = list((await db.execute(
        select(MealPlanEntry)
        .where(MealPlanEntry.plan_id == plan_id)
        .order_by(MealPlanEntry.entry_date, MealPlanEntry.sort_order)
    )).scalars().all())
    if not entries:
        return None, "This week has no planned meals yet"

    # A recipe's own yield is the baseline; an entry's `servings` overrides it.
    # Loaded in one query — this is inside the plan's hottest write path.
    recipe_servings = dict((await db.execute(
        select(Recipe.id, Recipe.servings).where(
            Recipe.id.in_({e.recipe_id for e in entries})
        )
    )).all())

    # One tuple per planned meal, not per distinct recipe: the same dinner
    # twice in a week needs twice the ingredients.
    recipes = [
        (e.recipe_id, _servings_scale(e, recipe_servings.get(e.recipe_id)))
        for e in entries
    ]

    created_list = False
    if data.list_id is not None:
        target = await grocery_service.get_grocery_list(
            db, data.list_id, household_id, user_id=user_id
        )
        if target is None:
            return None, "Grocery list not found"
        list_id, list_name = target.id, target.name
    else:
        # Deterministic name, then get-or-create against it. Without this the
        # no-list_id path is the one call in the feature that is NOT idempotent:
        # a double-tap on "Generate grocery list" would leave the household with
        # two identical shopping lists and no hint which one to shop from.
        name = data.name or f"Week of {plan.week_start.isoformat()}"
        reused = await grocery_service.find_active_list_by_name(
            db, household_id, user_id, name
        )
        if reused is not None:
            list_id, list_name = reused.id, reused.name
        else:
            created = await grocery_service.create_grocery_list(
                db,
                household_id,
                user_id,
                GroceryListCreate(name=name, store=data.store, status="active"),
            )
            list_id, list_name = created.id, created.name
            created_list = True

    result = await grocery_service.add_recipes_to_list_aggregated(
        db, recipes=recipes, list_id=list_id, household_id=household_id
    )

    semantic.record(
        db,
        event="meal.grocery_list_generated",
        entity_type="meal_plan",
        entity_id=plan.id,
        descriptor_from=plan,
        summary={
            "week_start": plan.week_start.isoformat(),
            "list_id": str(list_id),
            "added": result["added"],
        },
    )
    await db.commit()

    return GenerateGroceryListResponse(
        list_id=list_id,
        list_name=list_name,
        created_list=created_list,
        recipes_planned=len(recipes),
        added=result["added"],
        skipped=result["skipped"],
        items=result["items"],
    ), None


def _servings_scale(entry: MealPlanEntry, recipe_servings: int | None) -> float:
    """How much of a recipe this planned meal needs, as a multiplier.

    An entry's ``servings`` is how many people this meal has to feed, so the
    multiplier is that over the recipe's own yield: 6 planned against a recipe
    for 4 is 1.5×. Without an override — or without a yield to compare against —
    the recipe is cooked as written.
    """
    if not entry.servings or not recipe_servings:
        return 1.0
    return float(entry.servings) / float(recipe_servings)
