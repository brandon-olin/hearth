import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.workouts.schemas import (
    ExerciseEntryCreate,
    ExerciseEntryResponse,
    ExerciseEntryUpdate,
    WorkoutCreate,
    WorkoutListResponse,
    WorkoutResponse,
    WorkoutUpdate,
    WorkoutWithEntriesResponse,
)
from life_dashboard.domains.workouts import service

router = APIRouter(prefix="/workouts", tags=["workouts"])


# ── Workouts ───────────────────────────────────────────────────────────────────

@router.get("", response_model=WorkoutListResponse)
async def list_workouts(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutListResponse:
    return await service.list_workouts(
        db,
        current_user.household_id,
        current_user.id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get("/exercise-names", response_model=list[str])
async def list_exercise_names(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return distinct exercise names used in this household, sorted alphabetically.
    Used to power autocomplete in the workout editor.
    """
    return await service.list_exercise_names(db, current_user.household_id)


@router.get("/{workout_id}", response_model=WorkoutWithEntriesResponse)
async def get_workout(
    workout_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutWithEntriesResponse:
    workout = await service.get_workout_with_entries(
        db, workout_id, current_user.household_id, user_id=current_user.id
    )
    if workout is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Workout not found"
        )
    return workout


@router.post("", response_model=WorkoutWithEntriesResponse, status_code=http_status.HTTP_201_CREATED)
async def create_workout(
    data: WorkoutCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutWithEntriesResponse:
    return await service.create_workout(
        db, current_user.household_id, current_user.id, data
    )


@router.patch("/{workout_id}", response_model=WorkoutResponse)
async def update_workout(
    workout_id: uuid.UUID,
    data: WorkoutUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutResponse:
    workout = await service.update_workout(
        db, workout_id, current_user.household_id, data
    )
    if workout is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Workout not found"
        )
    return workout


@router.delete("", status_code=200)
async def delete_all_workouts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all workouts for the current household."""
    count = await service.delete_all_workouts(db, current_user.household_id)
    return {"deleted": count}


@router.delete("/{workout_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_workout(
    workout_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_workout(db, workout_id, current_user.household_id)
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Workout not found"
        )


# ── Exercise entries ───────────────────────────────────────────────────────────

@router.post(
    "/{workout_id}/entries",
    response_model=ExerciseEntryResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_entry(
    workout_id: uuid.UUID,
    data: ExerciseEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseEntryResponse:
    entry = await service.create_entry(db, workout_id, current_user.household_id, data)
    if entry is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Workout not found"
        )
    return entry


@router.patch(
    "/{workout_id}/entries/{entry_id}",
    response_model=ExerciseEntryResponse,
)
async def update_entry(
    workout_id: uuid.UUID,
    entry_id: uuid.UUID,
    data: ExerciseEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseEntryResponse:
    entry = await service.update_entry(
        db, workout_id, entry_id, current_user.household_id, data
    )
    if entry is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Entry not found"
        )
    return entry


@router.delete(
    "/{workout_id}/entries/{entry_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def delete_entry(
    workout_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_entry(
        db, workout_id, entry_id, current_user.household_id
    )
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Entry not found"
        )
