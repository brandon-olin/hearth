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
from collections import Counter
from datetime import UTC, date, datetime

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.workouts import templates_service
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
    PrefillSet,
    SessionExerciseCreate,
    SessionExercisePrefill,
    SessionExerciseResponse,
    SessionPrefillResponse,
    TemplateExerciseCreate,
    WorkoutSessionCreate,
    WorkoutSessionDetailResponse,
    WorkoutSessionListResponse,
    WorkoutSessionResponse,
    WorkoutSessionSummary,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetResponse,
    WorkoutSetUpdate,
    WorkoutTemplateCreate,
    WorkoutTemplateDetailResponse,
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


async def _load_session_exercises(
    db: AsyncSession, session_id: uuid.UUID
) -> list[SessionExercise]:
    return list(
        (
            await db.execute(
                select(SessionExercise)
                .where(SessionExercise.session_id == session_id)
                .order_by(
                    SessionExercise.position.asc(), SessionExercise.created_at.asc()
                )
            )
        ).scalars().all()
    )


async def _sets_by_session_exercise(
    db: AsyncSession,
    se_ids: list[uuid.UUID],
    *,
    completed_only: bool = False,
) -> dict[uuid.UUID, list[WorkoutSet]]:
    """Batch-load sets for many session_exercises at once (never per-exercise)."""
    if not se_ids:
        return {}
    query = select(WorkoutSet).where(WorkoutSet.session_exercise_id.in_(se_ids))
    if completed_only:
        query = query.where(WorkoutSet.completed_at.is_not(None))
    rows = (
        await db.execute(
            query.order_by(WorkoutSet.set_number.asc(), WorkoutSet.created_at.asc())
        )
    ).scalars().all()
    grouped: dict[uuid.UUID, list[WorkoutSet]] = {}
    for row in rows:
        grouped.setdefault(row.session_exercise_id, []).append(row)
    return grouped


# ── Ghost values (workouts-003) ─────────────────────────────────────────────
#
# GHOST VALUES ARE PER-USER. The lookup below is keyed on the template slot AND
# filtered to ``created_by_user_id == user_id``. Templates are household-shared,
# so without that predicate a member starting someone else's template would be
# pre-filled with the OTHER member's weights — a cross-user leak and a
# discouraging first session. Never relax it.
#
# Keying on template_exercise_id (not exercise_id) is deliberate: a heavy bench
# slot and a back-off bench slot in one template each track their own history,
# which is what makes progressive-overload prefill behave when protocols vary.
# The exercise_id branch exists ONLY for blank sessions, whose exercises have no
# slot to key on; it is likewise filtered to the requesting member.


async def _latest_logged_session_exercise(
    db: AsyncSession,
    *,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    session: WorkoutSession,
    key_col: ColumnElement,
    keys: set[uuid.UUID],
) -> dict[uuid.UUID, uuid.UUID]:
    """Map each key → the id of the most recent session_exercise THIS member
    logged for it, considering only exercises that have at least one completed
    set. One window-function query, not one query per key."""
    if not keys:
        return {}
    ranked = (
        select(
            key_col.label("k"),
            SessionExercise.id.label("se_id"),
            func.row_number()
            .over(
                partition_by=key_col,
                order_by=(WorkoutSession.started_at.desc(), WorkoutSession.id.desc()),
            )
            .label("rn"),
        )
        .join(WorkoutSession, WorkoutSession.id == SessionExercise.session_id)
        .where(
            key_col.in_(keys),
            WorkoutSession.household_id == household_id,
            # ── the anti-leak predicate ──
            WorkoutSession.created_by_user_id == user_id,
            WorkoutSession.id != session.id,
            WorkoutSession.started_at <= session.started_at,
            select(WorkoutSet.id)
            .where(
                WorkoutSet.session_exercise_id == SessionExercise.id,
                WorkoutSet.completed_at.is_not(None),
            )
            .exists(),
        )
        .subquery()
    )
    rows = (
        await db.execute(select(ranked.c.k, ranked.c.se_id).where(ranked.c.rn == 1))
    ).all()
    return {k: se_id for k, se_id in rows}


def _prefill_from_sets(sets: list[WorkoutSet]) -> list[PrefillSet]:
    return [
        PrefillSet(
            set_number=s.set_number,
            reps=s.reps,
            weight=float(s.weight) if s.weight is not None else None,
            weight_unit=s.weight_unit,
            is_warmup=s.is_warmup,
        )
        for s in sets
    ]


def _prefill_from_slot(slot: TemplateExercise) -> list[PrefillSet]:
    """The template's own defaults, expanded to one suggestion per planned set."""
    if slot.default_weight is None and slot.default_reps is None:
        return []
    n = slot.default_sets or 1
    return [
        PrefillSet(
            set_number=i,
            reps=slot.default_reps,
            weight=float(slot.default_weight) if slot.default_weight is not None else None,
            weight_unit="lbs" if slot.default_weight is not None else None,
            is_warmup=False,
        )
        for i in range(1, n + 1)
    ]


async def get_session_prefill(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SessionPrefillResponse | None:
    """Ghost-value suggestions for every exercise in a session.

    Resolution order per exercise, exactly as specified:
      1. the CURRENT member's most recent logged session for the same
         ``template_exercise_id`` (or ``exercise_id`` when the session is blank),
      2. the template slot's ``default_weight`` / ``default_reps``,
      3. nothing — the client shows empty fields.

    Another member's data is never a fallback at any step.
    """
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None

    ses = await _load_session_exercises(db, session_id)
    if not ses:
        return SessionPrefillResponse(session_id=session_id, items=[])

    te_ids = {se.template_exercise_id for se in ses if se.template_exercise_id}
    ex_ids = {se.exercise_id for se in ses if se.template_exercise_id is None}

    by_te = await _latest_logged_session_exercise(
        db, household_id=household_id, user_id=user_id, session=session,
        key_col=SessionExercise.template_exercise_id, keys=te_ids,
    )
    by_ex = await _latest_logged_session_exercise(
        db, household_id=household_id, user_id=user_id, session=session,
        key_col=SessionExercise.exercise_id, keys=ex_ids,
    )

    history_sets = await _sets_by_session_exercise(
        db, list({*by_te.values(), *by_ex.values()}), completed_only=True
    )

    slots: dict[uuid.UUID, TemplateExercise] = {}
    if te_ids:
        slots = {
            s.id: s
            for s in (
                await db.execute(
                    select(TemplateExercise).where(TemplateExercise.id.in_(te_ids))
                )
            ).scalars().all()
        }

    items: list[SessionExercisePrefill] = []
    for se in ses:
        slot = slots.get(se.template_exercise_id) if se.template_exercise_id else None
        source_se_id = (
            by_te.get(se.template_exercise_id)
            if se.template_exercise_id
            else by_ex.get(se.exercise_id)
        )
        suggestions = _prefill_from_sets(history_sets.get(source_se_id, [])) if source_se_id else []
        source = "history" if suggestions else "none"
        if not suggestions and slot is not None:
            suggestions = _prefill_from_slot(slot)
            source = "template" if suggestions else "none"
        items.append(
            SessionExercisePrefill(
                session_exercise_id=se.id,
                template_exercise_id=se.template_exercise_id,
                source=source,
                rest_seconds=slot.default_rest_seconds if slot else None,
                sets=suggestions,
            )
        )
    return SessionPrefillResponse(session_id=session_id, items=items)


# ── Finishing a session (workouts-003) ──────────────────────────────────────

def _aware(dt: datetime) -> datetime:
    """psycopg2 can hand back naive datetimes from TIMESTAMPTZ columns; normalize
    before arithmetic against an aware ``now`` (see api/CLAUDE.md)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _summarize(
    session: WorkoutSession,
    ses: list[SessionExercise],
    sets_by_se: dict[uuid.UUID, list[WorkoutSet]],
) -> WorkoutSessionSummary:
    volume = 0.0
    volume_unit: str | None = None
    working = 0
    warmups = 0
    exercises_completed = 0

    for se in ses:
        logged_working = False
        for s in sets_by_se.get(se.id, []):
            if s.completed_at is None:
                continue
            if s.is_warmup:
                warmups += 1
                continue
            working += 1
            logged_working = True
            if s.weight is not None and s.reps is not None:
                volume += float(s.weight) * s.reps
                if volume_unit is None:
                    volume_unit = s.weight_unit or "lbs"
        if logged_working:
            exercises_completed += 1

    duration = 0
    if session.ended_at is not None:
        duration = max(
            0, int((_aware(session.ended_at) - _aware(session.started_at)).total_seconds())
        )

    return WorkoutSessionSummary(
        session_id=session.id,
        name=session.name,
        started_at=session.started_at,
        ended_at=session.ended_at,
        duration_seconds=duration,
        working_volume=round(volume, 2),
        volume_unit=volume_unit,
        working_sets_completed=working,
        warmup_sets_completed=warmups,
        exercises_completed=exercises_completed,
        exercise_count=len(ses),
        from_template=session.template_id is not None,
    )


async def get_session_summary(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkoutSessionSummary | None:
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    ses = await _load_session_exercises(db, session_id)
    sets_by_se = await _sets_by_session_exercise(db, [s.id for s in ses])
    return _summarize(session, ses, sets_by_se)


async def finish_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    ended_at: datetime | None = None,
) -> WorkoutSessionSummary | None:
    """Stamp ``ended_at`` and return the summary.

    Idempotent: a session that is already finished keeps its original
    ``ended_at`` unless the caller passes an explicit one, so a retry (or a
    double-tap on "Finish workout") cannot stretch a recorded duration.
    """
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    if ended_at is not None or session.ended_at is None:
        session.ended_at = ended_at or datetime.now(UTC)
        await db.commit()
        await db.refresh(session)
    ses = await _load_session_exercises(db, session_id)
    sets_by_se = await _sets_by_session_exercise(db, [s.id for s in ses])
    return _summarize(session, ses, sets_by_se)


# ── Save a logged session as a reusable template (workouts-003) ─────────────

def _slot_defaults(sets: list[WorkoutSet]) -> dict:
    """Collapse a session exercise's sets into template defaults.

    Warmups are excluded (they are protocol, not the plan). Completed sets are
    preferred as the basis; if nothing was checked off, whatever was entered is
    used so a half-logged session still produces a sensible template.
    """
    working = [s for s in sets if not s.is_warmup]
    basis = [s for s in working if s.completed_at is not None] or working
    reps = [s.reps for s in basis if s.reps is not None]
    weights = [float(s.weight) for s in basis if s.weight is not None]
    rests = [s.rest_seconds for s in basis if s.rest_seconds is not None]
    return {
        "default_sets": len(working) or None,
        # The modal rep count is the plan; a single failed set shouldn't rewrite it.
        "default_reps": Counter(reps).most_common(1)[0][0] if reps else None,
        "default_weight": max(weights) if weights else None,
        "default_rest_seconds": max(rests) if rests else None,
    }


async def save_session_as_template(
    db: AsyncSession,
    session_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str | None = None,
) -> WorkoutTemplateDetailResponse | None:
    """Turn a logged session into a household-shared template.

    The session itself is left untouched — this is a read plus a create, so
    calling it twice yields two templates rather than corrupting history.
    """
    session = await _load_session(db, session_id, household_id, user_id)
    if session is None:
        return None
    ses = await _load_session_exercises(db, session_id)
    sets_by_se = await _sets_by_session_exercise(db, [s.id for s in ses])

    slots = [
        TemplateExerciseCreate(
            exercise_id=se.exercise_id,
            position=i,
            superset_group_id=se.superset_group_id,
            notes=se.notes,
            **_slot_defaults(sets_by_se.get(se.id, [])),
        )
        for i, se in enumerate(ses)
    ]
    return await templates_service.create_template(
        db,
        household_id,
        user_id,
        WorkoutTemplateCreate(name=name or session.name or "Workout", exercises=slots),
    )


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
