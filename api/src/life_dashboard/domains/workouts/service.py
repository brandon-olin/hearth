import uuid
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.workouts.models import ExerciseEntry, Workout
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


# ── Internal helpers ───────────────────────────────────────────────────────────

def _workout_response(workout: Workout) -> WorkoutResponse:
    return WorkoutResponse.model_validate(workout)


def _entry_response(entry: ExerciseEntry) -> ExerciseEntryResponse:
    return ExerciseEntryResponse.model_validate(entry)


async def _assert_workout_owned(
    db: AsyncSession,
    workout_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    """Return True if the workout exists and belongs to this household."""
    result = await db.execute(
        select(Workout.id).where(
            Workout.id == workout_id,
            Workout.household_id == household_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _load_entries(
    db: AsyncSession,
    workout_id: uuid.UUID,
) -> list[ExerciseEntry]:
    """Bulk-load exercise entries for one workout, ordered by sort_order."""
    result = await db.execute(
        select(ExerciseEntry)
        .where(ExerciseEntry.workout_id == workout_id)
        .order_by(ExerciseEntry.sort_order.asc(), ExerciseEntry.created_at.asc())
    )
    return list(result.scalars().all())


# ── Workouts ───────────────────────────────────────────────────────────────────

async def list_workouts(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> WorkoutListResponse:
    query = select(Workout).where(Workout.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Workout, user_id)
    if from_date is not None:
        query = query.where(Workout.workout_date >= from_date)
    if to_date is not None:
        query = query.where(Workout.workout_date <= to_date)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    workouts = list(
        (
            await db.execute(
                query.order_by(Workout.workout_date.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
    )

    # Batch-load exercise names for all returned workouts in one query so the
    # list card can show "Bench · Squat · Deadlift" without N+1 fetches.
    workout_ids = [w.id for w in workouts]
    names_by_workout: dict[uuid.UUID, list[str]] = {w.id: [] for w in workouts}
    if workout_ids:
        entries_result = await db.execute(
            select(ExerciseEntry.workout_id, ExerciseEntry.name)
            .where(ExerciseEntry.workout_id.in_(workout_ids))
            .order_by(ExerciseEntry.workout_id, ExerciseEntry.sort_order.asc(), ExerciseEntry.created_at.asc())
        )
        for workout_id, name in entries_result.all():
            names_by_workout[workout_id].append(name)

    items = [
        _workout_response(w).model_copy(update={"exercise_names": names_by_workout[w.id]})
        for w in workouts
    ]
    return WorkoutListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


async def list_exercise_names(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> list[str]:
    """Return distinct exercise names used in this household, sorted alphabetically."""
    result = await db.execute(
        select(ExerciseEntry.name)
        .join(Workout, ExerciseEntry.workout_id == Workout.id)
        .where(Workout.household_id == household_id)
        .distinct()
        .order_by(ExerciseEntry.name.asc())
    )
    return [row[0] for row in result.all() if row[0]]


async def get_workout(
    db: AsyncSession,
    workout_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> WorkoutResponse | None:
    query = select(Workout).where(
        Workout.id == workout_id,
        Workout.household_id == household_id,
    )
    if user_id is not None:
        query = apply_visibility_filter(query, Workout, user_id)
    workout = (await db.execute(query)).scalar_one_or_none()
    return _workout_response(workout) if workout else None


async def get_workout_with_entries(
    db: AsyncSession,
    workout_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> WorkoutWithEntriesResponse | None:
    query = select(Workout).where(
        Workout.id == workout_id,
        Workout.household_id == household_id,
    )
    if user_id is not None:
        query = apply_visibility_filter(query, Workout, user_id)
    workout = (await db.execute(query)).scalar_one_or_none()
    if workout is None:
        return None

    entries = await _load_entries(db, workout_id)
    # Inject the loaded entries without triggering any lazy load.
    response = WorkoutWithEntriesResponse.model_validate(workout)
    return response.model_copy(update={"entries": [_entry_response(e) for e in entries]})


async def create_workout(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkoutCreate,
) -> WorkoutWithEntriesResponse:
    workout = Workout(
        household_id=household_id,
        created_by_user_id=user_id,
        name=data.name,
        workout_date=data.workout_date,
        notes=data.notes,
        # Workouts are always personal — visibility is not user-configurable.
        visibility="personal",
        shared_with_user_ids=[],
    )
    db.add(workout)
    await db.flush()  # populate workout.id before creating entries

    entries: list[ExerciseEntry] = []
    for i, entry_data in enumerate(data.entries):
        entry = ExerciseEntry(
            workout_id=workout.id,
            name=entry_data.name,
            type=entry_data.type,
            sort_order=entry_data.sort_order if entry_data.sort_order != 0 else i,
            metrics=entry_data.metrics,
            notes=entry_data.notes,
        )
        db.add(entry)
        entries.append(entry)

    await db.commit()
    await db.refresh(workout)
    for entry in entries:
        await db.refresh(entry)

    response = WorkoutWithEntriesResponse.model_validate(workout)
    return response.model_copy(update={"entries": [_entry_response(e) for e in entries]})


async def update_workout(
    db: AsyncSession,
    workout_id: uuid.UUID,
    household_id: uuid.UUID,
    data: WorkoutUpdate,
) -> WorkoutResponse | None:
    result = await db.execute(
        select(Workout).where(
            Workout.id == workout_id,
            Workout.household_id == household_id,
        )
    )
    workout = result.scalar_one_or_none()
    if workout is None:
        return None

    for field in data.model_fields_set:
        setattr(workout, field, getattr(data, field))

    await db.commit()
    await db.refresh(workout)
    return _workout_response(workout)


async def delete_workout(
    db: AsyncSession,
    workout_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Workout).where(
            Workout.id == workout_id,
            Workout.household_id == household_id,
        )
    )
    workout = result.scalar_one_or_none()
    if workout is None:
        return False
    await db.delete(workout)
    await db.commit()
    return True


async def delete_all_workouts(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> int:
    """Delete every workout (and its entries via cascade) for this household."""
    result = await db.execute(
        delete(Workout)
        .where(Workout.household_id == household_id)
        .returning(Workout.id)
    )
    deleted = len(result.fetchall())
    await db.commit()
    return deleted


# ── Exercise entries ───────────────────────────────────────────────────────────

async def create_entry(
    db: AsyncSession,
    workout_id: uuid.UUID,
    household_id: uuid.UUID,
    data: ExerciseEntryCreate,
) -> ExerciseEntryResponse | None:
    if not await _assert_workout_owned(db, workout_id, household_id):
        return None

    # Default sort_order: append after current last entry.
    sort_order = data.sort_order
    if sort_order == 0:
        count_result = await db.execute(
            select(func.count()).where(ExerciseEntry.workout_id == workout_id)
        )
        sort_order = count_result.scalar_one()

    entry = ExerciseEntry(
        workout_id=workout_id,
        name=data.name,
        type=data.type,
        sort_order=sort_order,
        metrics=data.metrics,
        notes=data.notes,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_response(entry)


async def update_entry(
    db: AsyncSession,
    workout_id: uuid.UUID,
    entry_id: uuid.UUID,
    household_id: uuid.UUID,
    data: ExerciseEntryUpdate,
) -> ExerciseEntryResponse | None:
    if not await _assert_workout_owned(db, workout_id, household_id):
        return None

    result = await db.execute(
        select(ExerciseEntry).where(
            ExerciseEntry.id == entry_id,
            ExerciseEntry.workout_id == workout_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None

    for field in data.model_fields_set:
        setattr(entry, field, getattr(data, field))

    await db.commit()
    await db.refresh(entry)
    return _entry_response(entry)


async def delete_entry(
    db: AsyncSession,
    workout_id: uuid.UUID,
    entry_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    if not await _assert_workout_owned(db, workout_id, household_id):
        return False

    result = await db.execute(
        select(ExerciseEntry).where(
            ExerciseEntry.id == entry_id,
            ExerciseEntry.workout_id == workout_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True
