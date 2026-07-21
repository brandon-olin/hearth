"""HTTP surface for the workouts-001 refactor: exercise library, shared
templates (with superset groups), and personal sessions (with first-class sets).

Mounted at ``/workouts`` and registered in main.py BEFORE the legacy
``workouts_router`` so its static sub-paths (``/exercises``, ``/templates``,
``/sessions``) win over the legacy ``/workouts/{workout_id}`` catch-all. The
legacy endpoints (``GET /workouts``, ``/workouts/{id}``, ``/workouts/exercise-names``)
keep working unchanged for the existing frontend.

Business-rule violations from the service layer (``SupersetError``) map to 400;
missing or not-visible resources map to 404 (never distinguishing not-found from
not-permitted, per the API conventions).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.workouts import (
    exercises_service,
    progress_service,
    sessions_service,
    templates_service,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseCreate,
    ExerciseListResponse,
    ExerciseProgressResponse,
    ExerciseResponse,
    ExerciseUpdate,
    ProgressExerciseListResponse,
    SessionExerciseCreate,
    SessionExerciseResponse,
    TemplateExerciseCreate,
    TemplateExerciseResponse,
    TemplateExerciseUpdate,
    WorkoutSessionCreate,
    WorkoutSessionDetailResponse,
    WorkoutSessionListResponse,
    WorkoutSessionResponse,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetResponse,
    WorkoutSetUpdate,
    WorkoutTemplateCreate,
    WorkoutTemplateDetailResponse,
    WorkoutTemplateListResponse,
    WorkoutTemplateResponse,
    WorkoutTemplateUpdate,
)
from life_dashboard.domains.workouts.superset import SupersetError

router = APIRouter(prefix="/workouts", tags=["workouts"])

_NOT_FOUND = "Not found"


# ── Exercise catalog ─────────────────────────────────────────────────────────

@router.get("/exercises", response_model=ExerciseListResponse)
async def list_exercises(
    search: str | None = Query(default=None, max_length=200),
    sort: Literal["name", "recent"] = Query(
        default="name",
        description="'name' (alphabetical) or 'recent' (most-recently-used by you first).",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseListResponse:
    return await exercises_service.list_exercises(
        db, current_user.household_id, current_user.id,
        search=search, sort=sort, limit=limit, offset=offset,
    )


@router.post(
    "/exercises",
    response_model=ExerciseResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_exercise(
    data: ExerciseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseResponse:
    exercise, _created = await exercises_service.create_exercise(
        db, current_user.household_id, current_user.id, data
    )
    return exercise


@router.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
async def get_exercise(
    exercise_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseResponse:
    exercise = await exercises_service.get_exercise(
        db, exercise_id, current_user.household_id
    )
    if exercise is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return exercise


@router.patch("/exercises/{exercise_id}", response_model=ExerciseResponse)
async def update_exercise(
    exercise_id: uuid.UUID,
    data: ExerciseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseResponse:
    exercise = await exercises_service.update_exercise(
        db, exercise_id, current_user.household_id, data
    )
    if exercise is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return exercise


@router.delete("/exercises/{exercise_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_exercise(
    exercise_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await exercises_service.archive_exercise(
        db, exercise_id, current_user.household_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


# ── Progress (workouts-004) ──────────────────────────────────────────────────
#
# Declared before the ``/templates`` and ``/sessions`` groups purely for
# readability — the paths are distinct, so ordering carries no routing meaning
# here. Both reads are PERSONAL: the service filters created_by_user_id, so a
# second household member's sets can never reach this response.

@router.get("/progress", response_model=ProgressExerciseListResponse)
async def list_progress_exercises(
    min_sessions: int = Query(
        default=progress_service.MIN_SESSIONS,
        ge=1,
        le=50,
        description="Only list exercises YOU have logged in at least this many sessions.",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProgressExerciseListResponse:
    return await progress_service.list_progress_exercises(
        db, current_user.household_id, current_user.id,
        min_sessions=min_sessions, limit=limit,
    )


@router.get("/progress/{exercise_id}", response_model=ExerciseProgressResponse)
async def get_exercise_progress(
    exercise_id: uuid.UUID,
    limit: int = Query(
        default=20, ge=1, le=200,
        description="How many of the most recent sessions to return.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExerciseProgressResponse:
    progress = await progress_service.get_exercise_progress(
        db, exercise_id, current_user.household_id, current_user.id, limit=limit
    )
    if progress is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return progress


# ── Templates ────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=WorkoutTemplateListResponse)
async def list_templates(
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutTemplateListResponse:
    return await templates_service.list_templates(
        db, current_user.household_id, current_user.id,
        search=search, limit=limit, offset=offset,
    )


@router.post(
    "/templates",
    response_model=WorkoutTemplateDetailResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_template(
    data: WorkoutTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutTemplateDetailResponse:
    try:
        return await templates_service.create_template(
            db, current_user.household_id, current_user.id, data
        )
    except SupersetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/templates/{template_id}", response_model=WorkoutTemplateDetailResponse)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutTemplateDetailResponse:
    template = await templates_service.get_template(
        db, template_id, current_user.household_id, current_user.id
    )
    if template is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return template


@router.patch("/templates/{template_id}", response_model=WorkoutTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    data: WorkoutTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutTemplateResponse:
    template = await templates_service.update_template(
        db, template_id, current_user.household_id, data
    )
    if template is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return template


@router.delete("/templates/{template_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await templates_service.delete_template(
        db, template_id, current_user.household_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.post(
    "/templates/{template_id}/exercises",
    response_model=TemplateExerciseResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def add_template_exercise(
    template_id: uuid.UUID,
    data: TemplateExerciseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TemplateExerciseResponse:
    try:
        te = await templates_service.add_template_exercise(
            db, template_id, current_user.household_id, data
        )
    except SupersetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if te is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return te


@router.patch(
    "/templates/{template_id}/exercises/{te_id}",
    response_model=TemplateExerciseResponse,
)
async def update_template_exercise(
    template_id: uuid.UUID,
    te_id: uuid.UUID,
    data: TemplateExerciseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TemplateExerciseResponse:
    try:
        te = await templates_service.update_template_exercise(
            db, template_id, te_id, current_user.household_id, data
        )
    except SupersetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if te is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return te


@router.delete(
    "/templates/{template_id}/exercises/{te_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def remove_template_exercise(
    template_id: uuid.UUID,
    te_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await templates_service.remove_template_exercise(
        db, template_id, te_id, current_user.household_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


# ── Sessions ─────────────────────────────────────────────────────────────────

@router.get("/sessions", response_model=WorkoutSessionListResponse)
async def list_sessions(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutSessionListResponse:
    return await sessions_service.list_sessions(
        db, current_user.household_id, current_user.id,
        from_date=from_date, to_date=to_date, limit=limit, offset=offset,
    )


@router.post(
    "/sessions",
    response_model=WorkoutSessionDetailResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_session(
    data: WorkoutSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutSessionDetailResponse:
    try:
        session = await sessions_service.create_session(
            db, current_user.household_id, current_user.id, data
        )
    except SupersetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if session is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return session


@router.get("/sessions/{session_id}", response_model=WorkoutSessionDetailResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutSessionDetailResponse:
    session = await sessions_service.get_session(
        db, session_id, current_user.household_id, current_user.id
    )
    if session is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return session


@router.patch("/sessions/{session_id}", response_model=WorkoutSessionResponse)
async def update_session(
    session_id: uuid.UUID,
    data: WorkoutSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutSessionResponse:
    session = await sessions_service.update_session(
        db, session_id, current_user.household_id, current_user.id, data
    )
    if session is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return session


@router.delete("/sessions/{session_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await sessions_service.delete_session(
        db, session_id, current_user.household_id, current_user.id
    )
    if not ok:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.post(
    "/sessions/{session_id}/exercises",
    response_model=SessionExerciseResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def add_session_exercise(
    session_id: uuid.UUID,
    data: SessionExerciseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionExerciseResponse:
    try:
        se = await sessions_service.add_session_exercise(
            db, session_id, current_user.household_id, current_user.id, data
        )
    except SupersetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if se is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return se


@router.delete(
    "/sessions/{session_id}/exercises/{se_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def remove_session_exercise(
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await sessions_service.remove_session_exercise(
        db, session_id, se_id, current_user.household_id, current_user.id
    )
    if not ok:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.post(
    "/sessions/{session_id}/exercises/{se_id}/sets",
    response_model=WorkoutSetResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def add_set(
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    data: WorkoutSetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutSetResponse:
    ws = await sessions_service.add_set(
        db, session_id, se_id, current_user.household_id, current_user.id, data
    )
    if ws is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ws


@router.patch(
    "/sessions/{session_id}/exercises/{se_id}/sets/{set_id}",
    response_model=WorkoutSetResponse,
)
async def update_set(
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    set_id: uuid.UUID,
    data: WorkoutSetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkoutSetResponse:
    ws = await sessions_service.update_set(
        db, session_id, se_id, set_id, current_user.household_id, current_user.id, data
    )
    if ws is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ws


@router.delete(
    "/sessions/{session_id}/exercises/{se_id}/sets/{set_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def delete_set(
    session_id: uuid.UUID,
    se_id: uuid.UUID,
    set_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await sessions_service.delete_set(
        db, session_id, se_id, set_id, current_user.household_id, current_user.id
    )
    if not ok:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
