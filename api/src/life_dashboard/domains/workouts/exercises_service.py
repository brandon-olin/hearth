"""Exercise catalog service (workouts-001).

The catalog is SHARED: every household sees the ~60 global library rows
(``household_id IS NULL``) plus its own custom exercises. Nothing here is
personal, so there is no per-user filter — only the household boundary and the
global/custom split.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.workouts.models import (
    Exercise,
    SessionExercise,
    WorkoutSession,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseCreate,
    ExerciseListResponse,
    ExerciseResponse,
    ExerciseUpdate,
)
from life_dashboard.domains.workouts.seed_data import GLOBAL_EXERCISES, normalize_name


def _exercise_response(ex: Exercise) -> ExerciseResponse:
    return ExerciseResponse.model_validate(ex)


def _visible_clause(household_id: uuid.UUID):
    """Rows this household may see: the global library plus its own custom
    exercises. Global rows have ``household_id IS NULL``."""
    return or_(Exercise.household_id.is_(None), Exercise.household_id == household_id)


async def ensure_global_exercises(db: AsyncSession) -> int:
    """Idempotently seed the global library from :data:`GLOBAL_EXERCISES`.

    Migration 0048 seeds these at deploy time; this mirror exists for the
    SQLite ``create_all()`` path (tests, fresh dev DBs) where the migration's
    data step does not run. Inserts only the names not already present as global
    rows, so repeated calls never duplicate. Returns the number inserted.
    """
    existing = {
        normalize_name(n)
        for n in (
            await db.execute(select(Exercise.name).where(Exercise.is_global.is_(True)))
        ).scalars().all()
    }
    inserted = 0
    for spec in GLOBAL_EXERCISES:
        if normalize_name(spec["name"]) in existing:
            continue
        db.add(
            Exercise(
                household_id=None,
                created_by_user_id=None,
                name=spec["name"],
                muscle_groups=list(spec.get("muscle_groups") or []),
                equipment_type=spec.get("equipment_type"),
                tracking_type=spec["tracking_type"],
                is_global=True,
            )
        )
        existing.add(normalize_name(spec["name"]))
        inserted += 1
    if inserted:
        await db.commit()
    return inserted


async def list_exercises(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    search: str | None = None,
    sort: str = "name",
    limit: int = 100,
    offset: int = 0,
) -> ExerciseListResponse:
    """List the global library + this household's active custom exercises.

    ``search`` matches the name case-insensitively. ``sort`` is either ``"name"``
    (alphabetical, the default) or ``"recent"`` — most-recently-used by the
    CURRENT user first, derived through their sessions (never-used exercises sort
    last, then alphabetically). Recency is PERSONAL like template ordering: the
    catalog is shared but "recently used" means recently used *by you*.
    """
    query = select(Exercise).where(
        _visible_clause(household_id),
        Exercise.archived_at.is_(None),
    )
    if search:
        query = query.where(func.lower(Exercise.name).contains(search.strip().lower()))

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()

    if sort == "recent" and user_id is not None:
        # Per-user recency as a correlated subquery: MAX(started_at) over the
        # current user's sessions that included this exercise. Someone else's use
        # must not surface an exercise up your picker.
        last_used = (
            select(func.max(WorkoutSession.started_at))
            .select_from(SessionExercise)
            .join(WorkoutSession, SessionExercise.session_id == WorkoutSession.id)
            .where(
                SessionExercise.exercise_id == Exercise.id,
                WorkoutSession.created_by_user_id == user_id,
            )
            .correlate(Exercise)
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                query.add_columns(last_used.label("last_used_at"))
                # NULLs (never used by this user) sort last on both engines.
                .order_by(
                    last_used.is_(None).asc(),
                    last_used.desc(),
                    Exercise.name.asc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items = [_exercise_response(row[0]) for row in rows]
    else:
        rows = (
            await db.execute(
                query.order_by(Exercise.name.asc()).limit(limit).offset(offset)
            )
        ).scalars().all()
        items = [_exercise_response(e) for e in rows]

    return ExerciseListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_exercise(
    db: AsyncSession, exercise_id: uuid.UUID, household_id: uuid.UUID
) -> ExerciseResponse | None:
    ex = await _load_visible(db, exercise_id, household_id)
    return _exercise_response(ex) if ex else None


async def find_exercise_by_name(
    db: AsyncSession, household_id: uuid.UUID, name: str
) -> Exercise | None:
    """Case-insensitive exact-name lookup across the rows this household can
    see. Used by the MCP surface so an agent can reference an exercise by name
    rather than UUID (mirrors ``templates_service.find_template_by_name``)."""
    norm = normalize_name(name)
    if not norm:
        return None
    return (
        await db.execute(
            select(Exercise).where(
                _visible_clause(household_id),
                Exercise.archived_at.is_(None),
                func.lower(func.trim(Exercise.name)) == norm,
            )
        )
    ).scalars().first()


async def _load_visible(
    db: AsyncSession, exercise_id: uuid.UUID, household_id: uuid.UUID
) -> Exercise | None:
    return (
        await db.execute(
            select(Exercise).where(
                Exercise.id == exercise_id, _visible_clause(household_id)
            )
        )
    ).scalar_one_or_none()


async def create_exercise(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ExerciseCreate,
) -> tuple[ExerciseResponse, bool]:
    """Create a household-custom exercise. Idempotent by normalized name: if the
    name already matches a visible exercise (global or this household's custom),
    that existing row is returned and ``created`` is False."""
    norm = normalize_name(data.name)
    if norm:
        existing = (
            await db.execute(
                select(Exercise).where(
                    _visible_clause(household_id),
                    Exercise.archived_at.is_(None),
                    func.lower(func.trim(Exercise.name)) == norm,
                )
            )
        ).scalars().first()
        if existing is not None:
            return _exercise_response(existing), False

    ex = Exercise(
        household_id=household_id,
        created_by_user_id=user_id,
        name=data.name,
        muscle_groups=list(data.muscle_groups or []),
        equipment_type=data.equipment_type,
        tracking_type=data.tracking_type,
        is_global=False,
    )
    db.add(ex)
    await db.commit()
    await db.refresh(ex)
    return _exercise_response(ex), True


async def update_exercise(
    db: AsyncSession,
    exercise_id: uuid.UUID,
    household_id: uuid.UUID,
    data: ExerciseUpdate,
) -> ExerciseResponse | None:
    """Update a household-custom exercise. Global rows are read-only (returns
    None so the router answers 404 — a household cannot edit the shared library)."""
    ex = await _load_visible(db, exercise_id, household_id)
    if ex is None or ex.is_global or ex.household_id != household_id:
        return None
    for field in data.model_fields_set:
        setattr(ex, field, getattr(data, field))
    await db.commit()
    await db.refresh(ex)
    return _exercise_response(ex)


async def archive_exercise(
    db: AsyncSession, exercise_id: uuid.UUID, household_id: uuid.UUID
) -> bool:
    """Soft-delete a household-custom exercise. Global rows cannot be archived."""
    ex = await _load_visible(db, exercise_id, household_id)
    if ex is None or ex.is_global or ex.household_id != household_id:
        return False
    ex.archived_at = func.now()
    await db.commit()
    return True
