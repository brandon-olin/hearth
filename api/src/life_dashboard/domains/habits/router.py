import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.habits.schemas import (
    HabitCreate,
    HabitListResponse,
    HabitUpdate,
    HabitWithStats,
    OccurrenceCreate,
    OccurrenceListResponse,
    OccurrenceResponse,
    OccurrenceUpdate,
)
from life_dashboard.domains.habits import service

router = APIRouter(prefix="/habits", tags=["habits"])


@router.get("", response_model=HabitListResponse)
async def list_habits(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HabitListResponse:
    return await service.list_habits(
        db, current_user.household_id, current_user.id,
        status=status, limit=limit, offset=offset,
    )


@router.get("/{habit_id}", response_model=HabitWithStats)
async def get_habit(
    habit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HabitWithStats:
    habit = await service.get_habit(db, habit_id, current_user.household_id, user_id=current_user.id)
    if habit is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Habit not found")
    return habit


@router.post("", response_model=HabitWithStats, status_code=http_status.HTTP_201_CREATED)
async def create_habit(
    data: HabitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HabitWithStats:
    habit = await service.create_habit(db, current_user.household_id, current_user.id, data)
    return HabitWithStats(**habit.model_dump(), current_streak=0)


@router.patch("/{habit_id}", response_model=HabitWithStats)
async def update_habit(
    habit_id: uuid.UUID,
    data: HabitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HabitWithStats:
    habit = await service.update_habit(db, habit_id, current_user.household_id, data)
    if habit is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Habit not found")
    # Re-fetch with stats so the response includes an up-to-date streak
    return await service.get_habit(db, habit.id, current_user.household_id, user_id=current_user.id) or habit


@router.delete("/{habit_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_habit(
    habit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_habit(db, habit_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Habit not found")


# ── Occurrences ───────────────────────────────────────────────────────────────

@router.get("/{habit_id}/occurrences", response_model=OccurrenceListResponse)
async def list_occurrences(
    habit_id: uuid.UUID,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OccurrenceListResponse:
    result = await service.list_occurrences(
        db, habit_id, current_user.household_id,
        from_date=from_date, to_date=to_date, status=status,
        limit=limit, offset=offset,
    )
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Habit not found")
    return result


@router.post(
    "/{habit_id}/occurrences",
    response_model=OccurrenceResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_occurrence(
    habit_id: uuid.UUID,
    data: OccurrenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OccurrenceResponse:
    result = await service.create_occurrence(db, habit_id, current_user.household_id, data)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Habit not found")
    return result


@router.patch("/{habit_id}/occurrences/{occurrence_id}", response_model=OccurrenceResponse)
async def update_occurrence(
    habit_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    data: OccurrenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OccurrenceResponse:
    result = await service.update_occurrence(
        db, habit_id, occurrence_id, current_user.household_id, data
    )
    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Occurrence not found"
        )
    return result


@router.delete(
    "/{habit_id}/occurrences/{occurrence_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def delete_occurrence(
    habit_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_occurrence(
        db, habit_id, occurrence_id, current_user.household_id
    )
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Occurrence not found"
        )
