import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.collections import service
from life_dashboard.domains.collections.schemas import (
    CollectionCreate,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
    EnsureTodayResponse,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.get("", response_model=CollectionListResponse)
async def list_collections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_collections(db, household_id=current_user.household_id)


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    data: CollectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.create_collection(
        db,
        household_id=current_user.household_id,
        user_id=current_user.id,
        data=data,
    )


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    col = await service.get_collection(
        db, collection_id=collection_id, household_id=current_user.household_id
    )
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    return col


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: uuid.UUID,
    data: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    col = await service.update_collection(
        db,
        collection_id=collection_id,
        household_id=current_user.household_id,
        data=data,
    )
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    return col


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await service.delete_collection(
        db, collection_id=collection_id, household_id=current_user.household_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")


@router.post("/{collection_id}/ensure-today", response_model=EnsureTodayResponse)
async def ensure_today(
    collection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Idempotent. Ensures an entry for today exists in the collection.
    Returns the item ID and whether it was freshly created.
    Returns 404 if the collection has no auto_create_rule.
    """
    result = await service.ensure_today_entry(
        db,
        collection_id=collection_id,
        household_id=current_user.household_id,
        user_id=current_user.id,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail="Collection not found or has no auto_create_rule",
        )
    return result
