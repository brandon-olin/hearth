import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.habits.models import Habit, HabitOccurrence
from life_dashboard.domains.habits.schemas import (
    HabitCreate,
    HabitListResponse,
    HabitResponse,
    HabitUpdate,
    HabitWithStats,
    OccurrenceCreate,
    OccurrenceListResponse,
    OccurrenceResponse,
    OccurrenceUpdate,
)


def _habit_response(habit: Habit) -> HabitResponse:
    return HabitResponse.model_validate(habit)


def _expected_in_period(
    frequency: str,
    cadence: dict | None,
    period_days: int,
    created_at: datetime,
) -> float:
    """Return how many completions are expected in a period of `period_days` ending today.

    Returns 0.0 if the habit hasn't been active for the full period (habit is
    newer than the window), which the caller treats as "no data" (None rate).

    When `cadence` contains `days_of_week`, the count is exact: we sum the
    number of matching weekdays in the actual active window.
    """
    today = date.today()
    cadence = cadence or {}
    times = max(1, int(cadence.get("times_per_period") or 1))

    # Honour the user-supplied start_date from cadence, falling back to created_at.
    start_str: str | None = cadence.get("start_date")
    if start_str:
        try:
            habit_start = date.fromisoformat(start_str)
        except ValueError:
            habit_start = created_at.date()
    else:
        habit_start = created_at.date()

    period_start = today - timedelta(days=period_days - 1)
    actual_start = max(period_start, habit_start)
    actual_days = (today - actual_start).days + 1

    if actual_days <= 0:
        return 0.0

    # days_of_week takes priority — count exactly how many matching days fall
    # in the active window regardless of the broad frequency label.
    days_of_week_raw = cadence.get("days_of_week")
    if days_of_week_raw:
        dow_set = {int(d) for d in days_of_week_raw}
        return float(
            sum(
                1
                for i in range(actual_days)
                if (actual_start + timedelta(days=i)).weekday() in dow_set
            )
        )

    if frequency == "daily":
        return float(actual_days)
    if frequency == "weekdays":
        return float(
            sum(
                1
                for i in range(actual_days)
                if (actual_start + timedelta(days=i)).weekday() < 5
            )
        )
    if frequency == "weekly":
        return (actual_days / 7) * times
    if frequency == "monthly":
        return (actual_days / 30) * times
    # custom / fallback: treat like daily
    return float(actual_days)


def _compute_streak(
    completed_dates: set[date],
    frequency: str,
    days_of_week: list[int] | None = None,
) -> int:
    """Return the current consecutive-period streak for a habit.

    When `days_of_week` is provided, the streak counts consecutive *scheduled*
    days (only the specified weekdays) rather than calendar days.  A grace
    period applies for today: if today is a scheduled day and is not yet
    completed, counting starts from the previous scheduled day.

    Without `days_of_week`, the streak is period-based (daily / weekly /
    monthly).
    """
    if not completed_dates:
        return 0

    today = date.today()

    # ── days-of-week-aware streak ──────────────────────────────────────────
    if days_of_week:
        dow_set = set(days_of_week)
        streak = 0
        grace_used = False
        cursor = today

        while cursor >= today - timedelta(days=365):
            if cursor.weekday() in dow_set:
                if cursor in completed_dates:
                    streak += 1
                elif cursor == today and not grace_used:
                    # Today is scheduled but not yet done — don't break streak
                    grace_used = True
                else:
                    break  # Missed a scheduled day → streak ends
            cursor -= timedelta(days=1)

        return streak

    # ── frequency-based streak ─────────────────────────────────────────────
    if frequency == "daily":
        streak = 0
        cursor = today if today in completed_dates else today - timedelta(days=1)
        while cursor in completed_dates:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    if frequency == "weekly":
        streak = 0
        # Start of current week (Monday = 0)
        week_start = today - timedelta(days=today.weekday())
        # If no completion this week, start counting from last week
        if not any(week_start <= d < week_start + timedelta(weeks=1) for d in completed_dates):
            week_start -= timedelta(weeks=1)
        while True:
            week_end = week_start + timedelta(weeks=1)
            if not any(week_start <= d < week_end for d in completed_dates):
                break
            streak += 1
            week_start -= timedelta(weeks=1)
        return streak

    if frequency == "monthly":
        streak = 0
        year, month = today.year, today.month
        # If no completion this month, start from last month
        if not any(d.year == year and d.month == month for d in completed_dates):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        while True:
            if not any(d.year == year and d.month == month for d in completed_dates):
                break
            streak += 1
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        return streak

    # custom / unknown — fall back to daily logic
    return _compute_streak(completed_dates, "daily")


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
        visibility=data.visibility,
        shared_with_user_ids=data.shared_with_user_ids or [],
    )
    db.add(habit)
    await db.commit()
    await db.refresh(habit)
    return _habit_response(habit)


async def get_habit(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> HabitWithStats | None:
    query = select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Habit, user_id)
    result = await db.execute(query)
    habit = result.scalar_one_or_none()
    if habit is None:
        return None
    lookback = date.today() - timedelta(days=90)
    occ_result = await db.execute(
        select(HabitOccurrence.scheduled_date)
        .where(
            HabitOccurrence.habit_id == habit.id,
            HabitOccurrence.scheduled_date >= lookback,
            HabitOccurrence.status == "completed",
        )
    )
    completed_dates = {row[0] for row in occ_result.all()}
    cadence_h = habit.cadence or {}
    dow = [int(d) for d in cadence_h.get("days_of_week") or []] or None
    streak = _compute_streak(completed_dates, habit.frequency, dow)
    return HabitWithStats(**_habit_response(habit).model_dump(), current_streak=streak)


async def list_habits(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HabitListResponse:
    query = select(Habit).where(Habit.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Habit, user_id)
    if status is not None:
        query = query.where(Habit.status == status)

    # Fetch all matching habits so we can filter by start_date in Python.
    # (start_date lives inside the JSONB cadence field, making a SQL-level filter
    # awkward; the list is small enough that Python-side filtering is fine.)
    all_habits = list(
        (await db.execute(
            query.order_by(Habit.name.asc())
        )).scalars().all()
    )

    # Filter out habits that haven't reached their start_date yet.
    today_date = date.today()
    def _has_started(h: Habit) -> bool:
        cadence_h = h.cadence or {}
        start_str: str | None = cadence_h.get("start_date")
        if not start_str:
            return True
        try:
            return date.fromisoformat(start_str) <= today_date
        except ValueError:
            return True

    started_habits = [h for h in all_habits if _has_started(h)]
    total = len(started_habits)
    habits = started_habits[offset : offset + limit]

    # Batch-load the last 90 days of completed occurrences for all returned habits
    # in a single query so we can compute streaks and rates without N+1 queries.
    streaks: dict[uuid.UUID, int] = {}
    rates_7d: dict[uuid.UUID, float | None] = {}
    rates_30d: dict[uuid.UUID, float | None] = {}

    if habits:
        habit_ids = [h.id for h in habits]
        lookback = date.today() - timedelta(days=90)
        occ_result = await db.execute(
            select(HabitOccurrence.habit_id, HabitOccurrence.scheduled_date)
            .where(
                HabitOccurrence.habit_id.in_(habit_ids),
                HabitOccurrence.scheduled_date >= lookback,
                HabitOccurrence.status == "completed",
            )
        )
        occs_by_habit: dict[uuid.UUID, set[date]] = {}
        for habit_id, sched_date in occ_result.all():
            occs_by_habit.setdefault(habit_id, set()).add(sched_date)

        today = date.today()
        window_7 = today - timedelta(days=6)   # last 7 days inclusive
        window_30 = today - timedelta(days=29)  # last 30 days inclusive

        for h in habits:
            completed = occs_by_habit.get(h.id, set())
            cadence_h = h.cadence or {}
            dow = [int(d) for d in cadence_h.get("days_of_week") or []] or None
            streaks[h.id] = _compute_streak(completed, h.frequency, dow)

            exp_7 = _expected_in_period(h.frequency, h.cadence, 7, h.created_at)
            exp_30 = _expected_in_period(h.frequency, h.cadence, 30, h.created_at)

            c7 = sum(1 for d in completed if d >= window_7)
            c30 = sum(1 for d in completed if d >= window_30)

            rates_7d[h.id] = (
                round(min(100.0, c7 / exp_7 * 100), 1) if exp_7 >= 1.0 else None
            )
            rates_30d[h.id] = (
                round(min(100.0, c30 / exp_30 * 100), 1) if exp_30 >= 1.0 else None
            )

    items = [
        HabitWithStats(
            **_habit_response(h).model_dump(),
            current_streak=streaks.get(h.id, 0),
            completion_rate_7d=rates_7d.get(h.id),
            completion_rate_30d=rates_30d.get(h.id),
        )
        for h in habits
    ]
    return HabitListResponse(items=items, total=total, limit=limit, offset=offset)


async def update_habit(
    db: AsyncSession,
    habit_id: uuid.UUID,
    household_id: uuid.UUID,
    data: HabitUpdate,
    user_id: uuid.UUID | None = None,
) -> HabitResponse | None:
    query = select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Habit, user_id)
    result = await db.execute(query)
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
    user_id: uuid.UUID | None = None,
) -> bool:
    query = select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Habit, user_id)
    result = await db.execute(query)
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
