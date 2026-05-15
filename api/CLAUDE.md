# CLAUDE.md — api/

FastAPI backend for Hearth. See the root `CLAUDE.md` for product vision and cross-cutting principles.

---

## Stack

- **Python 3.12** with `pyproject.toml` (no `requirements.txt`)
- **FastAPI** — async routes, dependency injection via `Depends`
- **SQLAlchemy 2.x** (async) — `AsyncSession`, `select()` style queries
- **Alembic** — migrations in `../migrations/`
- **Pydantic v2** — request/response schemas, settings via `pydantic-settings`
- **Postgres** — primary datastore; JSONB used for flexible content fields
- **Uvicorn** — ASGI server

---

## Project layout

```
src/life_dashboard/
  main.py               App factory, router registration, CORS, lifespan
  core/
    database.py         Async engine, session factory, get_db dependency
    settings.py         Pydantic Settings — reads from .env
  auth/                 JWT auth: tokens, hashing, session management
  domains/
    documents/          Long-form writing pages (BlockNote JSON + markdown + icon)
    todos/              Tasks with due dates, recurrence, and household assignment
    habits/             Recurring habit tracking with streaks and completion rates
    goals/              Goal definitions and progress
    recipes/            Recipe storage with ingredient/step JSONB
    grocery_lists/      Shopping lists, linked to recipes
    workouts/           Workout logs and exercise entries
    contacts/           Household contacts/address book
    calendar_events/    Events and scheduling
    tags/               Cross-domain tagging
```

Each domain follows the same four-file pattern:
- `models.py` — SQLAlchemy ORM model(s)
- `schemas.py` — Pydantic request/response schemas
- `service.py` — all business logic; functions receive `AsyncSession` + domain args
- `router.py` — thin FastAPI routes; calls service functions, handles HTTP concerns only

---

## Conventions

**Routing prefix:** each domain router is mounted at `/domain-name` in `main.py`. All routes are relative to that prefix.

**Auth dependency:** use `current_user = Depends(get_current_user)` in routes that require auth. The dependency attaches three extra Python attributes at runtime (not ORM columns): `current_user.household_id`, `current_user.household_name`, and `current_user.role` (string value of `MembershipRole`, e.g. `"owner"`, `"admin"`, `"member"`, `"viewer"`). These are also populated during login/register and returned in `UserResponse`. Always read `user.role` from the membership join — do not add a `role` column to the `users` table.

**Household scoping:** every data query must filter by `household_id`. Never return data across household boundaries. Enforced in service functions, not routers.

**Partial updates:** `Update` schemas use `model_fields_set` to only update fields that were actually sent:
```python
for field in data.model_fields_set:
    setattr(obj, field, getattr(data, field))
```

**Response schemas:** use `model_config = ConfigDict(from_attributes=True)` for ORM mapping. Separate `Create`, `Update`, and `Response` schemas per domain.

**Soft deletes:** use `archived_at: datetime | None` rather than hard deletes where data should be recoverable.

**No bare `except`:** catch specific exceptions; let unexpected errors bubble to FastAPI's default 500 handler.

**Datetime timezone normalization:** SQLAlchemy/psycopg2 can return timezone-naive `datetime` objects from `TIMESTAMP WITH TIME ZONE` columns in some environments. When comparing a DB timestamp against `datetime.now(timezone.utc)` (which is timezone-aware), use the `_as_aware()` helper from `auth/service.py`:
```python
def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
```
Apply this pattern anywhere you compare a DB datetime to an aware datetime to avoid `TypeError: can't compare offset-naive and offset-aware datetimes`.

---

## JSONB fields

JSONB columns store flexible structured data without requiring migrations for sub-field changes. Typed as `dict[str, Any] | None` (SQLAlchemy `JSON` column type) in models, and as `dict[str, Any] | None` in Pydantic schemas.

**Read defensively:** always use `.get()` or `or {}` when reading JSONB sub-fields — the stored data may predate a new sub-field:
```python
cadence = habit.cadence or {}
days_of_week = cadence.get("days_of_week") or []
```

**Existing JSONB fields:**
- `documents.editor_json` — BlockNote block tree
- `documents.source_markdown` — original import markdown
- `todos.recurring` — recurrence rule (see Todos section below)
- `habits.cadence` — scheduling sub-fields (see Habits section below)
- `recipes.ingredients`, `recipes.steps` — structured recipe data

---

## Habits domain

### Models and schemas
`HabitWithStats` extends `HabitResponse` with computed fields that are not stored in the DB:
```python
class HabitWithStats(HabitResponse):
    current_streak: int = 0
    completion_rate_7d: float | None = None
    completion_rate_30d: float | None = None
```
`None` rates mean the habit is newer than the measurement window — the frontend displays `—`.

### Cadence JSONB sub-fields
- `days_of_week: list[int] | None` — Python weekday values (Mon=0…Sun=6), sorted ascending
- `times_per_period: int | None` — for weekly/monthly without specific days
- `start_date: str | None` — ISO date; monthly habits repeat on this day-of-month
- `link: dict | None` — optional page link; shape `{"path": "/workouts", "label": "Workouts"}`; stored as-is, no validation needed

### Preventing N+1 queries
`list_habits` batch-loads all completed occurrences for all returned habits in a single query, then groups them in Python:
```python
occ_result = await db.execute(
    select(HabitOccurrence.habit_id, HabitOccurrence.scheduled_date)
    .where(HabitOccurrence.habit_id.in_(habit_ids), ...)
)
occs_by_habit: dict[uuid.UUID, set[date]] = {}
for habit_id, sched_date in occ_result.all():
    occs_by_habit.setdefault(habit_id, set()).add(sched_date)
```
Do not query occurrences per-habit inside a loop.

### Streak calculation (`_compute_streak`)
- If `days_of_week` is set: counts consecutive *scheduled* days only; today gets a grace period if not yet completed
- `daily`: consecutive calendar days backwards from today
- `weekly`: consecutive weeks with ≥1 completion; grace period for current week
- `monthly`: consecutive months with ≥1 completion; grace period for current month
- Lookback capped at 90 days for the list endpoint (365 for the DOW streak branch)

### Completion rate (`_expected_in_period`)
Returns expected completions in a window of N days. Returns `0.0` (displayed as `None` rate) if the habit is newer than the window. If `days_of_week` is set, counts exactly how many matching weekdays fall in the active window. Respects `cadence.start_date` as the habit's effective start.

### Frequency options
Supported values: `daily`, `weekly`, `monthly`. `custom` was removed — it had no implementation and silently fell back to daily. Do not add it back without building real parsing logic.

---

## Recipes domain

### Tag filtering
`GET /recipes` accepts `tag_ids: list[uuid.UUID] = Query(default=[])` (repeating param: `?tag_ids=uuid1&tag_ids=uuid2`). The service joins `Tagging` with OR logic (`Tagging.tag_id.in_(tag_ids)`) and applies `.distinct()` to prevent duplicate rows when a recipe has multiple matching tags.

### Tagging pattern (cross-domain)
Tags are stored in the `tags` table (household-scoped). Associations live in `taggings` (junction table with `tag_id`, `entity_type`, `entity_id`). The recipe service uses `_ENTITY_TYPE = "recipe"`. When adding tag-filtering to another domain, follow the same join pattern:

```python
if tag_ids:
    query = (
        query
        .join(Tagging, (Tagging.entity_id == Model.id) & (Tagging.entity_type == ENTITY_TYPE))
        .where(Tagging.tag_id.in_(tag_ids))
        .distinct()
    )
```

---

## Todos domain

### Recurrence
When a todo marked done has a `recurring` JSONB field, `update_todo` in `service.py` computes the next due date and creates a new pending todo with the same fields. The recurrence rule shape:
```python
{
    "frequency": "daily" | "weekdays" | "weekly" | "monthly_date" | "monthly_weekday" | "yearly",
    "interval": int,          # e.g. 2 = every 2 weeks
    "days_of_week": list[int],  # for weekly frequency
    "end_date": str | None,   # ISO date or null
}
```

`_next_due_date(base, rule)` in `service.py` handles all six frequency types including edge cases (May 31 → June 30, Feb 29 → Mar 1, biweekly weekday snap). The next instance is not created if `end_date` is set and the computed next date would exceed it.

No migration was needed — the `recurring JSONB` column already existed on the `Todo` model.

---

## Households router

`life_dashboard/households/router.py` — mounted at `/households`. Handles household administration:

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/households/members` | any member | List all active members in the current household |
| `PATCH` | `/households/name` | admin/owner | Rename the household |
| `POST` | `/households/members` | admin/owner | Add a member: creates a `User` with `hash_password("password")` if the email is new, then adds a `HouseholdMembership`. Allowed roles: `admin`, `member`, `viewer`. Returns 409 if already a member. |
| `POST` | `/households/dev/impersonate/{target_user_id}` | admin/owner | **Dev only** — returns an access token for another member of the same household. Raises 403 in non-development environments (`settings.environment != "development"`). |
| `GET` | `/households/permissions` | any member | Return the household's permission config (defaults filled in) |
| `PUT` | `/households/permissions` | admin/owner | Update the household's permission config |

The `_ADMIN_ROLES` set (`{MembershipRole.owner, MembershipRole.admin}`) is the single source of truth for admin-gating in this router — use it for any new admin-only endpoints here.

---

## Running locally

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn life_dashboard.main:app --reload --port 1339
```

Or from the repo root: `make api` (runs on port 1339).

Requires a Postgres instance. Copy `.env.example` to `.env` and set `DATABASE_URL`.

**Port split:** the always-on launchd service runs on **1338**; local dev (`make api`) runs on **1339** so both can run simultaneously. `web/.env.local` is already set to `http://localhost:1339` for dev.

---

## Migrations

```bash
cd api
alembic upgrade head                                    # apply pending
alembic revision --autogenerate -m "description"        # generate new
```

Migration files live in `migrations/versions/`. Always review autogenerated migrations before applying — SQLAlchemy doesn't always detect renames or JSONB type changes correctly.

---

## Deployment (NAS / Docker)

```bash
cd /volume1/docker/life-dashboard/infra
sudo docker compose build api && sudo docker compose up -d
```
