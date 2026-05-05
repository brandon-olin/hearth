import uuid

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
) -> GroceryListResponse | None:
    result = await db.execute(
        select(GroceryList).where(
            GroceryList.id == list_id, GroceryList.household_id == household_id
        )
    )
    grocery_list = result.scalar_one_or_none()
    if grocery_list is None:
        return None
    item_map = await _load_items(db, [grocery_list.id])
    return _build_response(grocery_list, item_map.get(grocery_list.id, []))


async def list_grocery_lists(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> GroceryListListResponse:
    query = select(GroceryList).where(GroceryList.household_id == household_id)
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
    for field in ("todo_id", "name", "store", "status"):
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
