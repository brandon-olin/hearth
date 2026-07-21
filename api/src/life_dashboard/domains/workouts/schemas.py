import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── workouts-001 constrained value types ────────────────────────────────────────
TrackingType = Literal["reps", "duration", "distance"]
WeightUnit = Literal["lbs", "kg"]
DistanceUnit = Literal["km", "mi"]


# ══ workouts-001: exercise library, shared templates, personal sessions ═════════
# Exercise library, shared templates with superset groups, personal sessions with
# first-class sets. See models.py for the scoping rationale. (The legacy
# Workout/ExerciseEntry schemas this replaced were removed in workouts-001b.)

_NAME_MAX = 200
_NOTES_MAX = 2000


# ── Exercise catalog ─────────────────────────────────────────────────────────

class ExerciseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    muscle_groups: list[str] = Field(default_factory=list)
    equipment_type: str | None = Field(default=None, max_length=_NAME_MAX)
    tracking_type: TrackingType = "reps"


class ExerciseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    muscle_groups: list[str] | None = None
    equipment_type: str | None = Field(default=None, max_length=_NAME_MAX)
    tracking_type: TrackingType | None = None


class ExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    name: str
    muscle_groups: list[str] = []
    equipment_type: str | None
    tracking_type: str
    is_global: bool
    created_at: datetime
    updated_at: datetime


class ExerciseListResponse(BaseModel):
    items: list[ExerciseResponse]
    total: int
    limit: int
    offset: int


# ── Template exercises ───────────────────────────────────────────────────────

class TemplateExerciseCreate(BaseModel):
    exercise_id: uuid.UUID
    position: int | None = Field(default=None, ge=0)
    superset_group_id: uuid.UUID | None = None
    default_sets: int | None = Field(default=None, ge=1, le=50)
    default_reps: int | None = Field(default=None, ge=0, le=1000)
    default_weight: float | None = Field(default=None, ge=0)
    default_rest_seconds: int | None = Field(default=None, ge=0, le=86400)
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)


class TemplateExerciseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int | None = Field(default=None, ge=0)
    # Explicit None clears the superset assignment; omitting leaves it unchanged.
    superset_group_id: uuid.UUID | None = None
    default_sets: int | None = Field(default=None, ge=1, le=50)
    default_reps: int | None = Field(default=None, ge=0, le=1000)
    default_weight: float | None = Field(default=None, ge=0)
    default_rest_seconds: int | None = Field(default=None, ge=0, le=86400)
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)


class TemplateExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    exercise_id: uuid.UUID
    position: int
    superset_group_id: uuid.UUID | None
    default_sets: int | None
    default_reps: int | None
    default_weight: float | None
    default_rest_seconds: int | None
    notes: str | None
    # Convenience for clients rendering the row without a second lookup.
    exercise: ExerciseResponse | None = None


# ── Templates ────────────────────────────────────────────────────────────────

class WorkoutTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_NOTES_MAX)
    estimated_duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    exercises: list[TemplateExerciseCreate] = Field(default_factory=list)


class WorkoutTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_NOTES_MAX)
    estimated_duration_minutes: int | None = Field(default=None, ge=0, le=1440)


class WorkoutTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    name: str
    description: str | None
    estimated_duration_minutes: int | None
    created_at: datetime
    updated_at: datetime
    # Derived per-request, never stored columns:
    exercise_count: int = 0
    # MAX(started_at) of the CURRENT user's sessions for this template, or None.
    last_used_at: datetime | None = None


class WorkoutTemplateDetailResponse(WorkoutTemplateResponse):
    exercises: list[TemplateExerciseResponse] = []


class WorkoutTemplateListResponse(BaseModel):
    items: list[WorkoutTemplateResponse]
    total: int
    limit: int
    offset: int


# ── Workout sets ─────────────────────────────────────────────────────────────

class WorkoutSetCreate(BaseModel):
    set_number: int | None = Field(default=None, ge=1, le=100)
    reps: int | None = Field(default=None, ge=0, le=1000)
    target_reps: int | None = Field(default=None, ge=0, le=1000)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    weight: float | None = Field(default=None, ge=0)
    weight_unit: WeightUnit | None = None
    distance_meters: float | None = Field(default=None, ge=0)
    distance_unit: DistanceUnit | None = None
    rest_seconds: int | None = Field(default=None, ge=0, le=86400)
    is_warmup: bool = False
    rpe: int | None = Field(default=None, ge=1, le=10)
    completed_at: datetime | None = None


class WorkoutSetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_number: int | None = Field(default=None, ge=1, le=100)
    reps: int | None = Field(default=None, ge=0, le=1000)
    target_reps: int | None = Field(default=None, ge=0, le=1000)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    weight: float | None = Field(default=None, ge=0)
    weight_unit: WeightUnit | None = None
    distance_meters: float | None = Field(default=None, ge=0)
    distance_unit: DistanceUnit | None = None
    rest_seconds: int | None = Field(default=None, ge=0, le=86400)
    is_warmup: bool | None = None
    rpe: int | None = Field(default=None, ge=1, le=10)
    completed_at: datetime | None = None


class WorkoutSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_exercise_id: uuid.UUID
    set_number: int
    reps: int | None
    target_reps: int | None
    duration_seconds: int | None
    weight: float | None
    weight_unit: str | None
    distance_meters: float | None
    distance_unit: str | None
    rest_seconds: int | None
    is_warmup: bool
    rpe: int | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── Session exercises ────────────────────────────────────────────────────────

class SessionExerciseCreate(BaseModel):
    exercise_id: uuid.UUID
    template_exercise_id: uuid.UUID | None = None
    position: int | None = Field(default=None, ge=0)
    superset_group_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)
    sets: list[WorkoutSetCreate] = Field(default_factory=list)


class SessionExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    exercise_id: uuid.UUID
    template_exercise_id: uuid.UUID | None
    position: int
    superset_group_id: uuid.UUID | None
    notes: str | None
    exercise: ExerciseResponse | None = None
    sets: list[WorkoutSetResponse] = []


# ── Sessions ─────────────────────────────────────────────────────────────────

class WorkoutSessionCreate(BaseModel):
    # When template_id is set and `exercises` is empty, the session is
    # materialized from the template's slots and default sets.
    template_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=_NAME_MAX)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)
    exercises: list[SessionExerciseCreate] = Field(default_factory=list)


class WorkoutSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=_NAME_MAX)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=_NOTES_MAX)


class WorkoutSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    template_id: uuid.UUID | None
    name: str | None
    started_at: datetime
    ended_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    exercise_count: int = 0


class WorkoutSessionDetailResponse(WorkoutSessionResponse):
    exercises: list[SessionExerciseResponse] = []


class WorkoutSessionListResponse(BaseModel):
    items: list[WorkoutSessionResponse]
    total: int
    limit: int
    offset: int


# ══ workouts-003: live logging (ghost values, finish summary, save-as-template) ═
# All three are read-or-derive over the existing tables — workouts-003 adds no
# columns and no migration.


class PrefillSet(BaseModel):
    """One suggested set. These are GHOST values: the client renders them muted
    and never persists them until the member actually logs the set."""

    set_number: int
    reps: int | None
    weight: float | None
    weight_unit: str | None
    is_warmup: bool


class SessionExercisePrefill(BaseModel):
    """Ghost-value suggestions for one exercise in the session.

    ``source`` says where they came from:
      * ``history``  — the CURRENT member's most recent session for this slot
      * ``template`` — the template slot's ``default_weight`` / ``default_reps``
      * ``none``     — nothing to suggest; the client shows empty fields

    Never another member's data: history is keyed on the slot AND filtered to
    ``created_by_user_id = the requesting member`` (see prefill scoping in
    sessions_service).
    """

    session_exercise_id: uuid.UUID
    template_exercise_id: uuid.UUID | None
    source: Literal["history", "template", "none"]
    #: Rest countdown for this slot, from the template's default_rest_seconds.
    #: NULL means the client falls back to its own default (90s).
    rest_seconds: int | None
    sets: list[PrefillSet]


class SessionPrefillResponse(BaseModel):
    session_id: uuid.UUID
    items: list[SessionExercisePrefill]


class WorkoutSessionSummary(BaseModel):
    """What the finish screen reports. Every number is derived here so the UI and
    the agent surface can never disagree about the arithmetic.

    A set counts as logged only when ``completed_at`` is set — typing a value
    without checking the set off does not count. Warmup sets are excluded from
    ``working_volume`` and from ``working_sets_completed``.
    """

    session_id: uuid.UUID
    name: str | None
    started_at: datetime
    ended_at: datetime | None
    #: Wall-clock seconds from started_at to ended_at (0 if the clock is skewed).
    duration_seconds: int
    #: Σ(weight × reps) over completed, non-warmup sets. Bodyweight sets (weight
    #: NULL) contribute 0 but still count toward working_sets_completed.
    working_volume: float
    #: The unit ``working_volume`` is expressed in, or NULL when no weighted set
    #: was logged. Mixed-unit sessions report the unit of the first weighted set.
    volume_unit: str | None
    working_sets_completed: int
    warmup_sets_completed: int
    #: Exercises with at least one completed working set.
    exercises_completed: int
    exercise_count: int
    #: False for a blank session — the save-as-template prompt only fires then.
    from_template: bool


class SaveAsTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)


# ══ workouts-004: per-exercise progress ════════════════════════════════════════
# Read-only projections over the same first-class sets. Every derived number the
# charts show (estimated 1RM, volume, max weight) is computed by the client from
# this payload and NEVER stored — see progress_service for the scoping rules.


class ProgressSet(BaseModel):
    """One working set as it feeds the progress charts.

    Warmup sets never reach this schema — they are excluded from every
    calculation, so they are excluded from the payload. ``is_warmup`` is
    therefore always ``False``; it is carried anyway so a client can assert it.
    """

    reps: int | None
    weight: float | None
    is_warmup: bool
    #: Planned reps. NULL means no target was set — that is NOT a failed set.
    target_reps: int | None


class ProgressSession(BaseModel):
    """One session's working sets for a single exercise."""

    session_id: uuid.UUID
    #: UTC calendar date of ``started_at`` (sessions are anchored at noon UTC).
    session_date: date
    sets: list[ProgressSet]


class ExerciseProgressResponse(BaseModel):
    exercise: ExerciseResponse
    #: The most recent ``limit`` sessions, ordered OLDEST to NEWEST.
    sessions: list[ProgressSession]


class ProgressExerciseSummary(BaseModel):
    """A row in the progress list: one exercise this member has logged enough
    times to have a trend."""

    exercise_id: uuid.UUID
    name: str
    tracking_type: str
    session_count: int
    last_logged_at: datetime
    #: True when no logged working set carried a weight — the client shows the
    #: reps chart only, never an empty weight chart.
    is_bodyweight: bool
    #: Heaviest working set per session over the last few sessions, oldest to
    #: newest (max reps instead, for bodyweight exercises).
    sparkline: list[float]


class ProgressExerciseListResponse(BaseModel):
    items: list[ProgressExerciseSummary]
