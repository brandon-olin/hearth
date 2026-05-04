import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.contacts.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from life_dashboard.domains.contacts import service

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContactListResponse:
    return await service.list_contacts(
        db, current_user.household_id, search=search, limit=limit, offset=offset
    )


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContactResponse:
    contact = await service.get_contact(db, contact_id, current_user.household_id)
    if contact is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.post("", response_model=ContactResponse, status_code=http_status.HTTP_201_CREATED)
async def create_contact(
    data: ContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContactResponse:
    return await service.create_contact(db, current_user.household_id, current_user.id, data)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: uuid.UUID,
    data: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContactResponse:
    contact = await service.update_contact(db, contact_id, current_user.household_id, data)
    if contact is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.delete("/{contact_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_contact(db, contact_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Contact not found")
