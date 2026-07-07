# Plan 007: Make recurring-todo completion atomic and idempotent

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
- **Risk**: LOW (adds a guard + a row lock; the characterization tests from plan 006 protect existing behavior)
- **Depends on**: plans/006-characterize-recurring-todo-completion.md (its tests must exist and pass first); transitively plans/002
- **Category**: bug
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

`update_todo` spawns the next recurrence instance whenever an incoming PATCH sets
`status == "done"` and the todo is recurring — with **no check that the todo wasn't
already done** and **no row lock**. Two consequences, both create duplicate future
todos on the app's core task loop:

1. **Idempotency**: re-PATCHing an already-completed recurring todo with `status="done"`
   (a mobile double-tap, a retried request, a background refetch that re-submits) spawns
   another pending copy every time.
2. **Concurrency**: two simultaneous "complete" requests both read `status != "done"` and
   both spawn — duplicate instances.

`api/CLAUDE.md` calls this out explicitly as "Priority 1" idempotency work and
`.claude/rules/core-invariants.md#3` requires state transitions that trigger side-effects
to be atomic (check-and-create in one transaction, using `SELECT … FOR UPDATE` or
`UPDATE … WHERE … RETURNING`). This plan implements the guard + lock.

## Current state

File: `api/src/life_dashboard/domains/todos/service.py`, `update_todo` (lines 184–236):

```python
async def update_todo(db, todo_id, household_id, data, actor_id=None):
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.household_id == household_id)
    )
    todo = result.scalar_one_or_none()
    if todo is None:
        return None

    prev_assignee = todo.assigned_to_user_id

    for field in data.model_fields_set:
        setattr(todo, field, getattr(data, field))

    if "status" in data.model_fields_set and "completed_at" not in data.model_fields_set:
        if data.status == "done":
            todo.completed_at = datetime.now(tz=timezone.utc)
        else:
            todo.completed_at = None

    todo.updated_at = datetime.now(tz=timezone.utc)

    next_todo: Todo | None = None
    if (
        "status" in data.model_fields_set
        and data.status == "done"
        and todo.recurring
    ):
        rule = todo.recurring
        base = todo.due_date or date.today()
        next_due = _next_due_date(base, rule)
        end_date_str = rule.get("end_date")
        end_date = date.fromisoformat(end_date_str) if end_date_str else None
        if end_date is None or next_due <= end_date:
            next_todo = Todo(household_id=todo.household_id, ... status="pending", ...)
            db.add(next_todo)
    # ... notification dispatch, commit, return ...
```

The bug: the spawn condition looks at the incoming `data.status`, never at the todo's
**prior** status. There is no `with_for_update()` on the select.

Notes:
- `with_for_update()` is a Postgres row lock. On SQLite (the test backend) SQLAlchemy
  silently ignores it, so the concurrency case can't be unit-tested on SQLite — but the
  **prior-status gate** fully fixes the idempotency (double-submit) case and *is*
  testable on SQLite. Both changes ship together; the gate is what the test verifies.
- Plan 006 wrote characterization tests that must keep passing (single spawn, end_date
  cutoff, field copy).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Plan 006 tests still green | `cd api && .venv/bin/python -m pytest tests/test_todo_recurrence_completion.py -v` | all pass |
| New idempotency test | `cd api && .venv/bin/python -m pytest tests/test_todo_completion_idempotency.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | all pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/todos/service.py` (edit `update_todo`)
- `api/tests/test_todo_completion_idempotency.py` (create)

**Out of scope**:
- `_next_due_date` and the next-instance field-copy logic — unchanged.
- The habit-occurrence completion path (`habits/service.py`) — the audit confirmed it does
  NOT spawn a next occurrence, so it carries no duplicate risk; do not touch it here.
- The broader `Idempotency-Key` header system (Priority 2 in `api/CLAUDE.md`) — separate,
  larger work; not this plan.

## Git workflow

- Branch: `advisor/007-atomic-recurring-todo-completion`
- Commit style: e.g. `fix(todos): make recurring completion atomic and idempotent`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Lock the row and capture the prior status

Change the initial select to lock the row, and record the prior status **before** the
`setattr` loop overwrites it:

```python
    result = await db.execute(
        select(Todo)
        .where(Todo.id == todo_id, Todo.household_id == household_id)
        .with_for_update()
    )
    todo = result.scalar_one_or_none()
    if todo is None:
        return None

    prev_status = todo.status          # capture BEFORE applying the update
    prev_assignee = todo.assigned_to_user_id

    for field in data.model_fields_set:
        setattr(todo, field, getattr(data, field))
```

### Step 2: Gate the spawn on an actual pending → done transition

Change the spawn condition so it only fires when the todo was **not already done**:

```python
    next_todo: Todo | None = None
    if (
        "status" in data.model_fields_set
        and data.status == "done"
        and prev_status != "done"          # ← only on a real transition into done
        and todo.recurring
    ):
        ...  # unchanged spawn body
```

This is the whole behavioral fix: a repeated `status="done"` PATCH on an
already-completed recurring todo now no-ops the spawn. Combined with the
`with_for_update()` lock from Step 1, two concurrent completers serialize and only the
first (which sees `prev_status != "done"`) spawns.

**Verify**: `grep -n "prev_status != \"done\"" api/src/life_dashboard/domains/todos/service.py` → one match; `grep -n "with_for_update()" api/src/life_dashboard/domains/todos/service.py` → one match.

### Step 3: Add the idempotency regression test

Create `api/tests/test_todo_completion_idempotency.py` (reuse the seed helper shape from
plan 006):

```python
from datetime import date

from sqlalchemy import select

from life_dashboard.auth.models import Household
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import TodoUpdate
from life_dashboard.domains.todos import service as todos_service


async def _seed(db, rule):
    hh = Household(name="H")
    db.add(hh); await db.flush()
    todo = Todo(household_id=hh.id, title="T", status="pending",
                due_date=date(2026, 1, 1), recurring=rule)
    db.add(todo); await db.flush()
    return hh, todo


async def test_recompleting_done_recurring_todo_does_not_spawn_again(db_session):
    hh, todo = await _seed(db_session, {"frequency": "daily", "interval": 1})

    # First completion → spawns one next instance (total 2).
    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))
    # Second identical completion (double-tap / retry) → must NOT spawn a third.
    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    rows = await db_session.execute(select(Todo).where(Todo.household_id == hh.id))
    todos = list(rows.scalars().all())
    assert len(todos) == 2  # completed original + exactly one pending — NOT 3
```

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_todo_completion_idempotency.py -v` → pass. (This test would fail against the pre-fix code — it is the regression guard.)

### Step 4: Confirm plan 006's characterization tests still pass

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_todo_recurrence_completion.py tests/test_todo_completion_idempotency.py -v` → all pass. Then full suite: `cd api && .venv/bin/python -m pytest` → all pass.

## Test plan

- New: `test_recompleting_done_recurring_todo_does_not_spawn_again` — the double-submit
  idempotency guard.
- Preserved: all three plan-006 characterization tests (single spawn, end_date cutoff,
  field copy) must remain green — they prove the fix didn't change correct behavior.
- The concurrency (two-simultaneous-requests) case is not unit-testable on SQLite; the
  `with_for_update()` lock is verified by code review, not a test. Note this in your report.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'prev_status != "done"' api/src/life_dashboard/domains/todos/service.py` → one match
- [ ] `grep -n "with_for_update()" api/src/life_dashboard/domains/todos/service.py` → one match
- [ ] `cd api && .venv/bin/python -m pytest tests/test_todo_completion_idempotency.py` → pass
- [ ] `cd api && .venv/bin/python -m pytest tests/test_todo_recurrence_completion.py` → all pass (unchanged)
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `update_todo` body no longer matches "Current state" (drift) — reconcile before editing.
- `todo.status` uses an enum whose "done" value is not the string `"done"` — read the model/schema
  and use the correct comparison value; report what it is.
- Plan 006's characterization tests do not exist or are failing before you start — this plan
  depends on them as the safety net.
- Adding `with_for_update()` raises on the SQLite test backend (it should be silently ignored;
  if SQLAlchemy errors, report the version and message).

## Maintenance notes

- The same atomic pattern (lock + prior-state gate) is the template for the habit-occurrence
  completion path *if* it ever starts spawning next occurrences, and for the financial-create
  idempotency work (findings #13/#19 in the audit) — see `api/CLAUDE.md` Priority 1/2.
- Reviewer should confirm the prior-status capture happens **before** the `setattr` loop (a
  common mistake is reading `todo.status` after it's been overwritten).
- Follow-up deferred: the app-wide `Idempotency-Key` header/table (Priority 2) and notification
  dedup (Priority 3) remain unbuilt — tracked under the DIR-01 idempotency direction finding.
