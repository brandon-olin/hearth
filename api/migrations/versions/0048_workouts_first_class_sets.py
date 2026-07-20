"""workouts-001: exercise library, shared templates, first-class sets.

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-20

Promotes the legacy Workout/ExerciseEntry model (an aggregate `metrics` JSONB on
each entry) to a normalized model: an exercise catalog, household-shared
templates with superset groups, and personal sessions whose sets are first-class
rows. The legacy tables are LEFT IN PLACE so the existing /workouts endpoints and
frontend keep working during the workouts-002..005 UI migration.

Three jobs, all portable across Postgres and SQLite (no dialect-specific SQL, all
data work done through typed Core `sa.table()`s so binds render correctly on both
engines — see api/CLAUDE.md):

1. Create the six new tables + indexes.
2. Seed the ~60 global exercises (household_id NULL, is_global true). Idempotent:
   re-running inserts only names not already present as global rows.
3. Backfill legacy workouts → workout_sessions and exercise_entries →
   session_exercises + workout_sets. Free-text entry names are deduped against
   the global catalog by normalized name; unmatched names become household-custom
   exercises. The name→exercise resolution is printed for the record. Guarded by a
   session-count check so a second run is a no-op.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

# Import the canonical seed list so the migration and the runtime seed helper can
# never drift (api/src/.../workouts/seed_data.py is the single source of truth).
from life_dashboard.domains.workouts.seed_data import GLOBAL_EXERCISES, normalize_name

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


# ── Constrained VARCHAR + CHECK enums (native_enum=False → portable) ─────────────
_tracking_type = sa.Enum(
    "reps", "duration", "distance",
    native_enum=False, name="exercise_tracking_type", create_constraint=True,
)
_weight_unit = sa.Enum(
    "lbs", "kg",
    native_enum=False, name="workout_weight_unit", create_constraint=True,
)
_distance_unit = sa.Enum(
    "km", "mi",
    native_enum=False, name="workout_distance_unit", create_constraint=True,
)


def _create_tables() -> None:
    op.create_table(
        "exercises",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(),
                  sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("muscle_groups", sa.JSON(), nullable=True),
        sa.Column("equipment_type", sa.Text(), nullable=True),
        sa.Column("tracking_type", _tracking_type, nullable=False),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_exercises_household_id", "exercises", ["household_id"])

    op.create_table(
        "workout_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(),
                  sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_workout_templates_household_id", "workout_templates", ["household_id"]
    )

    op.create_table(
        "template_exercises",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("template_id", sa.Uuid(),
                  sa.ForeignKey("workout_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_id", sa.Uuid(),
                  sa.ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("superset_group_id", sa.Uuid(), nullable=True),
        sa.Column("default_sets", sa.Integer(), nullable=True),
        sa.Column("default_reps", sa.Integer(), nullable=True),
        sa.Column("default_weight", sa.Numeric(7, 2), nullable=True),
        sa.Column("default_rest_seconds", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_template_exercises_template_id", "template_exercises", ["template_id"]
    )

    op.create_table(
        "workout_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(),
                  sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_id", sa.Uuid(),
                  sa.ForeignKey("workout_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_workout_sessions_hh_user_started",
        "workout_sessions", ["household_id", "created_by_user_id", "started_at"],
    )
    op.create_index(
        "ix_workout_sessions_template_user",
        "workout_sessions", ["template_id", "created_by_user_id"],
    )

    op.create_table(
        "session_exercises",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(),
                  sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_id", sa.Uuid(),
                  sa.ForeignKey("exercises.id"), nullable=False),
        sa.Column("template_exercise_id", sa.Uuid(),
                  sa.ForeignKey("template_exercises.id", ondelete="SET NULL"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("superset_group_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_session_exercises_session_id", "session_exercises", ["session_id"]
    )
    op.create_index(
        "ix_session_exercises_exercise_id", "session_exercises", ["exercise_id"]
    )
    op.create_index(
        "ix_session_exercises_template_exercise_id",
        "session_exercises", ["template_exercise_id"],
    )

    op.create_table(
        "workout_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_exercise_id", sa.Uuid(),
                  sa.ForeignKey("session_exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("target_reps", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Numeric(7, 2), nullable=True),
        sa.Column("weight_unit", _weight_unit, nullable=True),
        sa.Column("distance_meters", sa.Numeric(10, 2), nullable=True),
        sa.Column("distance_unit", _distance_unit, nullable=True),
        sa.Column("rest_seconds", sa.Integer(), nullable=True),
        sa.Column("is_warmup", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("rpe", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_workout_sets_session_exercise_id", "workout_sets", ["session_exercise_id"]
    )


# ── Core table handles for the data steps (types match the real columns) ────────
# tracking_type / weight_unit / distance_unit are VARCHAR + CHECK (native_enum=
# False), so sa.String() is the correct Core type here — asyncpg then binds a
# plain VARCHAR, which the column accepts.
_exercises = sa.table(
    "exercises",
    sa.column("id", sa.Uuid()),
    sa.column("household_id", sa.Uuid()),
    sa.column("created_by_user_id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("muscle_groups", sa.JSON()),
    sa.column("equipment_type", sa.Text()),
    sa.column("tracking_type", sa.String()),
    sa.column("is_global", sa.Boolean()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_legacy_workouts = sa.table(
    "workouts",
    sa.column("id", sa.Uuid()),
    sa.column("household_id", sa.Uuid()),
    sa.column("created_by_user_id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("workout_date", sa.Date()),
    sa.column("notes", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_legacy_entries = sa.table(
    "exercise_entries",
    sa.column("id", sa.Uuid()),
    sa.column("workout_id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("type", sa.String()),
    sa.column("sort_order", sa.Integer()),
    sa.column("metrics", sa.JSON()),
    sa.column("notes", sa.Text()),
)
_sessions = sa.table(
    "workout_sessions",
    sa.column("id", sa.Uuid()),
    sa.column("household_id", sa.Uuid()),
    sa.column("created_by_user_id", sa.Uuid()),
    sa.column("template_id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("ended_at", sa.DateTime(timezone=True)),
    sa.column("notes", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_session_exercises = sa.table(
    "session_exercises",
    sa.column("id", sa.Uuid()),
    sa.column("session_id", sa.Uuid()),
    sa.column("exercise_id", sa.Uuid()),
    sa.column("template_exercise_id", sa.Uuid()),
    sa.column("position", sa.Integer()),
    sa.column("superset_group_id", sa.Uuid()),
    sa.column("notes", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_workout_sets = sa.table(
    "workout_sets",
    sa.column("id", sa.Uuid()),
    sa.column("session_exercise_id", sa.Uuid()),
    sa.column("set_number", sa.Integer()),
    sa.column("reps", sa.Integer()),
    sa.column("target_reps", sa.Integer()),
    sa.column("duration_seconds", sa.Integer()),
    sa.column("weight", sa.Numeric(7, 2)),
    sa.column("weight_unit", sa.String()),
    sa.column("distance_meters", sa.Numeric(10, 2)),
    sa.column("distance_unit", sa.String()),
    sa.column("rest_seconds", sa.Integer()),
    sa.column("is_warmup", sa.Boolean()),
    sa.column("rpe", sa.Integer()),
    sa.column("completed_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

# Legacy exercise_type → new tracking_type. cardio maps to distance (its metrics
# carried distance_meters); timed/mobility work maps to duration.
_TRACKING_BY_LEGACY_TYPE = {
    "strength": "reps",
    "cardio": "distance",
    "hiit": "duration",
    "flexibility": "duration",
    "other": "reps",
}


def _seed_global_exercises(bind, now: datetime) -> dict[str, uuid.UUID]:
    """Insert missing global exercises; return {normalized_name: id} for ALL
    globals (pre-existing + newly seeded)."""
    existing = {
        normalize_name(name): eid
        for eid, name in bind.execute(
            sa.select(_exercises.c.id, _exercises.c.name).where(
                _exercises.c.is_global.is_(True)
            )
        ).all()
    }
    rows = []
    for spec in GLOBAL_EXERCISES:
        norm = normalize_name(spec["name"])
        if norm in existing:
            continue
        new_id = uuid.uuid4()
        existing[norm] = new_id
        rows.append(
            {
                "id": new_id,
                "household_id": None,
                "created_by_user_id": None,
                "name": spec["name"],
                "muscle_groups": list(spec.get("muscle_groups") or []),
                "equipment_type": spec.get("equipment_type"),
                "tracking_type": spec["tracking_type"],
                "is_global": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    if rows:
        bind.execute(sa.insert(_exercises), rows)
    print(f"[0048] global exercises: seeded {len(rows)}, total {len(existing)}")
    return existing


def _as_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_decimal(value) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except (TypeError, ValueError):
        return None


def _build_sets_for_entry(se_id: uuid.UUID, legacy_type: str, metrics) -> list[dict]:
    """Translate a legacy entry's aggregate metrics into first-class set rows."""
    m = metrics if isinstance(metrics, dict) else {}
    base = {
        "session_exercise_id": se_id, "reps": None, "target_reps": None,
        "duration_seconds": None, "weight": None, "weight_unit": None,
        "distance_meters": None, "distance_unit": None, "rest_seconds": None,
        "is_warmup": False, "rpe": None, "completed_at": None,
    }
    out: list[dict] = []
    if legacy_type == "strength":
        n = max(_as_int(m.get("sets")) or 1, 1)
        reps = _as_int(m.get("reps"))
        weight = _as_decimal(m.get("weight_kg"))
        for i in range(1, n + 1):
            out.append({**base, "set_number": i, "reps": reps, "weight": weight,
                        "weight_unit": "kg" if weight is not None else None})
    elif legacy_type == "cardio":
        out.append({**base, "set_number": 1,
                    "duration_seconds": _as_int(m.get("duration_seconds")),
                    "distance_meters": _as_decimal(m.get("distance_meters"))})
    elif legacy_type == "hiit":
        n = max(_as_int(m.get("rounds")) or 1, 1)
        work = _as_int(m.get("work_seconds"))
        rest = _as_int(m.get("rest_seconds"))
        for i in range(1, n + 1):
            out.append({**base, "set_number": i,
                        "duration_seconds": work, "rest_seconds": rest})
    else:  # flexibility / other / unknown — preserve one set with any duration.
        out.append({**base, "set_number": 1,
                    "duration_seconds": _as_int(m.get("duration_seconds"))})
    # Core inserts carry no default — stamp a fresh PK on each row.
    for row in out:
        row["id"] = uuid.uuid4()
    return out


def _backfill(bind, globals_by_norm: dict[str, uuid.UUID], now: datetime) -> None:
    """Copy legacy workouts/entries forward. No-op if any session already exists
    (idempotency guard for re-runs)."""
    already = bind.execute(
        sa.select(sa.func.count()).select_from(_sessions)
    ).scalar()
    if already:
        print(f"[0048] backfill skipped — {already} workout_sessions already present")
        return

    workouts = bind.execute(
        sa.select(
            _legacy_workouts.c.id, _legacy_workouts.c.household_id,
            _legacy_workouts.c.created_by_user_id, _legacy_workouts.c.name,
            _legacy_workouts.c.workout_date, _legacy_workouts.c.notes,
            _legacy_workouts.c.created_at,
        )
    ).all()
    if not workouts:
        print("[0048] backfill: no legacy workouts to migrate")
        return

    entries_by_workout: dict[uuid.UUID, list] = {}
    for row in bind.execute(
        sa.select(
            _legacy_entries.c.id, _legacy_entries.c.workout_id,
            _legacy_entries.c.name, _legacy_entries.c.type,
            _legacy_entries.c.sort_order, _legacy_entries.c.metrics,
            _legacy_entries.c.notes,
        ).order_by(_legacy_entries.c.sort_order.asc())
    ).all():
        entries_by_workout.setdefault(row.workout_id, []).append(row)

    # Per-household cache of custom exercises we mint, keyed by normalized name,
    # so the same free-text name across workouts resolves to one row.
    custom_by_household: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    new_customs: list[dict] = []
    session_rows: list[dict] = []
    se_rows: list[dict] = []
    set_rows: list[dict] = []
    mapping: dict[str, str] = {}  # name → "global" | "custom" (for the report)

    def resolve_exercise(hh_id, owner_id, name, legacy_type) -> uuid.UUID:
        norm = normalize_name(name)
        if norm and norm in globals_by_norm:
            mapping.setdefault(name, "global")
            return globals_by_norm[norm]
        cache = custom_by_household.setdefault(hh_id, {})
        if norm in cache:
            return cache[norm]
        new_id = uuid.uuid4()
        cache[norm] = new_id
        mapping[name] = "custom"
        new_customs.append({
            "id": new_id, "household_id": hh_id, "created_by_user_id": owner_id,
            "name": name, "muscle_groups": [], "equipment_type": None,
            "tracking_type": _TRACKING_BY_LEGACY_TYPE.get(legacy_type, "reps"),
            "is_global": False, "created_at": now, "updated_at": now,
        })
        return new_id

    for w in workouts:
        session_id = uuid.uuid4()
        # Anchor legacy date-only workouts at NOON UTC, not midnight: midnight UTC
        # renders as the previous calendar day in every negative-offset timezone
        # (US, the Americas), which would misplace the session on the calendar
        # (workouts-005). Noon UTC keeps the date stable across all common offsets.
        started = datetime.combine(w.workout_date, time(12, 0), tzinfo=UTC) \
            if w.workout_date else now
        session_rows.append({
            "id": session_id, "household_id": w.household_id,
            "created_by_user_id": w.created_by_user_id, "template_id": None,
            "name": w.name, "started_at": started, "ended_at": None,
            "notes": w.notes, "created_at": w.created_at or now, "updated_at": now,
        })
        for entry in entries_by_workout.get(w.id, []):
            eid = resolve_exercise(
                w.household_id, w.created_by_user_id, entry.name, entry.type
            )
            se_id = uuid.uuid4()
            se_rows.append({
                "id": se_id, "session_id": session_id, "exercise_id": eid,
                "template_exercise_id": None,
                "position": entry.sort_order if entry.sort_order is not None else 0,
                "superset_group_id": None, "notes": entry.notes,
                "created_at": now, "updated_at": now,
            })
            for s in _build_sets_for_entry(se_id, entry.type, entry.metrics):
                set_rows.append({**s, "created_at": now, "updated_at": now})

    # Insert in FK order.
    if new_customs:
        bind.execute(sa.insert(_exercises), new_customs)
    if session_rows:
        bind.execute(sa.insert(_sessions), session_rows)
    if se_rows:
        bind.execute(sa.insert(_session_exercises), se_rows)
    if set_rows:
        bind.execute(sa.insert(_workout_sets), set_rows)

    print(
        f"[0048] backfill: {len(session_rows)} sessions, {len(se_rows)} "
        f"session_exercises, {len(set_rows)} sets, {len(new_customs)} custom exercises"
    )
    for name, kind in sorted(mapping.items()):
        print(f"[0048]   {kind:6s}  {name!r}")


def upgrade() -> None:
    _create_tables()
    bind = op.get_bind()
    now = datetime.now(UTC)
    globals_by_norm = _seed_global_exercises(bind, now)
    _backfill(bind, globals_by_norm, now)


def downgrade() -> None:
    op.drop_table("workout_sets")
    op.drop_table("session_exercises")
    op.drop_table("workout_sessions")
    op.drop_table("template_exercises")
    op.drop_table("workout_templates")
    op.drop_table("exercises")
