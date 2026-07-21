"""Per-exercise progress service (workouts-004).

Progress history is PERSONAL. The exercise catalog is SHARED, which makes this
the exact place another member's numbers could bleed into your charts — so
every query here filters ``WorkoutSession.created_by_user_id == user_id``
alongside the household boundary. The filter is server-side by construction:
another member's sets are never sent to the client to be discarded there.

Two shapes of read:

* :func:`list_progress_exercises` — the exercises this member has logged in at
  least ``min_sessions`` sessions, most recently logged first, each with a
  sparkline over its last few sessions.
* :func:`get_exercise_progress` — the full time-series for one exercise,
  ordered oldest to newest.

Both apply the same definition of a data point:

* **Warmup sets are excluded entirely.** They are excluded from every
  calculation downstream (volume, max weight, 1RM, completion), so they never
  enter the payload in the first place.
* **Blank sets are excluded.** The logging UI creates set rows before they are
  filled in; a row with neither reps nor weight is not a data point. This also
  means ``duration``/``distance`` exercises (planks, running) do not appear —
  the three charts this feeds are reps/weight shaped.
* A session left with no working sets for the exercise after those filters does
  not count as a session for that exercise.

Every derived number (estimated 1RM via Epley, volume, max weight) is computed
client-side from this payload and is NEVER stored.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.service import _as_aware
from life_dashboard.domains.workouts.exercises_service import _visible_clause
from life_dashboard.domains.workouts.models import (
    Exercise,
    SessionExercise,
    WorkoutSession,
    WorkoutSet,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseProgressResponse,
    ExerciseResponse,
    ProgressExerciseListResponse,
    ProgressExerciseSummary,
    ProgressSession,
    ProgressSet,
)

#: How many trailing sessions the list-row sparkline covers.
SPARKLINE_POINTS = 5
#: An exercise needs this many logged sessions before it has a trend worth showing.
MIN_SESSIONS = 2


def _working_set_clause():
    """A set that counts: not a warmup, and something was actually logged."""
    return and_(
        WorkoutSet.is_warmup.is_(False),
        or_(WorkoutSet.reps.isnot(None), WorkoutSet.weight.isnot(None)),
    )


def _session_date(started_at: datetime) -> date:
    """UTC calendar date of a session. Sessions are anchored at noon UTC so this
    matches the day the client renders (which slices the ISO string)."""
    return _as_aware(started_at).astimezone(timezone.utc).date()


def _as_float(value) -> float | None:
    """Numeric columns come back as ``Decimal``; the schemas are floats."""
    return None if value is None else float(value)


async def get_exercise_progress(
    db: AsyncSession,
    exercise_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    limit: int = 20,
) -> ExerciseProgressResponse | None:
    """Time-series of ONE exercise for ONE member, oldest session to newest.

    Returns ``None`` when the exercise is not visible to the household (the
    router answers 404). Archived exercises still resolve — history must outlive
    a catalog edit. An exercise the member has never logged returns an empty
    ``sessions`` list rather than 404.
    """
    exercise = (
        await db.execute(
            select(Exercise).where(
                Exercise.id == exercise_id, _visible_clause(household_id)
            )
        )
    ).scalar_one_or_none()
    if exercise is None:
        return None

    # The most recent `limit` sessions that contain a working set of this
    # exercise. The owner filter here is what keeps the charts personal.
    recent = (
        await db.execute(
            select(WorkoutSession.id, WorkoutSession.started_at)
            .select_from(WorkoutSession)
            .join(SessionExercise, SessionExercise.session_id == WorkoutSession.id)
            .join(WorkoutSet, WorkoutSet.session_exercise_id == SessionExercise.id)
            .where(
                SessionExercise.exercise_id == exercise_id,
                WorkoutSession.household_id == household_id,
                WorkoutSession.created_by_user_id == user_id,
                _working_set_clause(),
            )
            .group_by(WorkoutSession.id, WorkoutSession.started_at)
            .order_by(WorkoutSession.started_at.desc(), WorkoutSession.id.desc())
            .limit(limit)
        )
    ).all()

    response = ExerciseProgressResponse(
        exercise=ExerciseResponse.model_validate(exercise), sessions=[]
    )
    if not recent:
        return response

    oldest_first = list(reversed(recent))
    session_ids = [sid for sid, _ in oldest_first]

    # One batched fetch for every set across those sessions — no per-session query.
    set_rows = (
        await db.execute(
            select(SessionExercise.session_id, WorkoutSet)
            .select_from(WorkoutSet)
            .join(SessionExercise, WorkoutSet.session_exercise_id == SessionExercise.id)
            .where(
                SessionExercise.session_id.in_(session_ids),
                SessionExercise.exercise_id == exercise_id,
                _working_set_clause(),
            )
            .order_by(SessionExercise.position.asc(), WorkoutSet.set_number.asc())
        )
    ).all()

    by_session: dict[uuid.UUID, list[ProgressSet]] = {}
    for session_id, ws in set_rows:
        by_session.setdefault(session_id, []).append(
            ProgressSet(
                reps=ws.reps,
                weight=_as_float(ws.weight),
                is_warmup=ws.is_warmup,
                target_reps=ws.target_reps,
            )
        )

    response.sessions = [
        ProgressSession(
            session_id=session_id,
            session_date=_session_date(started_at),
            sets=by_session.get(session_id, []),
        )
        for session_id, started_at in oldest_first
    ]
    return response


async def list_progress_exercises(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    min_sessions: int = MIN_SESSIONS,
    limit: int = 100,
) -> ProgressExerciseListResponse:
    """Exercises THIS member has logged in at least ``min_sessions`` sessions,
    most recently logged first.

    The list is personal for the same reason the charts are: the catalog is
    shared, so an exercise another member trained must not surface here.
    """
    # One row per (exercise, session) with that session's peak weight and reps.
    # Aggregating in SQL keeps the payload proportional to sessions, not sets;
    # the per-exercise grouping below is the same batch-then-group-in-Python
    # shape the habits list uses to avoid N+1 queries.
    rows = (
        await db.execute(
            select(
                SessionExercise.exercise_id,
                WorkoutSession.id,
                WorkoutSession.started_at,
                func.max(WorkoutSet.weight),
                func.max(WorkoutSet.reps),
            )
            .select_from(WorkoutSet)
            .join(SessionExercise, WorkoutSet.session_exercise_id == SessionExercise.id)
            .join(WorkoutSession, SessionExercise.session_id == WorkoutSession.id)
            .where(
                WorkoutSession.household_id == household_id,
                WorkoutSession.created_by_user_id == user_id,
                _working_set_clause(),
            )
            .group_by(
                SessionExercise.exercise_id,
                WorkoutSession.id,
                WorkoutSession.started_at,
            )
        )
    ).all()

    # exercise_id → [(started_at, max_weight, max_reps)], one entry per session.
    per_exercise: dict[uuid.UUID, list[tuple[datetime, float | None, int | None]]] = {}
    for exercise_id, _session_id, started_at, max_weight, max_reps in rows:
        per_exercise.setdefault(exercise_id, []).append(
            (_as_aware(started_at), _as_float(max_weight), max_reps)
        )

    qualifying = {
        exercise_id: sorted(points, key=lambda p: p[0])
        for exercise_id, points in per_exercise.items()
        if len(points) >= min_sessions
    }
    if not qualifying:
        return ProgressExerciseListResponse(items=[])

    exercises = (
        await db.execute(select(Exercise).where(Exercise.id.in_(qualifying.keys())))
    ).scalars().all()

    items: list[ProgressExerciseSummary] = []
    for exercise in exercises:
        points = qualifying[exercise.id]
        # Bodyweight = no logged working set ever carried a weight. The client
        # renders the reps chart only for these.
        is_bodyweight = all(weight is None for _, weight, _ in points)
        tail = points[-SPARKLINE_POINTS:]
        sparkline = [
            float(reps if is_bodyweight else weight)
            for _, weight, reps in tail
            if (reps if is_bodyweight else weight) is not None
        ]
        items.append(
            ProgressExerciseSummary(
                exercise_id=exercise.id,
                name=exercise.name,
                tracking_type=exercise.tracking_type,
                session_count=len(points),
                last_logged_at=points[-1][0],
                is_bodyweight=is_bodyweight,
                sparkline=sparkline,
            )
        )

    items.sort(key=lambda i: i.last_logged_at, reverse=True)
    return ProgressExerciseListResponse(items=items[:limit])
