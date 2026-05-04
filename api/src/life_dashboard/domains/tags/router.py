import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.tags.schemas import (
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
)
from life_dashboard.domains.tags import service

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=TagListResponse)
async def list_tags(
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagListResponse:
    return await service.list_tags(
        db, current_user.household_id, search=search, limit=limit, offset=offset
    )


@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    tag = await service.get_tag(db, tag_id, current_user.household_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return tag


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    tag = await service.create_tag(db, current_user.household_id, data)
    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A tag named '{data.name}' already exists",
        )
    return tag


@router.patch("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: uuid.UUID,
    data: TagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    try:
        tag = await service.update_tag(db, tag_id, current_user.household_id, data)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tag with that name already exists",
        )
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_tag(db, tag_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
