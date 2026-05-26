import uuid

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.grocery_lists.models import GroceryItem, GroceryList
from life_dashboard.domains.grocery_lists.schemas import (
    GroceryItemData,
    GroceryItemResponse,
    GroceryItemUpdate,
    GroceryListCreate,
    GroceryListListResponse,
    GroceryListResponse,
    GroceryListUpdate,
)


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

    # Verify the parent list belongs to this household.
    owned = (await db.execute(
        select(GroceryList.id).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )).scalar_one_or_none()
    if owned is None:
        return None

    for field in data.model_fields_set:
        setattr(item, field, getattr(data, field))

    await db.commit()
    await db.refresh(item)
    return GroceryItemResponse.model_validate(item)


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
    from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient  # local to avoid circular import

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
