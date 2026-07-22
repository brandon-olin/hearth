import uuid
from decimal import Decimal

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.grocery_lists.models import GroceryItem, GroceryList
from life_dashboard.domains.grocery_lists.schemas import (
    GroceryItemAdd,
    GroceryItemData,
    GroceryItemResponse,
    GroceryItemUpdate,
    GroceryListCreate,
    GroceryListListResponse,
    GroceryListResponse,
    GroceryListUpdate,
)
from life_dashboard.events import semantic

# ── Child loaders ─────────────────────────────────────────────────────────────

async def _load_items(
    db: AsyncSession, list_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[GroceryItem]]:
    if not list_ids:
        return {}
    rows = (await db.execute(
        select(GroceryItem).where(GroceryItem.list_id.in_(list_ids))
    )).scalars().all()
    item_map: dict[uuid.UUID, list[GroceryItem]] = {}
    for item in rows:
        item_map.setdefault(item.list_id, []).append(item)
    return item_map


def _build_response(
    grocery_list: GroceryList, items: list[GroceryItem]
) -> GroceryListResponse:
    return GroceryListResponse.model_validate(grocery_list).model_copy(update={
        "items": [GroceryItemResponse.model_validate(i) for i in items],
    })


async def _replace_items(
    db: AsyncSession, list_id: uuid.UUID, items: list[GroceryItemData]
) -> None:
    await db.execute(sa_delete(GroceryItem).where(GroceryItem.list_id == list_id))
    for item in items:
        db.add(GroceryItem(list_id=list_id, **item.model_dump()))


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_grocery_list(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GroceryListCreate,
) -> GroceryListResponse:
    grocery_list = GroceryList(
        household_id=household_id,
        created_by_user_id=user_id,
        todo_id=data.todo_id,
        name=data.name,
        store=data.store,
        status=data.status,
        visibility=data.visibility,
        shared_with_user_ids=data.shared_with_user_ids or [],
    )
    db.add(grocery_list)
    await db.flush()

    await _replace_items(db, grocery_list.id, data.items)

    await db.commit()
    await db.refresh(grocery_list)

    item_map = await _load_items(db, [grocery_list.id])
    return _build_response(grocery_list, item_map.get(grocery_list.id, []))


async def find_active_list_by_name(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
) -> GroceryListResponse | None:
    """The caller's most recent visible *active* list with this exact name.

    The get-half of a get-or-create for callers that generate a list under a
    deterministic name (meal-001's "Week of 2026-07-20"), so pressing the button
    twice targets one list instead of minting a second. Matched
    case-insensitively and only among active lists — a completed list is last
    week's shopping trip, not a target to append to.
    """
    query = apply_visibility_filter(
        select(GroceryList).where(
            GroceryList.household_id == household_id,
            GroceryList.status == "active",
            func.lower(GroceryList.name) == name.strip().lower(),
        ),
        GroceryList,
        user_id,
    )
    found = (await db.execute(
        query.order_by(GroceryList.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if found is None:
        return None
    item_map = await _load_items(db, [found.id])
    return _build_response(found, item_map.get(found.id, []))


async def get_grocery_list(
    db: AsyncSession,
    list_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> GroceryListResponse | None:
    query = select(GroceryList).where(
        GroceryList.id == list_id, GroceryList.household_id == household_id
    )
    if user_id is not None:
        query = apply_visibility_filter(query, GroceryList, user_id)
    grocery_list = (await db.execute(query)).scalar_one_or_none()
    if grocery_list is None:
        return None
    item_map = await _load_items(db, [grocery_list.id])
    return _build_response(grocery_list, item_map.get(grocery_list.id, []))


async def list_grocery_lists(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> GroceryListListResponse:
    query = select(GroceryList).where(GroceryList.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, GroceryList, user_id)
    if status is not None:
        query = query.where(GroceryList.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    lists = list(
        (await db.execute(
            query.order_by(GroceryList.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
    )

    ids = [gl.id for gl in lists]
    item_map = await _load_items(db, ids)
    return GroceryListListResponse(
        items=[_build_response(gl, item_map.get(gl.id, [])) for gl in lists],
        total=total, limit=limit, offset=offset,
    )


async def update_grocery_list(
    db: AsyncSession,
    list_id: uuid.UUID,
    household_id: uuid.UUID,
    data: GroceryListUpdate,
) -> GroceryListResponse | None:
    result = await db.execute(
        select(GroceryList).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )
    grocery_list = result.scalar_one_or_none()
    if grocery_list is None:
        return None

    sent = data.model_fields_set
    for field in ("todo_id", "name", "store", "status", "visibility", "shared_with_user_ids"):
        if field in sent:
            setattr(grocery_list, field, getattr(data, field))

    if "items" in sent and data.items is not None:
        await _replace_items(db, grocery_list.id, data.items)

    await db.commit()
    await db.refresh(grocery_list)

    item_map = await _load_items(db, [grocery_list.id])
    return _build_response(grocery_list, item_map.get(grocery_list.id, []))


async def delete_grocery_list(
    db: AsyncSession,
    list_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(GroceryList).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )
    grocery_list = result.scalar_one_or_none()
    if grocery_list is None:
        return False
    await db.delete(grocery_list)
    await db.commit()
    return True


# ── Individual item patch ─────────────────────────────────────────────────────

async def update_grocery_item(
    db: AsyncSession,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    household_id: uuid.UUID,
    data: GroceryItemUpdate,
) -> GroceryItemResponse | None:
    result = await db.execute(
        select(GroceryItem).where(
            GroceryItem.id == item_id, GroceryItem.list_id == list_id
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None

    # Verify the parent list belongs to this household. Loaded in full because
    # the check-off event below inherits its household_id and visibility.
    parent = (await db.execute(
        select(GroceryList).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )).scalar_one_or_none()
    if parent is None:
        return None

    was_checked = item.is_checked

    for field in data.model_fields_set:
        setattr(item, field, getattr(data, field))

    # Only the un-checked → checked transition is an event; re-checking an
    # already-checked item (a double-tap, a retried PATCH) emits nothing.
    if item.is_checked and not was_checked:
        semantic.record(
            db,
            event="grocery.item_checked",
            entity_type="grocery_item",
            entity_id=item.id,
            descriptor_from=parent,
            summary={
                "name": item.name,
                "quantity": item.quantity,
                "unit": item.unit,
                "category": item.category,
                "list_id": parent.id,
                "list_name": parent.name,
            },
        )

    await db.commit()
    await db.refresh(item)
    return GroceryItemResponse.model_validate(item)


async def add_grocery_item(
    db: AsyncSession,
    list_id: uuid.UUID,
    household_id: uuid.UUID,
    data: GroceryItemAdd,
) -> GroceryItemResponse | None:
    """Append a single item to a list without replacing the rest.

    The list-level PATCH replaces the whole items array, which a stateless
    caller (a Home Assistant rest_command, an agent) can't do in one shot —
    it would have to read, merge, and write back. This is the single-call
    "add milk to the list" primitive those callers need.

    Returns None if the list doesn't exist in this household (→ 404).
    """
    # The whole row, not just the id: grocery_items carries no household_id or
    # visibility of its own, so the semantic event below has to borrow the
    # parent list's descriptor (see events/semantic.py).
    parent = (await db.execute(
        select(GroceryList).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )).scalar_one_or_none()
    if parent is None:
        return None

    item = GroceryItem(list_id=list_id, **data.model_dump())
    db.add(item)
    await db.flush()  # get item.id before the event names it

    semantic.record(
        db,
        event="grocery.item_added",
        entity_type="grocery_item",
        entity_id=item.id,
        descriptor_from=parent,
        summary={
            "name": item.name,
            "quantity": item.quantity,
            "unit": item.unit,
            "category": item.category,
            "list_id": parent.id,
            "list_name": parent.name,
        },
    )

    await db.commit()
    await db.refresh(item)
    return GroceryItemResponse.model_validate(item)


async def add_grocery_item_idempotent(
    db: AsyncSession,
    list_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GroceryItemAdd,
) -> tuple[GroceryItemResponse | None, bool]:
    """Append an item, or return an existing un-checked item with the same name
    (case-insensitive) already on the list — a double-submit guard for stateless
    callers. "Add milk" twice yields one milk line, not two.

    The list must be visible to ``user_id`` — a member (or household-agent) token
    can only add to lists it is entitled to see, so an agent can't append to
    another member's personal list by guessing its id. Returns ``(item,
    created)``; ``item`` is None (→ 404) if the list is not in this household or
    not visible to the caller. A previously-checked-off item of the same name
    does not suppress a fresh add — re-adding milk after it was bought is real.
    """
    owned_query = apply_visibility_filter(
        select(GroceryList.id).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        ),
        GroceryList,
        user_id,
    )
    owned = (await db.execute(owned_query)).scalar_one_or_none()
    if owned is None:
        return None, False

    existing = (await db.execute(
        select(GroceryItem)
        .where(
            GroceryItem.list_id == list_id,
            func.lower(GroceryItem.name) == data.name.strip().lower(),
            GroceryItem.is_checked.is_(False),
        )
        .limit(1)
    )).scalar_one_or_none()
    if existing is not None:
        return GroceryItemResponse.model_validate(existing), False

    created = await add_grocery_item(db, list_id, household_id, data)
    return created, True


# ── Recipe → grocery list ─────────────────────────────────────────────────────

async def add_recipe_ingredients_to_list(
    db: AsyncSession,
    *,
    recipe_id: uuid.UUID,
    list_id: uuid.UUID,
    household_id: uuid.UUID,
    servings_scale: float = 1.0,
) -> dict[str, int]:
    """
    Append recipe ingredients to an existing grocery list.
    Ingredients whose recipe_ingredient_id is already in the list are skipped
    (idempotent — safe to call again if the user hits the button twice).
    Returns {"added": n, "skipped": m}.
    """
    from life_dashboard.domains.recipes.models import (  # local to avoid circular import
        Recipe,
        RecipeIngredient,
    )

    # Verify the recipe belongs to this household
    recipe = (await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.household_id == household_id)
    )).scalar_one_or_none()
    if recipe is None:
        raise ValueError("Recipe not found")

    # Verify the target grocery list belongs to this household
    grocery_list = (await db.execute(
        select(GroceryList).where(GroceryList.id == list_id, GroceryList.household_id == household_id)
    )).scalar_one_or_none()
    if grocery_list is None:
        raise ValueError("Grocery list not found")

    # Load recipe ingredients
    ingredients = list((await db.execute(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order)
    )).scalars().all())

    if not ingredients:
        return {"added": 0, "skipped": 0}

    # Find ingredient IDs already in this list
    existing_ids: set[uuid.UUID] = set(
        (await db.execute(
            select(GroceryItem.recipe_ingredient_id)
            .where(
                GroceryItem.list_id == list_id,
                GroceryItem.recipe_ingredient_id.in_([i.id for i in ingredients]),
            )
        )).scalars().all()
    )

    added = 0
    skipped = 0
    for ing in ingredients:
        if ing.id in existing_ids:
            skipped += 1
            continue
        qty = ing.quantity
        if qty is not None and servings_scale != 1.0:
            qty = float(qty) * servings_scale
        db.add(GroceryItem(
            list_id=list_id,
            name=ing.name,
            quantity=qty,
            unit=ing.unit,
            notes=ing.notes,
            recipe_id=recipe_id,
            recipe_ingredient_id=ing.id,
        ))
        added += 1

    await db.commit()
    return {"added": added, "skipped": skipped}


def _merge_key(name: str, unit: str | None) -> tuple[str, str]:
    """Two ingredient lines merge when they name the same thing in the same unit.

    Unit is part of the key on purpose: "2 cups flour" and "100 g flour" are the
    same ingredient but not addable quantities, and silently summing them would
    put a wrong number on the shopping list. They stay two lines.
    """
    return (name.strip().lower(), (unit or "").strip().lower())


async def add_recipes_to_list_aggregated(
    db: AsyncSession,
    *,
    recipes: list[tuple[uuid.UUID, float]],
    list_id: uuid.UUID,
    household_id: uuid.UUID,
) -> dict:
    """Append the ingredients of several recipes to one list, merging duplicates.

    This is the meal-planner's path (meal-001), and it differs from
    :func:`add_recipe_ingredients_to_list` in the one way that matters: that
    function dedupes by ``recipe_ingredient_id``, which is per-recipe, so two
    recipes that both call for garlic produce two garlic lines. Shopping for a
    week means shopping for garlic once. Lines are merged by (name, unit) across
    every recipe in the plan.

    ``recipes`` is a list of ``(recipe_id, servings_scale)`` — the same recipe
    planned twice in a week arrives twice and its quantities are counted twice,
    which is the correct answer for the shopper.

    Idempotent: a merged line whose name+unit is already on the list un-checked
    is skipped rather than re-added, so pressing "Generate" twice does not
    double the list. Returns ``{"added", "skipped", "items"}``.
    """
    from life_dashboard.domains.recipes.models import (  # local to avoid circular import
        Recipe,
        RecipeIngredient,
    )

    grocery_list = (await db.execute(
        select(GroceryList).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )).scalar_one_or_none()
    if grocery_list is None:
        raise ValueError("Grocery list not found")

    if not recipes:
        return {"added": 0, "skipped": 0, "items": []}

    # Only recipes that really belong to this household contribute — a planned
    # entry can outlive a recipe moved or removed, and a caller should never be
    # able to pull another household's ingredients through a plan.
    recipe_ids = [rid for rid, _ in recipes]
    owned_ids = set((await db.execute(
        select(Recipe.id).where(
            Recipe.id.in_(recipe_ids), Recipe.household_id == household_id
        )
    )).scalars().all())

    # One query for every ingredient of every planned recipe — not one per
    # recipe inside the loop below.
    rows = list((await db.execute(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id.in_(owned_ids))
        .order_by(RecipeIngredient.sort_order)
    )).scalars().all())
    by_recipe: dict[uuid.UUID, list] = {}
    for row in rows:
        by_recipe.setdefault(row.recipe_id, []).append(row)

    # Merge. `order` preserves first-seen ordering so the list reads like the
    # recipes did rather than in hash order.
    merged: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for recipe_id, scale in recipes:
        for ing in by_recipe.get(recipe_id, []):
            name = (ing.name or "").strip()
            if not name:
                continue
            key = _merge_key(name, ing.unit)
            qty = None
            if ing.quantity is not None:
                qty = Decimal(str(ing.quantity)) * Decimal(str(scale))
            if key not in merged:
                merged[key] = {
                    "name": name,
                    "unit": ing.unit,
                    "quantity": qty,
                    # Kept only while a single recipe contributes — see below.
                    "recipe_id": recipe_id,
                    "recipe_ingredient_id": ing.id,
                    "notes": ing.notes,
                    "from_recipes": 1,
                    "contributors": {recipe_id},
                }
                order.append(key)
                continue

            entry = merged[key]
            # An unquantified line ("salt, to taste") poisons the sum: there is
            # no honest total, so the merged line carries no quantity at all.
            if entry["quantity"] is None or qty is None:
                entry["quantity"] = None
            else:
                entry["quantity"] = entry["quantity"] + qty
            if recipe_id not in entry["contributors"]:
                entry["contributors"].add(recipe_id)
                entry["from_recipes"] += 1
            # Attribution only survives while one recipe owns the line. Pointing
            # a merged line at one of its several sources would be a lie the
            # "remove this recipe" path could act on.
            if entry["recipe_id"] != recipe_id:
                entry["recipe_id"] = None
                entry["recipe_ingredient_id"] = None
                entry["notes"] = None

    # Everything already on the list and not yet bought. Re-adding something the
    # shopper has already checked off is legitimate (it is a new week).
    existing = {
        _merge_key(name, unit)
        for name, unit in (await db.execute(
            select(GroceryItem.name, GroceryItem.unit).where(
                GroceryItem.list_id == list_id, GroceryItem.is_checked.is_(False)
            )
        )).all()
    }

    added = 0
    skipped = 0
    items: list[dict] = []
    for key in order:
        entry = merged[key]
        items.append({
            "name": entry["name"],
            "quantity": entry["quantity"],
            "unit": entry["unit"],
            "from_recipes": entry["from_recipes"],
        })
        if key in existing:
            skipped += 1
            continue
        db.add(GroceryItem(
            list_id=list_id,
            name=entry["name"],
            quantity=entry["quantity"],
            unit=entry["unit"],
            notes=entry["notes"],
            recipe_id=entry["recipe_id"],
            recipe_ingredient_id=entry["recipe_ingredient_id"],
        ))
        added += 1

    await db.commit()
    return {"added": added, "skipped": skipped, "items": items}
