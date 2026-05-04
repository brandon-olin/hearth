import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.calendar_events.schemas import (
    CalendarEventCreate,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventStatus,
    CalendarEventUpdate,
)
from life_dashboard.domains.calendar_events import service

router = APIRouter(prefix="/events", tags=["calendar_events"])


@router.get("", response_model=CalendarEventListResponse)
async def list_events(
    starts_after: datetime | None = Query(default=None),
    starts_before: datetime | None = Query(default=None),
    event_status: CalendarEventStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalendarEventListResponse:
    return await service.list_events(
        db, current_user.household_id,
        starts_after=starts_after, starts_before=starts_before,
        status=event_status, search=search, limit=limit, offset=offset,
    )


@router.get("/{event_id}", response_model=CalendarEventResponse)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalendarEventResponse:
    event = await service.get_event(db, event_id, current_user.household_id)
    if event is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


@router.post("", response_model=CalendarEventResponse, status_code=http_status.HTTP_201_CREATED)
async def create_event(
    data: CalendarEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalendarEventResponse:
    return await service.create_event(db, current_user.household_id, current_user.id, data)


@router.patch("/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: uuid.UUID,
    data: CalendarEventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CalendarEventResponse:
    event = await service.update_event(db, event_id, current_user.household_id, data)
    if event is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


@router.delete("/{event_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_event(db, event_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Event not found")
