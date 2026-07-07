# Plan 013: Roll back the session when `_maybe_check_thresholds` swallows an exception

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6ddaa9f..HEAD -- api/src/life_dashboard/domains/budget/service.py`
> Locate code by function name (`_maybe_check_thresholds`), not line number.
> If the "Current state" excerpt no longer matches, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (error-path-only change; happy path untouched)
- **Depends on**: plans/002-verification-baseline.md (merged)
- **Category**: correctness
- **Planned at**: commit `6ddaa9f`, 2026-07-07
- **Audit ref**: #15

## Why this matters

`_maybe_check_thresholds` (`budget/service.py`, ~line 1888) intentionally
swallows exceptions so a notification failure never blocks the primary write —
correct policy. But the `except` block only logs; it does **not roll back**.
If `check_budget_thresholds` raises mid-work (after issuing SQL), the session
is left in a failed/dirty state. Every caller uses the session *as if it were
clean* afterward — `create_transaction` returns normally, and in
`update_transaction` / `bulk_import_transactions` the same session may be
reused by the request scope. Subsequent operations on a failed session raise
`PendingRollbackError` or, worse, silently carry uncommitted threshold-side
writes into the next commit. One `await db.rollback()` in the except restores
the invariant "this helper never affects the caller's session state."

The primary write is safe either way — all callers `commit()` **before**
calling this helper — so the rollback discards only partial threshold work.

## Current state

`budget/service.py` (~lines 1888–1908):

```python
async def _maybe_check_thresholds(
    db: AsyncSession,
    household_id: uuid.UUID,
    txn_date: date_type | None,
) -> None:
    ...
    try:
        await check_budget_thresholds(db, household_id)
        await db.commit()
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Budget threshold check failed for household %s: %s", household_id, exc
        )
```

Callers (all commit first): `create_transaction` (~1954), `update_transaction`
(~1979), `bulk_import_transactions` (~2408). `check_budget_thresholds` is at
~line 3253.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_threshold_check_rollback.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint (tests) | `cd api && .venv/bin/python -m ruff check tests` | exit 0 |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/budget/service.py` — the `except` block of `_maybe_check_thresholds` only
- `api/tests/test_threshold_check_rollback.py` (create)

**Out of scope**:
- `check_budget_thresholds` itself (its internal logic is unchanged).
- The module-level-vs-local `import logging` style oddity — leave it (or hoist
  it only if ruff already flags it; do not expand scope otherwise).
- Notification dedup (roadmap Priority 3).

## Git workflow

- Branch: `advisor/013-threshold-check-rollback`
- Commit style: `fix(budget): roll back session when threshold check fails`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the rollback

In the `except` block, before logging:

```python
    except Exception as exc:
        await db.rollback()
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Budget threshold check failed for household %s: %s", household_id, exc
        )
```

`rollback()` order (before vs. after the log line) doesn't matter functionally;
put it first so the session is restored even if logging itself misbehaves.

**Verify**: `grep -n -A3 "Budget threshold check failed" api/src/life_dashboard/domains/budget/service.py` shows `await db.rollback()` inside the same `except`.

### Step 2: Test that the session survives a threshold failure

Create `api/tests/test_threshold_check_rollback.py`. Force
`check_budget_thresholds` to raise via monkeypatch and assert the session is
usable afterward:

1. `test_threshold_failure_leaves_session_usable` — seed a household (pattern
   from `api/tests/test_auto_budget.py`); monkeypatch
   `budget_service.check_budget_thresholds` with an async function that first
   executes some SQL on the session (e.g. `await db.execute(select(1))`) and
   then raises `RuntimeError("boom")`; call
   `await budget_service._maybe_check_thresholds(db_session, hh.id, date.today())`
   — it must **not** raise; then prove the session still works:
   `await db_session.execute(select(BudgetTransaction))` and a
   `db_session.add(...)` + `await db_session.commit()` of a fresh row succeed.
2. `test_threshold_success_commits` — monkeypatch with a no-op async function;
   call the helper with today's date; no exception, session usable. (Guards
   against a regression where the rollback lands on the happy path.)

Note: the helper early-returns unless `txn_date` is in the **current month** —
use `date.today()` in both tests or the monkeypatched function is never called.
Assert it *was* called (e.g. set a flag in the patched function).

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_threshold_check_rollback.py -v` → 2 passed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `await db.rollback()` present in `_maybe_check_thresholds`'s `except` block
- [ ] `cd api && .venv/bin/python -m pytest tests/test_threshold_check_rollback.py` → 2 passed
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check tests` → exit 0; `ruff check src` error count not increased vs. `main`
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_maybe_check_thresholds` no longer matches the excerpt (drift).
- The monkeypatch cannot reach the symbol the helper actually calls (it calls
  the module-local name `check_budget_thresholds` — patch it on the
  `budget.service` module, not where it's defined elsewhere; if that still
  doesn't intercept, report).
- The full suite fails for reasons unrelated to your diff.

## Maintenance notes

- If a future refactor makes callers share the helper's transaction (i.e. call
  it *before* their own commit), this rollback would discard the primary write
  — the "callers commit first" invariant must hold. Reviewer: confirm all
  three call sites still commit before calling the helper.
- Sibling audit finding #16 (`auto_categorize_transactions` unbounded load)
  lives in the same post-sync path and is still unplanned.
