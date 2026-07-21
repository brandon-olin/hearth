"""workouts-001b: retire the legacy Workout/ExerciseEntry model.

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-20

Migration 0048 promoted the legacy ``workouts`` / ``exercise_entries`` tables to
the normalized session/exercise/set model but LEFT THE LEGACY TABLES IN PLACE so
the old endpoints kept working during the UI cutover. This revision removes them:
the frontend, MCP tools, and AI-chat tools now speak the new model exclusively.

DATA SAFETY — the reason this is not a two-line drop
────────────────────────────────────────────────────
0048's ``_backfill`` skips ENTIRELY if any ``workout_sessions`` row already
exists ("backfill skipped — N workout_sessions already present"). On a database
where a session was created through the new API *before* 0048 ran, the legacy
rows were therefore NEVER copied forward. Dropping the tables there would destroy
them. The legacy endpoints also stayed writable between 0048 and this revision,
so fresh legacy rows may exist that 0048 never saw.

So before dropping, this migration:

  1. Builds the set of legacy workouts that already have a corresponding
     ``workout_sessions`` row. Correspondence keys on
     ``(household_id, created_by_user_id, created_at)`` — 0048 copied the legacy
     workout's ``created_at`` verbatim onto the session it created, and a
     new-API session carries its own ``now()`` timestamp, so this microsecond-
     precision key distinguishes "already migrated by 0048" from "unrelated
     session" without any false positives.
  2. Migrates every legacy workout NOT in that set forward, using the SAME
     translation logic as 0048's ``_backfill`` (exercise name → catalog
     resolution, aggregate metrics → first-class sets). It stamps the new
     session's ``created_at`` with the legacy workout's ``created_at`` too, so a
     re-run would detect it as already migrated.
  3. Only then drops ``exercise_entries`` and ``workouts``, printing the counts
     it moved.

All table operations are guarded by an existence check via the inspector, so the
migration is a no-op-safe on any tier where the legacy tables are already absent
(e.g. a fresh SQLite/Tauri DB built from ``create_all()`` and stamped at head,
where the legacy models no longer exist). No dialect-specific SQL is used and all
data work goes through typed Core ``sa.table()``s — portable across Postgres and
SQLite (api/CLAUDE.md).

IRREVERSIBLE: ``downgrade`` recreates the legacy table *structure* so the schema
can be walked backwards, but it CANNOT restore the dropped rows. The data lived
only in these tables; once dropped it exists solely in the new session/exercise/
set tables. Treat this revision as forward-only for data.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

# Same single source of truth 0048 uses — the runtime seed list and the name
# normalizer. Keeps the safety-net's name→exercise resolution identical to 0048.
from life_dashboard.domains.workouts.seed_data import GLOBAL_EXERCISES, normalize_name

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


# ── Core table handles (types match the real columns; see 0048 for rationale) ───
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

# Legacy exercise_type → new tracking_type (identical mapping to 0048).
_TRACKING_BY_LEGACY_TYPE = {
    "strength": "reps",
    "cardio": "distance",
    "hiit": "duration",
    "flexibility": "duration",
    "other": "reps",
}


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
    """Translate a legacy entry's aggregate metrics into first-class set rows.
    Identical translation to 0048's ``_build_sets_for_entry``."""
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
    else:  # flexibility / other / unknown
        out.append({**base, "set_number": 1,
                    "duration_seconds": _as_int(m.get("duration_seconds"))})
    for row in out:
        row["id"] = uuid.uuid4()
    return out


def _globals_by_norm(bind, now: datetime) -> dict[str, uuid.UUID]:
    """Return {normalized_name: id} for every global exercise, seeding any that
    are somehow missing (0048 already seeds them; this only fills gaps so name
    resolution below never fails)."""
    existing = {
        normalize_name(name): eid
        for eid, name in bind.execute(
            sa.select(_exercises.c.id, _exercises.c.name).where(
                _exercises.c.is_global.is_(True)
            )
        ).all()
    }
    missing = []
    for spec in GLOBAL_EXERCISES:
        norm = normalize_name(spec["name"])
        if norm in existing:
            continue
        new_id = uuid.uuid4()
        existing[norm] = new_id
        missing.append({
            "id": new_id, "household_id": None, "created_by_user_id": None,
            "name": spec["name"], "muscle_groups": list(spec.get("muscle_groups") or []),
            "equipment_type": spec.get("equipment_type"),
            "tracking_type": spec["tracking_type"], "is_global": True,
            "created_at": now, "updated_at": now,
        })
    if missing:
        bind.execute(sa.insert(_exercises), missing)
        print(f"[0049] seeded {len(missing)} missing global exercises")
    return existing


def _safety_net_backfill(bind, now: datetime) -> None:
    """Migrate any legacy workout that 0048 never copied forward, then leave the
    drop to the caller. Correspondence with an existing session keys on
    (household_id, created_by_user_id, created_at) — 0048 stamped the session's
    created_at with the legacy workout's created_at, so an already-migrated
    workout matches a session by this microsecond-precision tuple."""
    workouts = bind.execute(
        sa.select(
            _legacy_workouts.c.id, _legacy_workouts.c.household_id,
            _legacy_workouts.c.created_by_user_id, _legacy_workouts.c.name,
            _legacy_workouts.c.workout_date, _legacy_workouts.c.notes,
            _legacy_workouts.c.created_at,
        )
    ).all()
    if not workouts:
        print("[0049] safety net: no legacy workouts present")
        return

    # Keys of legacy workouts already represented by a session (migrated by 0048).
    existing_keys = {
        (hh, uid, created_at)
        for hh, uid, created_at in bind.execute(
            sa.select(
                _sessions.c.household_id, _sessions.c.created_by_user_id,
                _sessions.c.created_at,
            )
        ).all()
    }
    unmigrated = [
        w for w in workouts
        if (w.household_id, w.created_by_user_id, w.created_at) not in existing_keys
    ]
    print(
        f"[0049] safety net: {len(workouts)} legacy workouts, "
        f"{len(workouts) - len(unmigrated)} already migrated by 0048, "
        f"{len(unmigrated)} to migrate now"
    )
    if not unmigrated:
        return

    globals_by_norm = _globals_by_norm(bind, now)

    unmigrated_ids = [w.id for w in unmigrated]
    entries_by_workout: dict[uuid.UUID, list] = {}
    for row in bind.execute(
        sa.select(
            _legacy_entries.c.id, _legacy_entries.c.workout_id,
            _legacy_entries.c.name, _legacy_entries.c.type,
            _legacy_entries.c.sort_order, _legacy_entries.c.metrics,
            _legacy_entries.c.notes,
        )
        .where(_legacy_entries.c.workout_id.in_(unmigrated_ids))
        .order_by(_legacy_entries.c.sort_order.asc())
    ).all():
        entries_by_workout.setdefault(row.workout_id, []).append(row)

    # Per-household cache of minted custom exercises, keyed by normalized name.
    custom_by_household: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    new_customs: list[dict] = []
    session_rows: list[dict] = []
    se_rows: list[dict] = []
    set_rows: list[dict] = []

    def resolve_exercise(hh_id, owner_id, name, legacy_type) -> uuid.UUID:
        norm = normalize_name(name)
        if norm and norm in globals_by_norm:
            return globals_by_norm[norm]
        cache = custom_by_household.setdefault(hh_id, {})
        if norm in cache:
            return cache[norm]
        new_id = uuid.uuid4()
        cache[norm] = new_id
        new_customs.append({
            "id": new_id, "household_id": hh_id, "created_by_user_id": owner_id,
            "name": name, "muscle_groups": [], "equipment_type": None,
            "tracking_type": _TRACKING_BY_LEGACY_TYPE.get(legacy_type, "reps"),
            "is_global": False, "created_at": now, "updated_at": now,
        })
        return new_id

    for w in workouts:
        if (w.household_id, w.created_by_user_id, w.created_at) in existing_keys:
            continue  # already migrated by 0048 — leave the existing session alone
        session_id = uuid.uuid4()
        # Anchor date-only legacy workouts at NOON UTC (same reasoning as 0048:
        # midnight UTC rolls back a calendar day in the Americas). Copy the legacy
        # created_at so a re-run detects this session as already migrated.
        started = datetime.combine(w.workout_date, time(12, 0), tzinfo=UTC) \
            if w.workout_date else (w.created_at or now)
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
        f"[0049] safety net migrated: {len(session_rows)} sessions, "
        f"{len(se_rows)} session_exercises, {len(set_rows)} sets, "
        f"{len(new_customs)} custom exercises"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # If the legacy tables are already gone (fresh SQLite/Tauri DB stamped at
    # head, where the models no longer declare them), there is nothing to do.
    if "workouts" in tables:
        _safety_net_backfill(bind, datetime.now(UTC))

    if "exercise_entries" in tables:
        op.drop_table("exercise_entries")
        print("[0049] dropped exercise_entries")
    if "workouts" in tables:
        op.drop_table("workouts")
        print("[0049] dropped workouts")


def downgrade() -> None:
    """Recreate the legacy table STRUCTURE only. The dropped rows cannot be
    restored — they existed solely in these tables before the upgrade migrated
    them into the session/exercise/set model. This downgrade lets the schema
    walk backwards; it is not a data rollback."""
    op.create_table(
        "workouts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(),
                  sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("workout_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        # VisibilityMixin columns (present on the legacy Workout model).
        sa.Column("visibility", sa.String(), nullable=False, server_default="personal"),
        sa.Column("shared_with_user_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "exercise_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workout_id", sa.Uuid(),
                  sa.ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "strength", "cardio", "hiit", "flexibility", "other",
                native_enum=False, name="exercise_type", create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
