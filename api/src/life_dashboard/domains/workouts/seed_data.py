"""Canonical global exercise library (workouts-001).

The single source of truth for the ~60 app-wide seeded exercises. Both
migration 0048 (which inserts them at deploy time) and the test/dev seed helper
(``exercises_service.ensure_global_exercises``) read this list, so the catalog
can never drift between the two paths.

Each entry seeds one row with ``household_id = NULL`` and ``is_global = True``.
``tracking_type`` drives which fields the logging UI collects:

  * ``reps``     — sets of repetitions, optionally weighted (strength work).
  * ``duration`` — timed holds/intervals (planks, jump rope).
  * ``distance`` — cardio measured by distance (running, rowing, cycling).

Muscle-group slugs are lowercase and stable; the UI maps them to display labels.
Keep names Title Case and unique (case-insensitively) — the backfill dedupes
legacy free-text exercise names against these by normalized name.
"""
from __future__ import annotations


def _ex(name: str, muscles: str, equipment: str, tracking: str) -> dict:
    """Build one seed row. ``muscles`` is a space-separated list of slugs, kept
    compact so the table below stays readable on one line each."""
    return {
        "name": name,
        "muscle_groups": muscles.split(),
        "equipment_type": equipment,
        "tracking_type": tracking,
    }


GLOBAL_EXERCISES: list[dict] = [
    # ── Chest ──────────────────────────────────────────────────────────────
    _ex("Barbell Bench Press", "chest triceps shoulders", "barbell", "reps"),
    _ex("Incline Barbell Bench Press", "chest shoulders triceps", "barbell", "reps"),
    _ex("Dumbbell Bench Press", "chest triceps shoulders", "dumbbell", "reps"),
    _ex("Incline Dumbbell Press", "chest shoulders triceps", "dumbbell", "reps"),
    _ex("Dumbbell Fly", "chest", "dumbbell", "reps"),
    _ex("Cable Crossover", "chest", "cable", "reps"),
    _ex("Push-Up", "chest triceps core", "bodyweight", "reps"),
    _ex("Chest Dip", "chest triceps", "bodyweight", "reps"),

    # ── Back ───────────────────────────────────────────────────────────────
    _ex("Deadlift", "back hamstrings glutes", "barbell", "reps"),
    _ex("Pull-Up", "lats biceps", "bodyweight", "reps"),
    _ex("Chin-Up", "lats biceps", "bodyweight", "reps"),
    _ex("Bent-Over Barbell Row", "back lats biceps", "barbell", "reps"),
    _ex("Dumbbell Row", "back lats biceps", "dumbbell", "reps"),
    _ex("Lat Pulldown", "lats biceps", "cable", "reps"),
    _ex("Seated Cable Row", "back lats biceps", "cable", "reps"),
    _ex("T-Bar Row", "back lats", "barbell", "reps"),
    _ex("Face Pull", "shoulders traps", "cable", "reps"),

    # ── Legs ───────────────────────────────────────────────────────────────
    _ex("Back Squat", "quads glutes hamstrings", "barbell", "reps"),
    _ex("Front Squat", "quads glutes", "barbell", "reps"),
    _ex("Goblet Squat", "quads glutes", "dumbbell", "reps"),
    _ex("Leg Press", "quads glutes hamstrings", "machine", "reps"),
    _ex("Romanian Deadlift", "hamstrings glutes back", "barbell", "reps"),
    _ex("Walking Lunge", "quads glutes hamstrings", "dumbbell", "reps"),
    _ex("Bulgarian Split Squat", "quads glutes", "dumbbell", "reps"),
    _ex("Leg Extension", "quads", "machine", "reps"),
    _ex("Leg Curl", "hamstrings", "machine", "reps"),
    _ex("Calf Raise", "calves", "machine", "reps"),
    _ex("Hip Thrust", "glutes hamstrings", "barbell", "reps"),

    # ── Shoulders ──────────────────────────────────────────────────────────
    _ex("Overhead Press", "shoulders triceps", "barbell", "reps"),
    _ex("Dumbbell Shoulder Press", "shoulders triceps", "dumbbell", "reps"),
    _ex("Arnold Press", "shoulders triceps", "dumbbell", "reps"),
    _ex("Lateral Raise", "shoulders", "dumbbell", "reps"),
    _ex("Front Raise", "shoulders", "dumbbell", "reps"),
    _ex("Rear Delt Fly", "shoulders traps", "dumbbell", "reps"),
    _ex("Upright Row", "shoulders traps", "barbell", "reps"),
    _ex("Barbell Shrug", "traps", "barbell", "reps"),

    # ── Arms ───────────────────────────────────────────────────────────────
    _ex("Barbell Curl", "biceps", "barbell", "reps"),
    _ex("Dumbbell Curl", "biceps", "dumbbell", "reps"),
    _ex("Hammer Curl", "biceps forearms", "dumbbell", "reps"),
    _ex("Preacher Curl", "biceps", "barbell", "reps"),
    _ex("Concentration Curl", "biceps", "dumbbell", "reps"),
    _ex("Tricep Pushdown", "triceps", "cable", "reps"),
    _ex("Skull Crusher", "triceps", "barbell", "reps"),
    _ex("Overhead Tricep Extension", "triceps", "dumbbell", "reps"),
    _ex("Tricep Dip", "triceps chest", "bodyweight", "reps"),

    # ── Core ───────────────────────────────────────────────────────────────
    _ex("Plank", "core", "bodyweight", "duration"),
    _ex("Side Plank", "core", "bodyweight", "duration"),
    _ex("Sit-Up", "core", "bodyweight", "reps"),
    _ex("Crunch", "core", "bodyweight", "reps"),
    _ex("Hanging Leg Raise", "core", "bodyweight", "reps"),
    _ex("Russian Twist", "core", "bodyweight", "reps"),
    _ex("Cable Crunch", "core", "cable", "reps"),
    _ex("Ab Wheel Rollout", "core", "bodyweight", "reps"),
    _ex("Bicycle Crunch", "core", "bodyweight", "reps"),

    # ── Cardio / conditioning ──────────────────────────────────────────────
    _ex("Running", "cardio", "cardio", "distance"),
    _ex("Cycling", "cardio", "cardio", "distance"),
    _ex("Rowing", "cardio back", "cardio", "distance"),
    _ex("Walking", "cardio", "cardio", "distance"),
    _ex("Elliptical", "cardio", "cardio", "distance"),
    _ex("Swimming", "cardio full_body", "cardio", "distance"),
    _ex("Stair Climber", "cardio glutes", "cardio", "duration"),
    _ex("Jump Rope", "cardio calves", "bodyweight", "duration"),
    _ex("Burpee", "full_body cardio", "bodyweight", "reps"),
]


def normalize_name(name: str) -> str:
    """Fold an exercise name for dedup: trim, lowercase, collapse inner spaces.

    Used both to dedupe legacy free-text names during the 0048 backfill and to
    guard against duplicate custom exercises within a household.
    """
    return " ".join((name or "").strip().lower().split())
