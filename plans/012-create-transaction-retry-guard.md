# Plan 012: Guard `create_transaction` against double-submit using its own dedup hash

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6ddaa9f..HEAD -- api/src/life_dashboard/domains/budget/service.py`
> Locate code by function name (`create_transaction`, `_compute_dedup_hash`),
> not line number. If the "Current state" excerpt no longer matches, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (adds one pre-insert query; behavior change only within a short retry window)
- **Depends on**: plans/002-verification-baseline.md (merged); pairs with plan 011 but does not depend on it
- **Category**: correctness / financial integrity
- **Planned at**: commit `6ddaa9f`, 2026-07-07
- **Audit ref**: #19

## Why this matters

`create_transaction` (`budget/service.py`, ~line 1911) **computes** a
`dedup_hash` for every manual create (~line 1932) and stores it — but never
*checks* it. A double-tap, network retry, or background refetch re-POSTing the
same manual transaction inserts **two money rows**. `api/CLAUDE.md` →
"Idempotency" names exactly this pattern ("Treat every write endpoint as a
potential retry target").

The subtlety: unlike bank imports, two *legitimately identical* manual
transactions can exist (two same-price coffees on the same day), so a hard
uniqueness rule on `dedup_hash` is wrong. The fix is a **retry-window guard**:
if a transaction with the same `dedup_hash` on the same account was created
within the last few minutes, treat the request as a retry and return the
existing row instead of inserting. Legit duplicates entered deliberately are
almost never entered twice within the window; retries always are.

The long-term path is the Idempotency-Key header infrastructure
(`api/CLAUDE.md` roadmap Priority 2, M effort); this plan is the cheap guard
that closes the live data-corruption hole now without blocking that work.

## Current state

`budget/service.py`, `create_transaction` (~lines 1911–1955):

```python
    dedup_hash = _compute_dedup_hash(data.account_id, data.date, data.amount, data.description)

    txn = BudgetTransaction(
        ...
        dedup_hash=dedup_hash,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    await _maybe_check_thresholds(db, household_id, txn.date)
    return BudgetTransactionResponse.model_validate(txn)
```

No lookup of `dedup_hash` anywhere in this function. `BudgetTransaction` has
`created_at` with `server_default=func.now()` (models.py ~line 390).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_create_transaction_retry_guard.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint (tests) | `cd api && .venv/bin/python -m ruff check tests` | exit 0 |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/budget/service.py` — `create_transaction` only, plus one module-level constant
- `api/tests/test_create_transaction_retry_guard.py` (create)

**Out of scope**:
- `bulk_import_transactions` / Teller sync — plan 011.
- The Idempotency-Key table/middleware (roadmap Priority 2).
- Any schema/migration change.
- The router layer (`budget/router.py`) — the service-level guard covers all callers.

## Git workflow

- Branch: `advisor/012-create-transaction-retry-guard`
- Commit style: `fix(budget): return existing txn on double-submit within retry window`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the retry-window check

Add a module-level constant near `FREE_TIER_MAX_PROFILES`:

```python
# Window within which an identical manual create is treated as a client retry
# (double-tap / network retry) rather than a deliberate duplicate.
CREATE_TXN_RETRY_WINDOW_SECONDS = 120
```

In `create_transaction`, after computing `dedup_hash` and before building the
`BudgetTransaction`, insert:

```python
    # Retry guard: an identical create within the window is a double-submit,
    # not a deliberate duplicate — return the existing row (idempotent).
    window_start = datetime.now(timezone.utc) - timedelta(
        seconds=CREATE_TXN_RETRY_WINDOW_SECONDS
    )
    recent_stmt = select(BudgetTransaction).where(
        BudgetTransaction.account_id == data.account_id,
        BudgetTransaction.dedup_hash == dedup_hash,
        BudgetTransaction.created_at >= window_start,
        BudgetTransaction.archived_at.is_(None),
    ).limit(1)
    existing = (await db.execute(recent_stmt)).scalar_one_or_none()
    if existing is not None:
        return BudgetTransactionResponse.model_validate(existing)
```

`timedelta` — check the existing datetime imports at the top of the file and
extend them if needed. Note `created_at` is timezone-aware
(`DateTime(timezone=True)`); compare against an aware `datetime` as shown.
Under SQLite in tests, aware-vs-naive comparison quirks are possible — if the
test from Step 2 fails on the comparison, mirror how `service.py` ~line 3147
(`BudgetTransaction.created_at > account.balance_synced_at`) handles it.

**Verify**: `grep -n "CREATE_TXN_RETRY_WINDOW_SECONDS" api/src/life_dashboard/domains/budget/service.py` → 2 matches (definition + use).

### Step 2: Tests

Create `api/tests/test_create_transaction_retry_guard.py` (fixture pattern:
household → profile → account, as in `api/tests/test_auto_budget.py`):

1. `test_double_submit_returns_existing_row` — call `create_transaction`
   twice with the identical `BudgetTransactionCreate`; assert both responses
   have the **same `id`** and only one `BudgetTransaction` row exists.
2. `test_distinct_transactions_both_insert` — two creates differing in
   amount (or description); assert two rows.
3. `test_old_identical_transaction_does_not_block` — seed a txn with the
   same dedup fields but `created_at` older than the window (insert directly
   with an explicit `created_at`), then call `create_transaction`; assert a
   **new** row is created (2 rows total).

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_create_transaction_retry_guard.py -v` → 3 passed.

## Test plan

Covered by Step 2: retry collapses to one row; legit distinct creates
unaffected; the window actually expires (deliberate later duplicates still
work).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "CREATE_TXN_RETRY_WINDOW_SECONDS" api/src/life_dashboard/domains/budget/service.py` → 2 matches
- [ ] `cd api && .venv/bin/python -m pytest tests/test_create_transaction_retry_guard.py` → 3 passed
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check tests` → exit 0; `ruff check src` error count not increased vs. `main`
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `create_transaction` no longer matches the "Current state" excerpt (drift).
- The `created_at` timezone comparison cannot be made to pass on SQLite
  without changing behavior on Postgres — report the discrepancy.
- You are tempted to instead add a unique constraint on `dedup_hash` — do not;
  that is explicitly rejected (legit same-day duplicates exist).
- The full suite fails for reasons unrelated to your diff.

## Maintenance notes

- When the Idempotency-Key infrastructure (roadmap Priority 2) lands, this
  window guard can remain as defense-in-depth for keyless clients — they
  compose; no need to remove it.
- The 120 s window is a judgment call; it only needs to exceed realistic
  client retry horizons. Adjust the constant, not the logic.
- Reviewer: confirm the guard runs *before* scope resolution has side effects
  (it has none today — the guard placement after account lookup is fine and
  keeps the 404-on-bad-account behavior unchanged).
