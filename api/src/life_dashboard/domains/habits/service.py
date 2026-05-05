import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.habits.models import Habit, HabitOccurrence
from life_dashboard.domains.habits.schemas import (
    HabitCreate,
    HabitListResponse,
    HabitResponse,
    HabitUpdate,
    OccurrenceCreate,
    OccurrenceListResponse,
    OccurrenceResponse,
    OccurrenceUpdate,
)


def _habit_response(habit: Habit) -> HabitResponse:
    return HabitResponse.model_validate(habit)


def _occurrence_response(occ: HabitOccurrence) -> OccurrenceResponse:
    return OccurrenceResponse.model_validate(occ)


# ── Habits ────────────────────────────────────────────────────────────────────

async def create_habit(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: HabitCreate,
) -> HabitResponse:
    habit = Habit(
        household_id=household_id,
        created_by_user_id=user_id,
        goal_id=data.goal_id,
        name=data.name,
        description=data.description,
        frequency=data.frequency,
        cadence=data.cadence,
        status=data.status,
    )
    db.add(habit)
    await db.commit()
    await db.refresh(habit)
    return _habit_response(habit)


async def get_habit(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
) -> HabitResponse | None:
    result = await db.execute(
        select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    )
    habit = result.scalar_one_or_none()
    return _habit_response(habit) if habit else None


async def list_habits(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HabitListResponse:
    query = select(Habit).where(Habit.household_id == household_id)
    if status is not None:
        query = query.where(Habit.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    habits = list(
        (await db.execute(
            query.order_by(Habit.name.asc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return HabitListResponse(
        items=[_habit_response(h) for h in habits],
        total=total, limit=limit, offset=offset,
    )


async def update_habit(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
    data: HabitUpdate,
) -> HabitResponse | None:
    result = await db.execute(
        select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    )
    habit = result.scalar_one_or_none()
    if habit is None:
        return None

    for field in data.model_fields_set:
        setattr(habit, field, getattr(data, field))

    await db.commit()
    await db.refresh(habit)
    return _habit_response(habit)


async def delete_habit(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    )
    habit = result.scalar_one_or_none()
    if habit is None:
        return False
    await db.delete(habit)
    await db.commit()
    return True


# ── Occurrences ───────────────────────────────────────────────────────────────

async def _assert_habit_owned(
    db: AsyncSession, habit_id: uuid.UUID, household_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(Habit.id).where(Habit.id == habit_id, Habit.household_id == household_id)
    )
    return result.scalar_one_or_none() is not None


async def create_occurrence(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
    data: OccurrenceCreate,
) -> OccurrenceResponse | None:
    if not await _assert_habit_owned(db, habit_id, household_id):
        return None
    occ = HabitOccurrence(
        habit_id=habit_id,
        todo_id=data.todo_id,
        scheduled_date=data.scheduled_date,
        status=data.status,
        notes=data.notes,
    )
    db.add(occ)
    await db.commit()
    await db.refresh(occ)
    return _occurrence_response(occ)


async def list_occurrences(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> OccurrenceListResponse | None:
    if not await _assert_habit_owned(db, habit_id, household_id):
        return None

    query = select(HabitOccurrence).where(HabitOccurrence.habit_id == habit_id)
    if from_date is not None:
        query = query.where(HabitOccurrence.scheduled_date >= from_date)
    if to_date is not None:
        query = query.where(HabitOccurrence.scheduled_date <= to_date)
    if status is not None:
        query = query.where(HabitOccurrence.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    occs = list(
        (await db.execute(
            query.order_by(HabitOccurrence.scheduled_date.desc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return OccurrenceListResponse(
        items=[_occurrence_response(o) for o in occs],
        total=total, limit=limit, offset=offset,
    )


async def update_occurrence(
    db: AsyncSession,
    habit_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    household_id: uuid.UUID,
    data: OccurrenceUpdate,
) -> OccurrenceResponse | None:
    result = await db.execute(
        select(HabitOccurrence).where(
            HabitOccurrence.id == occurrence_id,
            HabitOccurrence.habit_id == habit_id,
        )
    )
    occ = result.scalar_one_or_none()
    if occ is None:
        return None

    # Verify the parent habit belongs to this household.
    if not await _assert_habit_owned(db, habit_id, household_id):
        return None

    for field in data.model_fields_set:
        setattr(occ, field, getattr(data, field))

    await db.commit()
    await db.refresh(occ)
    return _occurrence_response(occ)


async def delete_occurrence(
    db: AsyncSession,
    habit_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(HabitOccurrence).where(
            HabitOccurrence.id == occurrence_id,
            HabitOccurrence.habit_id == habit_id,
        )
    )
    occ = result.scalar_one_or_none()
    if occ is None:
        return False
    if not await _assert_habit_owned(db, habit_id, household_id):
        return False
    await db.delete(occ)
    await db.commit()
    return True
