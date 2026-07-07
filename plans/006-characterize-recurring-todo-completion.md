# Plan 006: Characterization tests for recurring-todo completion → next-instance spawn

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/domains/todos/service.py`
> If it changed since this plan was written, compare the "Current state" excerpt
> against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (adds tests only; no source change)
- **Depends on**: plans/002-verification-baseline.md (for the `db_session` fixture)
- **Category**: tests
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

Plan 007 will change `update_todo` to make recurring-todo completion atomic and
idempotent (add a row lock and a prior-status gate). Before touching that logic, we
pin the behavior that must **not** regress: completing a recurring todo spawns exactly
one next instance with the correct due date and copied fields, and no instance is
created once the recurrence `end_date` has passed. These characterization tests are the
safety net the 007 refactor is verified against. They also give this critical
task-loop path its first coverage.

## Current state

File: `api/src/life_dashboard/domains/todos/service.py`. The completion → spawn logic
in `update_todo` (lines 194–236):

```python
    for field in data.model_fields_set:
        setattr(todo, field, getattr(data, field))

    # Auto-stamp completed_at when status transitions to/from done
    if "status" in data.model_fields_set and "completed_at" not in data.model_fields_set:
        if data.status == "done":
            todo.completed_at = datetime.now(tz=timezone.utc)
        else:
            todo.completed_at = None

    todo.updated_at = datetime.now(tz=timezone.utc)

    # Auto-spawn the next instance when a recurring todo is completed.
    next_todo: Todo | None = None
    if (
        "status" in data.model_fields_set
        and data.status == "done"
        and todo.recurring
    ):
        rule = todo.recurring
        base = todo.due_date or date.today()
        next_due = _next_due_date(base, rule)
        end_date_str: str | None = rule.get("end_date")
        end_date = date.fromisoformat(end_date_str) if end_date_str else None
        if end_date is None or next_due <= end_date:
            next_todo = Todo(household_id=todo.household_id, ... status="pending",
                             due_date=next_due, recurring=todo.recurring, ...)
            db.add(next_todo)
```

Signatures / call convention:
- `update_todo(db, todo_id, household_id, data: TodoUpdate, actor_id=None) -> TodoResponse | None`
  (router calls it at `todos/router.py:91`).
- `_next_due_date(base: date, rule: dict) -> date` (`todos/service.py:23`, pure).
- The `recurring` JSONB rule shape:
  `{"frequency": "daily"|"weekdays"|"weekly"|"monthly_date"|"monthly_weekday"|"yearly",
    "interval": int, "days_of_week": list[int], "end_date": str|None}`.

**Known bug (do NOT fix here — plan 007 owns it):** there is no gate on the *prior*
status and no row lock, so re-completing an already-done recurring todo spawns a
duplicate. This plan characterizes the *correct* behaviors only; the idempotency
regression test belongs to plan 007.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run these tests | `cd api && .venv/bin/python -m pytest tests/test_todo_recurrence_completion.py -v` | all pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | all pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |

## Scope

**In scope**:
- `api/tests/test_todo_recurrence_completion.py` (create)

**Out of scope**:
- `api/src/life_dashboard/domains/todos/service.py` — no source change in this plan.
- The idempotency/atomicity fix and its regression test — that is plan 007.

## Git workflow

- Branch: `advisor/006-characterize-recurring-todo-completion`
- Commit style: e.g. `test(todos): characterize recurring completion spawn behavior`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the characterization tests

Create `api/tests/test_todo_recurrence_completion.py`, using the `db_session` fixture
from `conftest.py`. First read `todos/schemas.py` for the exact `TodoCreate`/`TodoUpdate`
required fields and the `todos/models.py` `Todo` columns, then adapt the helper below.

```python
from datetime import date

from sqlalchemy import select

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import TodoUpdate
from life_dashboard.domains.todos import service as todos_service


async def _seed_recurring_todo(db, *, rule, due=date(2026, 1, 1)):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    todo = Todo(
        household_id=hh.id,
        title="Water plants",
        status="pending",
        due_date=due,
        recurring=rule,
    )
    db.add(todo)
    await db.flush()
    return hh, todo


async def _count_todos(db, household_id):
    rows = await db.execute(select(Todo).where(Todo.household_id == household_id))
    return list(rows.scalars().all())


async def test_completing_recurring_todo_spawns_exactly_one_next_instance(db_session):
    hh, todo = await _seed_recurring_todo(
        db_session, rule={"frequency": "daily", "interval": 1}, due=date(2026, 1, 1)
    )

    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    todos = await _count_todos(db_session, hh.id)
    assert len(todos) == 2  # the completed one + exactly one new pending instance
    pending = [t for t in todos if t.status == "pending"]
    assert len(pending) == 1
    assert pending[0].due_date == date(2026, 1, 2)  # daily → next day


async def test_no_next_instance_created_past_end_date(db_session):
    hh, todo = await _seed_recurring_todo(
        db_session,
        rule={"frequency": "daily", "interval": 1, "end_date": "2026-01-01"},
        due=date(2026, 1, 1),
    )

    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    todos = await _count_todos(db_session, hh.id)
    assert len(todos) == 1  # next due (Jan 2) is past end_date (Jan 1) → no spawn
    assert todos[0].status == "done"


async def test_spawned_instance_copies_recurring_rule_and_title(db_session):
    rule = {"frequency": "weekly", "interval": 1, "days_of_week": [3]}
    hh, todo = await _seed_recurring_todo(db_session, rule=rule, due=date(2026, 1, 1))

    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    todos = await _count_todos(db_session, hh.id)
    pending = [t for t in todos if t.status == "pending"]
    assert len(pending) == 1
    assert pending[0].title == "Water plants"
    assert pending[0].recurring == rule
```

Adaptation notes:
- If `TodoUpdate(status="done")` fails to construct (e.g. `status` is an enum), pass the
  value the schema expects — read `todos/schemas.py`.
- If `update_todo` commits internally and detaches objects, re-`select` rather than using
  stale references (the `_count_todos` helper already re-selects).
- If the real next-due date differs from the assertions (e.g. weekly snapping), adjust the
  assertion to the **actual** current result and add `# characterizes current behavior`.
  Do NOT change the source.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_todo_recurrence_completion.py -v` → all pass.

### Step 2: Run the full suite

**Verify**: `cd api && .venv/bin/python -m pytest` → all pass; `cd api && .venv/bin/python -m ruff check src tests` → exit 0.

## Test plan

- `test_completing_recurring_todo_spawns_exactly_one_next_instance` — the core contract.
- `test_no_next_instance_created_past_end_date` — the `end_date` cutoff.
- `test_spawned_instance_copies_recurring_rule_and_title` — fields carry over.
- These three must still pass unchanged after plan 007's refactor — that is their purpose.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `cd api && .venv/bin/python -m pytest tests/test_todo_recurrence_completion.py` → 3 passed
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No files under `api/src/` modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `update_todo` spawn block no longer matches the "Current state" excerpt (drift) —
  plan 007 may have already landed; coordinate before writing overlapping tests.
- `db_session` fixture is missing (plan 002 not executed).
- A test cannot be made to pass by adjusting assertions to real behavior — report the
  actual vs. expected values; do not modify `service.py`.

## Maintenance notes

- These tests are plan 007's regression harness. Reviewer of 007 should confirm all
  three still pass after the atomicity change.
- If pagination or a status enum change ever alters `update_todo`, revisit these.
- Follow-up: the idempotent-re-completion test is intentionally deferred to plan 007.
