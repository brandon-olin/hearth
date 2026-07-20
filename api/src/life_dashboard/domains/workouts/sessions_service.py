"""Workout session service (workouts-001).

Sessions are PERSONAL. Every read filters ``created_by_user_id == user_id`` in
addition to the household boundary — a member never sees another member's logs,
and there is deliberately no per-session visibility control. The household_id
column is retained so household deletion cascades and exports stay
household-shaped.

Sessions materialize their own ``session_exercises`` and ``workout_sets`` at
start (optionally seeded from a template), so a later template deletion cannot
destroy history. FK cascades on delete are performed explicitly for the SQLite
tier (no FK enforcement there — see delete_session).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.workouts.exercises_service import _visible_clause
from life_dashboard.domains.workouts.models import (
    Exercise,
    SessionExercise,
    TemplateExercise,
    WorkoutSession,
    WorkoutSet,
    WorkoutTemplate,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseResponse,
    SessionExerciseCreate,
    SessionExerciseResponse,
    WorkoutSessionCreate,
    WorkoutSessionDetailResponse,
    WorkoutSessionListResponse,
    WorkoutSessionResponse,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetResponse,
    WorkoutSetUpdate,
)
from life_dashboard.domains.workouts.superset import (
    SupersetError,
    assert_capacity_for_join,
    dissolve_if_orphaned,
)

# ── Internal helpers ────────────────────────────────────────────────────────

async def _load_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkoutSession | None:
    """Load a session scoped to household AND owner. The owner filter is what
    makes sessions personal."""
    return (
        await db.execute(
            select(WorkoutSession).where(
                WorkoutSession.id == session_id,
                WorkoutSession.household_id == household_id,
                WorkoutSession.created_by_user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def _assert_exercise_visible(
    db: AsyncSession, exercise_id: uuid.UUID, household_id: uuid.UUID
) -> None:
    ok = (
        await db.execute(
            select(Exercise.id).where(
                Exercise.id == exercise_id,
                _visible_clause(household_id),
                Exercise.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if ok is None:
        raise SupersetError("Exercise not found or not visible to this household.")


def _validate_group_sizes(group_ids: list[uuid.UUID | None]) -> None:
    counts: dict[uuid.UUID, int] = {}
    for gid in group_ids:
        if gid is not None:
            counts[gid] = counts.get(gid, 0) + 1
    for gid, n in counts.items():
        if n > 5:
            raise SupersetError(
                f"A superset can hold at most 5 exercises; group {gid} has {n}."
            )


def _build_set(se_id: uuid.UUID, set_number: int, s: WorkoutSetCreate) -> WorkoutSet:
    return WorkoutSet(
        session_exercise_id=se_id,
        set_number=s.set_number if s.set_number is not None else set_number,
        reps=s.reps,
        target_reps=s.target_reps,
        duration_seconds=s.duration_seconds,
        weight=s.weight,
        weight_unit=s.weight_unit,
        distance_meters=s.distance_meters,
        distance_unit=s.distance_unit,
        rest_seconds=s.rest_seconds,
        is_warmup=s.is_warmup,
        rpe=s.rpe,
        completed_at=s.completed_at,
    )


async def _load_detail(
    db: AsyncSession, session: WorkoutSession
) -> WorkoutSessionDetailResponse:
    """Assemble the full session tree (exercises → sets) with each exercise
    attached, all batch-loaded to avoid N+1."""
    ses = (
        await db.execute(
            select(SessionExercise)
            .where(SessionExercise.session_id == session.id)
            .order_by(SessionExercise.position.asc(), SessionExercise.created_at.asc())
        )
    ).scalars().all()

    ex_by_id: dict[uuid.UUID, Exercise] = {}
    sets_by_se: dict[uuid.UUID, list[WorkoutSetResponse]] = {}
    if ses:
        ex_ids = {s.exercise_id for s in ses}
        ex_by_id = {
            e.id: e
            for e in (
                await db.execute(select(Exercise).where(Exercise.id.in_(ex_ids)))
            ).scalars().all()
        }
        se_ids = [s.id for s in ses]
        set_rows = (
            await db.execute(
                select(WorkoutSet)
                .where(WorkoutSet.session_exercise_id.in_(se_ids))
                .order_by(WorkoutSet.set_number.asc(), WorkoutSet.created_at.asc())
            )
        ).scalars().all()
        for row in set_rows:
            sets_by_se.setdefault(row.session_exercise_id, []).append(
                WorkoutSetResponse.model_validate(row)
            )

    exercises = []
    for se in ses:
        resp = SessionExerciseResponse.model_validate(se)
        ex = ex_by_id.get(se.exercise_id)
        exercises.append(
            resp.model_copy(
                update={
                    "exercise": ExerciseResponse.model_validate(ex) if ex else None,
                    "sets": sets_by_se.get(se.id, []),
                }
            )
        )

    resp = WorkoutSessionDetailResponse.model_validate(session)
    return resp.model_copy(
        update={"exercise_count": len(ses), "exercises": exercises}
    )


# ── Sessions: list / get ────────────────────────────────────────────────────

async def list_sessions(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> WorkoutSessionListResponse:
    """List the CURRENT user's sessions, newest first."""
    query = select(WorkoutSession).where(
        WorkoutSession.household_id == household_id,
        WorkoutSession.created_by_user_id == user_id,
    )
    if from_date is not None:
        query = query.where(
            WorkoutSession.started_at >= datetime.combine(from_date, datetime.min.time())
        )
    if to_date is not None:
        query = query.where(
            WorkoutSession.started_at < datetime.combine(to_date, datetime.max.time())
        )

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    sessions = (
        await db.execute(
            query.order_by(WorkoutSession.started_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    session_ids = [s.id for s in sessions]
    counts: dict[uuid.UUID, int] = {}
    if session_ids:
        rows = (
            await db.execute(
                select(SessionExercise.session_id, func.count())
                .where(SessionExercise.session_id.in_(session_ids))
                .group_by(SessionExercise.session_id)
            )
        ).all()
        counts = {sid: n for sid, n in rows}

    items = [
        WorkoutSessionResponse.model_validate(s).model_copy(
            update={"exercise_count": counts.get(s.id, 0)}
        )
        for s in sessions
    ]
    return WorkoutSessionListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


async def get_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkoutSessionDetailResponse | None:
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    return await _load_detail(db, session)


# ── Sessions: create / update / delete ──────────────────────────────────────

async def create_session(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkoutSessionCreate,
) -> WorkoutSessionDetailResponse | None:
    """Start/log a session.

    * ``template_id`` set and ``exercises`` empty → materialize session_exercises
      and their sets from the template's slots (ghost/default prefill), linked
      back via template_exercise_id.
    * ``exercises`` provided → log those directly (blank-session path).

    Returns None if ``template_id`` refers to a template outside this household.
    Raises SupersetError on an invalid exercise or oversized superset group.
    """
    template: WorkoutTemplate | None = None
    if data.template_id is not None:
        template = (
            await db.execute(
                select(WorkoutTemplate).where(
                    WorkoutTemplate.id == data.template_id,
                    WorkoutTemplate.household_id == household_id,
                    WorkoutTemplate.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if template is None:
            return None

    # Validate explicit exercises up front.
    _validate_group_sizes([e.superset_group_id for e in data.exercises])
    for e in data.exercises:
        await _assert_exercise_visible(db, e.exercise_id, household_id)

    session = WorkoutSession(
        household_id=household_id,
        created_by_user_id=user_id,
        template_id=data.template_id,
        name=data.name or (template.name if template else None),
        started_at=data.started_at or func.now(),
        ended_at=data.ended_at,
        notes=data.notes,
    )
    db.add(session)
    await db.flush()

    if data.exercises:
        await _add_exercises(db, session.id, data.exercises)
    elif template is not None:
        await _materialize_from_template(db, session.id, template.id)

    await db.commit()
    await db.refresh(session)
    return await _load_detail(db, session)


async def _add_exercises(
    db: AsyncSession, session_id: uuid.UUID, exercises: list[SessionExerciseCreate]
) -> None:
    for i, e in enumerate(exercises):
        se = SessionExercise(
            session_id=session_id,
            exercise_id=e.exercise_id,
            template_exercise_id=e.template_exercise_id,
            position=e.position if e.position is not None else i,
            superset_group_id=e.superset_group_id,
            notes=e.notes,
        )
        db.add(se)
        await db.flush()
        for j, s in enumerate(e.sets, start=1):
            db.add(_build_set(se.id, j, s))


async def _materialize_from_template(
    db: AsyncSession, session_id: uuid.UUID, template_id: uuid.UUID
) -> None:
    """Copy a template's slots into the session as session_exercises, each with
    ``default_sets`` sets pre-filled from the slot defaults. This is the
    materialization that lets history outlive the template."""
    slots = (
        await db.execute(
            select(TemplateExercise)
            .where(TemplateExercise.template_id == template_id)
            .order_by(TemplateExercise.position.asc(), TemplateExercise.created_at.asc())
        )
    ).scalars().all()
    for slot in slots:
        se = SessionExercise(
            session_id=session_id,
            exercise_id=slot.exercise_id,
            template_exercise_id=slot.id,
            position=slot.position,
            superset_group_id=slot.superset_group_id,
            notes=slot.notes,
        )
        db.add(se)
        await db.flush()
        n_sets = slot.default_sets or 0
        for k in range(1, n_sets + 1):
            db.add(
                WorkoutSet(
                    session_exercise_id=se.id,
                    set_number=k,
                    target_reps=slot.default_reps,
                    weight=slot.default_weight,
                    weight_unit="lbs" if slot.default_weight is not None else None,
                    rest_seconds=slot.default_rest_seconds,
                )
            )


async def update_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkoutSessionUpdate,
) -> WorkoutSessionResponse | None:
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    for field in data.model_fields_set:
        setattr(session, field, getattr(data, field))
    await db.commit()
    await db.refresh(session)
    count = (
        await db.execute(
            select(func.count()).select_from(SessionExercise).where(
                SessionExercise.session_id == session_id
            )
        )
    ).scalar_one()
    return WorkoutSessionResponse.model_validate(session).model_copy(
        update={"exercise_count": count}
    )


async def delete_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Hard-delete a session and its exercises + sets (explicit cascade for the
    SQLite tier)."""
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return False
    se_ids = (
        await db.execute(
            select(SessionExercise.id).where(SessionExercise.session_id == session_id)
        )
    ).scalars().all()
    if se_ids:
        await db.execute(
            delete(WorkoutSet).where(WorkoutSet.session_exercise_id.in_(se_ids))
        )
    await db.execute(
        delete(SessionExercise).where(SessionExercise.session_id == session_id)
    )
    await db.execute(delete(WorkoutSession).where(WorkoutSession.id == session_id))
    await db.commit()
    return True


# ── Session exercises & sets (live logging primitives) ──────────────────────

async def add_session_exercise(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: SessionExerciseCreate,
) -> SessionExerciseResponse | None:
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    await _assert_exercise_visible(db, data.exercise_id, household_id)

    parent = SessionExercise.session_id == session_id
    if data.superset_group_id is not None:
        await assert_capacity_for_join(db, SessionExercise, parent, data.superset_group_id)

    if data.position is not None:
        position = data.position
    else:
        max_pos = (
            await db.execute(select(func.max(SessionExercise.position)).where(parent))
        ).scalar_one_or_none()
        position = 0 if max_pos is None else max_pos + 1

    se = SessionExercise(
        session_id=session_id,
        exercise_id=data.exercise_id,
        template_exercise_id=data.template_exercise_id,
        position=position,
        superset_group_id=data.superset_group_id,
        notes=data.notes,
    )
    db.add(se)
    await db.flush()
    for j, s in enumerate(data.sets, start=1):
        db.add(_build_set(se.id, j, s))
    await db.commit()
    await db.refresh(se)
    return await _session_exercise_response(db, se)


async def _session_exercise_response(
    db: AsyncSession, se: SessionExercise
) -> SessionExerciseResponse:
    exercise = (
        await db.execute(select(Exercise).where(Exercise.id == se.exercise_id))
    ).scalar_one_or_none()
    sets = (
        await db.execute(
            select(WorkoutSet)
            .where(WorkoutSet.session_exercise_id == se.id)
            .order_by(WorkoutSet.set_number.asc(), WorkoutSet.created_at.asc())
        )
    ).scalars().all()
    resp = SessionExerciseResponse.model_validate(se)
    return resp.model_copy(
        update={
            "exercise": ExerciseResponse.model_validate(exercise) if exercise else None,
            "sets": [WorkoutSetResponse.model_validate(s) for s in sets],
        }
    )


async def _load_session_exercise(
    db: AsyncSession,
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SessionExercise | None:
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    return (
        await db.execute(
            select(SessionExercise).where(
                SessionExercise.id == se_id,
                SessionExercise.session_id == session_id,
            )
        )
    ).scalar_one_or_none()


async def add_set(
    db: AsyncSession,
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkoutSetCreate,
) -> WorkoutSetResponse | None:
    se = await _load_session_exercise(db, session_id, se_id, household_id, user_id)
    if se is None:
        return None
    if data.set_number is not None:
        set_number = data.set_number
    else:
        max_n = (
            await db.execute(
                select(func.max(WorkoutSet.set_number)).where(
                    WorkoutSet.session_exercise_id == se_id
                )
            )
        ).scalar_one_or_none()
        set_number = 1 if max_n is None else max_n + 1
    ws = _build_set(se_id, set_number, data)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return WorkoutSetResponse.model_validate(ws)


async def update_set(
    db: AsyncSession,
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    set_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkoutSetUpdate,
) -> WorkoutSetResponse | None:
    se = await _load_session_exercise(db, session_id, se_id, household_id, user_id)
    if se is None:
        return None
    ws = (
        await db.execute(
            select(WorkoutSet).where(
                WorkoutSet.id == set_id, WorkoutSet.session_exercise_id == se_id
            )
        )
    ).scalar_one_or_none()
    if ws is None:
        return None
    for field in data.model_fields_set:
        setattr(ws, field, getattr(data, field))
    await db.commit()
    await db.refresh(ws)
    return WorkoutSetResponse.model_validate(ws)


async def delete_set(
    db: AsyncSession,
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    set_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    se = await _load_session_exercise(db, session_id, se_id, household_id, user_id)
    if se is None:
        return False
    result = await db.execute(
        delete(WorkoutSet).where(
            WorkoutSet.id == set_id, WorkoutSet.session_exercise_id == se_id
        ).returning(WorkoutSet.id)
    )
    deleted = result.scalar_one_or_none() is not None
    await db.commit()
    return deleted


async def remove_session_exercise(
    db: AsyncSession,
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    se = await _load_session_exercise(db, session_id, se_id, household_id, user_id)
    if se is None:
        return False
    group_id = se.superset_group_id
    parent = SessionExercise.session_id == session_id
    await db.execute(delete(WorkoutSet).where(WorkoutSet.session_exercise_id == se_id))
    await db.execute(delete(SessionExercise).where(SessionExercise.id == se_id))
    await db.flush()
    await dissolve_if_orphaned(db, SessionExercise, parent, group_id)
    await db.commit()
    return True
