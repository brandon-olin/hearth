"""Workout template service (workouts-001).

Templates are SHARED across the household (any member sees and can start from
any template), but their recency ordering is PERSONAL: ``last_used_at`` is
derived per-request as MAX(started_at) over the CURRENT user's sessions for the
template — there is no stored column (see models.py).

Superset invariants (2–5 members, dissolve-lone-member) are enforced here via
``superset.py``. Foreign-key cascades are done explicitly in the service rather
than relying on ``ON DELETE`` clauses, because the SQLite tier does not enable
FK enforcement — see delete_template / remove_template_exercise.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.workouts.exercises_service import _visible_clause
from life_dashboard.domains.workouts.models import (
    Exercise,
    SessionExercise,
    TemplateExercise,
    WorkoutSession,
    WorkoutTemplate,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseResponse,
    TemplateExerciseCreate,
    TemplateExerciseResponse,
    TemplateExerciseUpdate,
    WorkoutTemplateCreate,
    WorkoutTemplateDetailResponse,
    WorkoutTemplateListResponse,
    WorkoutTemplateResponse,
    WorkoutTemplateUpdate,
)
from life_dashboard.domains.workouts.superset import (
    SupersetError,
    assert_capacity_for_join,
    dissolve_if_orphaned,
)

# ── Internal helpers ────────────────────────────────────────────────────────

async def _load_template(
    db: AsyncSession, template_id: uuid.UUID, household_id: uuid.UUID
) -> WorkoutTemplate | None:
    return (
        await db.execute(
            select(WorkoutTemplate).where(
                WorkoutTemplate.id == template_id,
                WorkoutTemplate.household_id == household_id,
                WorkoutTemplate.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _last_used_at(
    db: AsyncSession, template_id: uuid.UUID, user_id: uuid.UUID
) -> object | None:
    return (
        await db.execute(
            select(func.max(WorkoutSession.started_at)).where(
                WorkoutSession.template_id == template_id,
                WorkoutSession.created_by_user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def _exercise_count(db: AsyncSession, template_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(TemplateExercise).where(
                TemplateExercise.template_id == template_id
            )
        )
    ).scalar_one()


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


def _te_response(
    te: TemplateExercise, exercise: Exercise | None = None
) -> TemplateExerciseResponse:
    resp = TemplateExerciseResponse.model_validate(te)
    if exercise is not None:
        return resp.model_copy(
            update={"exercise": ExerciseResponse.model_validate(exercise)}
        )
    return resp


async def _load_template_exercises(
    db: AsyncSession, template_id: uuid.UUID
) -> list[TemplateExerciseResponse]:
    """Load a template's slots ordered by position, with each exercise attached
    (batch-loaded — no N+1)."""
    rows = (
        await db.execute(
            select(TemplateExercise)
            .where(TemplateExercise.template_id == template_id)
            .order_by(TemplateExercise.position.asc(), TemplateExercise.created_at.asc())
        )
    ).scalars().all()
    if not rows:
        return []
    ex_ids = {r.exercise_id for r in rows}
    ex_by_id = {
        e.id: e
        for e in (
            await db.execute(select(Exercise).where(Exercise.id.in_(ex_ids)))
        ).scalars().all()
    }
    return [_te_response(r, ex_by_id.get(r.exercise_id)) for r in rows]


# ── Templates: list / get ───────────────────────────────────────────────────

async def list_templates(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> WorkoutTemplateListResponse:
    """List household templates. Ordering is personal: most-recently-used by the
    CURRENT user first, then never-used, then by name. Every household template
    is shown regardless of creator — only the ORDER is per-user."""
    # Per-user recency as a correlated subquery so a template someone else used
    # recently does not float up this user's list.
    last_used = (
        select(func.max(WorkoutSession.started_at))
        .where(
            WorkoutSession.template_id == WorkoutTemplate.id,
            WorkoutSession.created_by_user_id == user_id,
        )
        .correlate(WorkoutTemplate)
        .scalar_subquery()
    )

    base = select(WorkoutTemplate).where(
        WorkoutTemplate.household_id == household_id,
        WorkoutTemplate.archived_at.is_(None),
    )
    if search:
        base = base.where(func.lower(WorkoutTemplate.name).contains(search.strip().lower()))

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await db.execute(
            base.add_columns(last_used.label("last_used_at"))
            # NULLs (never used) sort last on both engines: order by the flag first.
            .order_by(
                last_used.is_(None).asc(),
                last_used.desc(),
                WorkoutTemplate.name.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    template_ids = [row[0].id for row in rows]
    counts = await _counts_by_template(db, template_ids)

    items = []
    for template, last_used_at in rows:
        resp = WorkoutTemplateResponse.model_validate(template)
        items.append(
            resp.model_copy(
                update={
                    "exercise_count": counts.get(template.id, 0),
                    "last_used_at": last_used_at,
                }
            )
        )
    return WorkoutTemplateListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


async def _counts_by_template(
    db: AsyncSession, template_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not template_ids:
        return {}
    rows = (
        await db.execute(
            select(TemplateExercise.template_id, func.count())
            .where(TemplateExercise.template_id.in_(template_ids))
            .group_by(TemplateExercise.template_id)
        )
    ).all()
    return {tid: n for tid, n in rows}


async def find_template_by_name(
    db: AsyncSession, household_id: uuid.UUID, name: str
) -> WorkoutTemplate | None:
    """Case-insensitive exact-name lookup within a household. Used by the MCP
    surface so an agent can reference a template by name rather than UUID."""
    return (
        await db.execute(
            select(WorkoutTemplate).where(
                WorkoutTemplate.household_id == household_id,
                WorkoutTemplate.archived_at.is_(None),
                func.lower(func.trim(WorkoutTemplate.name)) == name.strip().lower(),
            )
        )
    ).scalars().first()


async def get_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkoutTemplateDetailResponse | None:
    template = await _load_template(db, template_id, household_id)
    if template is None:
        return None
    exercises = await _load_template_exercises(db, template_id)
    resp = WorkoutTemplateDetailResponse.model_validate(template)
    return resp.model_copy(
        update={
            "exercise_count": len(exercises),
            "last_used_at": await _last_used_at(db, template_id, user_id),
            "exercises": exercises,
        }
    )


# ── Templates: create / update / delete ─────────────────────────────────────

async def create_template(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: WorkoutTemplateCreate,
) -> WorkoutTemplateDetailResponse:
    """Create a shared template, optionally with its exercise slots. Validates
    every exercise is visible and that no superset group exceeds 5 members."""
    _validate_group_sizes(
        [(e.superset_group_id) for e in data.exercises]
    )
    for e in data.exercises:
        await _assert_exercise_visible(db, e.exercise_id, household_id)

    template = WorkoutTemplate(
        household_id=household_id,
        created_by_user_id=user_id,
        name=data.name,
        description=data.description,
        estimated_duration_minutes=data.estimated_duration_minutes,
    )
    db.add(template)
    await db.flush()

    for i, e in enumerate(data.exercises):
        db.add(
            TemplateExercise(
                template_id=template.id,
                exercise_id=e.exercise_id,
                position=e.position if e.position is not None else i,
                superset_group_id=e.superset_group_id,
                default_sets=e.default_sets,
                default_reps=e.default_reps,
                default_weight=e.default_weight,
                default_rest_seconds=e.default_rest_seconds,
                notes=e.notes,
            )
        )
    await db.commit()

    result = await get_template(db, template.id, household_id, user_id)
    assert result is not None  # just created
    return result


def _validate_group_sizes(group_ids: list[uuid.UUID | None]) -> None:
    """On create, reject any superset group given more than 5 members in one
    payload. (Min-2 is a UI convention; the lone-member rule is enforced on
    removal, not creation.)"""
    counts: dict[uuid.UUID, int] = {}
    for gid in group_ids:
        if gid is not None:
            counts[gid] = counts.get(gid, 0) + 1
    for gid, n in counts.items():
        if n > 5:
            raise SupersetError(
                f"A superset can hold at most 5 exercises; group {gid} has {n}."
            )


async def update_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    household_id: uuid.UUID,
    data: WorkoutTemplateUpdate,
) -> WorkoutTemplateResponse | None:
    template = await _load_template(db, template_id, household_id)
    if template is None:
        return None
    for field in data.model_fields_set:
        setattr(template, field, getattr(data, field))
    await db.commit()
    await db.refresh(template)
    resp = WorkoutTemplateResponse.model_validate(template)
    return resp.model_copy(
        update={"exercise_count": await _exercise_count(db, template_id)}
    )


async def delete_template(
    db: AsyncSession, template_id: uuid.UUID, household_id: uuid.UUID
) -> bool:
    """Hard-delete a template. Logs survive: sessions keep their materialized
    exercises and sets; only the template links are cleared. The cascade is done
    explicitly because SQLite does not enforce ON DELETE (see module docstring)."""
    template = await _load_template(db, template_id, household_id)
    if template is None:
        return False

    te_ids = (
        await db.execute(
            select(TemplateExercise.id).where(
                TemplateExercise.template_id == template_id
            )
        )
    ).scalars().all()

    # SET NULL on the two back-references, then remove the slots and template.
    await db.execute(
        update(WorkoutSession)
        .where(WorkoutSession.template_id == template_id)
        .values(template_id=None)
    )
    if te_ids:
        await db.execute(
            update(SessionExercise)
            .where(SessionExercise.template_exercise_id.in_(te_ids))
            .values(template_exercise_id=None)
        )
    await db.execute(
        delete(TemplateExercise).where(TemplateExercise.template_id == template_id)
    )
    await db.execute(delete(WorkoutTemplate).where(WorkoutTemplate.id == template_id))
    await db.commit()
    return True


# ── Template exercises: add / update / remove ───────────────────────────────

async def add_template_exercise(
    db: AsyncSession,
    template_id: uuid.UUID,
    household_id: uuid.UUID,
    data: TemplateExerciseCreate,
) -> TemplateExerciseResponse | None:
    """Append (or insert at ``position``) an exercise slot. Raises SupersetError
    if joining a group would exceed 5 members. Returns None if the template is
    not in this household."""
    template = await _load_template(db, template_id, household_id)
    if template is None:
        return None
    await _assert_exercise_visible(db, data.exercise_id, household_id)

    parent = TemplateExercise.template_id == template_id
    if data.superset_group_id is not None:
        await assert_capacity_for_join(
            db, TemplateExercise, parent, data.superset_group_id
        )

    if data.position is not None:
        position = data.position
    else:
        max_pos = (
            await db.execute(
                select(func.max(TemplateExercise.position)).where(parent)
            )
        ).scalar_one_or_none()
        position = 0 if max_pos is None else max_pos + 1

    te = TemplateExercise(
        template_id=template_id,
        exercise_id=data.exercise_id,
        position=position,
        superset_group_id=data.superset_group_id,
        default_sets=data.default_sets,
        default_reps=data.default_reps,
        default_weight=data.default_weight,
        default_rest_seconds=data.default_rest_seconds,
        notes=data.notes,
    )
    db.add(te)
    await db.commit()
    await db.refresh(te)
    exercise = (
        await db.execute(select(Exercise).where(Exercise.id == te.exercise_id))
    ).scalar_one_or_none()
    return _te_response(te, exercise)


async def update_template_exercise(
    db: AsyncSession,
    template_id: uuid.UUID,
    te_id: uuid.UUID,
    household_id: uuid.UUID,
    data: TemplateExerciseUpdate,
) -> TemplateExerciseResponse | None:
    template = await _load_template(db, template_id, household_id)
    if template is None:
        return None
    te = (
        await db.execute(
            select(TemplateExercise).where(
                TemplateExercise.id == te_id,
                TemplateExercise.template_id == template_id,
            )
        )
    ).scalar_one_or_none()
    if te is None:
        return None

    parent = TemplateExercise.template_id == template_id
    old_group = te.superset_group_id
    fields = data.model_fields_set

    if "superset_group_id" in fields:
        new_group = data.superset_group_id
        if new_group is not None and new_group != old_group:
            await assert_capacity_for_join(
                db, TemplateExercise, parent, new_group, exclude_id=te_id
            )

    for field in fields:
        setattr(te, field, getattr(data, field))
    await db.flush()

    # If this row left a group, that group may now be a lone member — dissolve it.
    left_group = (
        "superset_group_id" in fields
        and old_group is not None
        and old_group != data.superset_group_id
    )
    if left_group:
        await dissolve_if_orphaned(db, TemplateExercise, parent, old_group)

    await db.commit()
    await db.refresh(te)
    exercise = (
        await db.execute(select(Exercise).where(Exercise.id == te.exercise_id))
    ).scalar_one_or_none()
    return _te_response(te, exercise)


async def remove_template_exercise(
    db: AsyncSession,
    template_id: uuid.UUID,
    te_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    """Remove a slot. If it was in a superset that now has a single member left,
    that member's group is cleared (no superset-of-one)."""
    template = await _load_template(db, template_id, household_id)
    if template is None:
        return False
    te = (
        await db.execute(
            select(TemplateExercise).where(
                TemplateExercise.id == te_id,
                TemplateExercise.template_id == template_id,
            )
        )
    ).scalar_one_or_none()
    if te is None:
        return False

    group_id = te.superset_group_id
    parent = TemplateExercise.template_id == template_id
    # Detach any session_exercises that were seeded from this slot (SET NULL,
    # done explicitly for the SQLite tier).
    await db.execute(
        update(SessionExercise)
        .where(SessionExercise.template_exercise_id == te_id)
        .values(template_exercise_id=None)
    )
    await db.execute(delete(TemplateExercise).where(TemplateExercise.id == te_id))
    await db.flush()
    await dissolve_if_orphaned(db, TemplateExercise, parent, group_id)
    await db.commit()
    return True
