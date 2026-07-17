import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import (
    check_permission,
    get_item_creator,
    load_household_permissions,
)
from life_dashboard.domains.grocery_lists.models import GroceryList
from life_dashboard.domains.grocery_lists.schemas import (
    GroceryItemAdd,
    GroceryItemResponse,
    GroceryItemUpdate,
    GroceryListCreate,
    GroceryListListResponse,
    GroceryListResponse,
    GroceryListUpdate,
)
from life_dashboard.domains.grocery_lists import service

router = APIRouter(prefix="/grocery-lists", tags=["grocery_lists"])


@router.get("", response_model=GroceryListListResponse)
async def list_grocery_lists(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GroceryListListResponse:
    return await service.list_grocery_lists(
        db, current_user.household_id, current_user.id,
        status=status, limit=limit, offset=offset,
    )


@router.get("/{list_id}", response_model=GroceryListResponse)
async def get_grocery_list(
    list_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GroceryListResponse:
    grocery_list = await service.get_grocery_list(db, list_id, current_user.household_id, user_id=current_user.id)
    if grocery_list is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )
    return grocery_list


@router.post("", response_model=GroceryListResponse, status_code=http_status.HTTP_201_CREATED)
async def create_grocery_list(
    data: GroceryListCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GroceryListResponse:
    perms = await load_household_permissions(db, current_user.household_id)
    if not check_permission(perms, "grocery", "create", current_user.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create grocery lists.",
        )
    return await service.create_grocery_list(
        db, current_user.household_id, current_user.id, data
    )


@router.patch("/{list_id}", response_model=GroceryListResponse)
async def update_grocery_list(
    list_id: uuid.UUID,
    data: GroceryListUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GroceryListResponse:
    creator_id = await get_item_creator(db, GroceryList, list_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "grocery", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit others' grocery lists.",
            )
    grocery_list = await service.update_grocery_list(
        db, list_id, current_user.household_id, data
    )
    if grocery_list is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )
    return grocery_list


@router.delete("/{list_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_grocery_list(
    list_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    creator_id = await get_item_creator(db, GroceryList, list_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "grocery", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete others' grocery lists.",
            )
    deleted = await service.delete_grocery_list(db, list_id, current_user.household_id)
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )


@router.post(
    "/{list_id}/items",
    response_model=GroceryItemResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def add_grocery_item(
    list_id: uuid.UUID,
    data: GroceryItemAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GroceryItemResponse:
    # Appending an item is a collaborative action on a shared list — same
    # permission model as item updates: allowed on your own list, otherwise
    # gated behind grocery.manage_others. This is the single-call primitive
    # Home Assistant / agents use to "add milk to the list" (a scoped PAT with
    # grocery:write reaches it via the /grocery-lists scope mapping).
    creator_id = await get_item_creator(db, GroceryList, list_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "grocery", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit this grocery list.",
            )
    item = await service.add_grocery_item(
        db, list_id, current_user.household_id, data
    )
    if item is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Grocery list not found"
        )
    return item


@router.patch("/{list_id}/items/{item_id}", response_model=GroceryItemResponse)
async def update_grocery_item(
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    data: GroceryItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GroceryItemResponse:
    # Item-level updates (check/uncheck, quantity changes) use the list's manage_others
    # permission — these are collaborative actions on a shared list.
    creator_id = await get_item_creator(db, GroceryList, list_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "grocery", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit this grocery list.",
            )
    item = await service.update_grocery_item(
        db, list_id, item_id, current_user.household_id, data
    )
    if item is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    return item
