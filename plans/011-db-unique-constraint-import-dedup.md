# Plan 011: Enforce import dedup at the DB with a unique index on (account_id, external_id)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 6ddaa9f..HEAD -- api/src/life_dashboard/domains/budget/service.py api/src/life_dashboard/domains/budget/models.py api/migrations/versions/`
> Locate code by function name (`bulk_import_transactions`), not line number.
> If the "Current state" excerpts no longer match, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (adds a migration; a live DB containing pre-existing duplicates will fail the migration — by design, see Step 2)
- **Depends on**: plans/002-verification-baseline.md (merged; `db_session` fixture)
- **Category**: correctness / financial integrity
- **Planned at**: commit `6ddaa9f`, 2026-07-07
- **Audit ref**: #13

## Why this matters

Import dedup today is **application-level only**: `bulk_import_transactions`
(`budget/service.py`, ~line 2330) loads existing `external_id` / `dedup_hash`
values into Python sets, then skips matches. Two overlapping syncs (double-tap
on "Sync", a background refetch racing a manual sync, two workers) both read
the same "existing" snapshot, both see the new transaction as absent, and both
insert it — **duplicate financial rows** that silently corrupt balances,
budgets, and analytics. This is exactly the class of bug the idempotency
roadmap (`api/CLAUDE.md` → "Idempotency") says to guard with DB constraints.

`external_id` is the bank's own transaction ID (Teller/OFX FITID) and is
genuinely unique per account when present. It is the right column for a hard
constraint. `dedup_hash` is deliberately **not** constrained: two legitimate
same-day identical transactions (two same-price coffees) share a hash, and a
unique index would reject the second one outright (a known caveat, README
"Findings not yet planned" — lower items).

## Current state

- `budget/models.py` `BudgetTransaction` (~line 328): **no `__table_args__`**,
  no unique constraints or indexes beyond the PK.
- `external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)` (~line 372)
- `bulk_import_transactions` dedups via in-memory sets (~lines 2344–2367),
  single `await db.commit()` at the end (~line 2398).
- Latest migration: `api/migrations/versions/0041_budget_account_balance_anchor.py`
  (`revision = "0041"`). Next slot: `0042`.
- Tests create schema via `Base.metadata.create_all` (see `api/tests/conftest.py`),
  so the index must be declared **on the model** to exist in tests, not only in
  the migration.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_import_dedup_constraint.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint (tests) | `cd api && .venv/bin/python -m ruff check tests` | exit 0 |
| Apply migration (operator, live DB) | `cd api && alembic upgrade head` | no error |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/budget/models.py` — add `__table_args__` with the partial unique index
- `api/migrations/versions/0042_transaction_external_id_unique.py` (create)
- `api/src/life_dashboard/domains/budget/service.py` — `IntegrityError` handling in `bulk_import_transactions` only
- `api/tests/test_import_dedup_constraint.py` (create)

**Out of scope**:
- `create_transaction` double-submit guard — that is plan 012.
- Any constraint on `dedup_hash` (see "Why this matters").
- The Idempotency-Key infrastructure (roadmap Priority 2).

## Git workflow

- Branch: `advisor/011-db-unique-import-dedup`
- Commit style: `fix(budget): enforce per-account external_id uniqueness at the DB`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Declare the partial unique index on the model

In `budget/models.py`, on `BudgetTransaction`, add:

```python
    __table_args__ = (
        Index(
            "uq_budget_txn_account_external_id",
            "account_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
            sqlite_where=text("external_id IS NOT NULL"),
        ),
    )
```

Import `Index` and `text` from `sqlalchemy` (check existing imports first).
The partial (`WHERE external_id IS NOT NULL`) form is required: most manual/CSV
rows have NULL `external_id`, and while both Postgres and SQLite treat NULLs as
distinct in unique indexes, the partial index is smaller and states the intent.
Both dialects support partial indexes; both `*_where` kwargs are needed because
tests run SQLite and prod runs Postgres.

**Verify**: `grep -n "uq_budget_txn_account_external_id" api/src/life_dashboard/domains/budget/models.py` → 1 match.

### Step 2: Write migration 0042

Create `api/migrations/versions/0042_transaction_external_id_unique.py`
(`revision = "0042"`, `down_revision = "0041"`; copy the header shape of 0041).

The migration must **check for pre-existing duplicates first** and fail loudly
with a diagnostic if any exist — deleting money rows is an operator decision,
not a migration side-effect:

```python
def upgrade() -> None:
    conn = op.get_bind()
    dupes = conn.execute(sa.text(
        """
        SELECT account_id, external_id, COUNT(*) AS n
        FROM budget_transactions
        WHERE external_id IS NOT NULL
        GROUP BY account_id, external_id
        HAVING COUNT(*) > 1
        """
    )).fetchall()
    if dupes:
        raise RuntimeError(
            f"Cannot add unique index: {len(dupes)} duplicated "
            "(account_id, external_id) pairs exist in budget_transactions. "
            "Resolve manually (keep one row per pair, delete/merge the rest), "
            "then re-run. Pairs: "
            + ", ".join(f"({r.account_id}, {r.external_id}) x{r.n}" for r in dupes[:20])
        )
    op.create_index(
        "uq_budget_txn_account_external_id",
        "budget_transactions",
        ["account_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
        sqlite_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_budget_txn_account_external_id", table_name="budget_transactions")
```

**Verify**: `cd api && .venv/bin/python -c "import importlib.util as u; s=u.spec_from_file_location('m','migrations/versions/0042_transaction_external_id_unique.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.revision, m.down_revision)"` → `0042 0041`.

### Step 3: Handle the race in `bulk_import_transactions`

The in-memory skip logic stays (it avoids pointless inserts); the constraint is
the backstop for the race. Change the single end-commit so a constraint hit on
one row doesn't abort the whole batch: flush each insert inside a SAVEPOINT and
convert `IntegrityError` to a skip:

```python
from sqlalchemy.exc import IntegrityError  # top of file, if not present

        # inside the for-loop, replacing the bare `db.add(txn)`:
        try:
            async with db.begin_nested():
                db.add(txn)
                await db.flush()
        except IntegrityError:
            skipped += 1
            continue
```

Keep the final `await db.commit()`. The counters (`inserted`, and the
set-maintenance lines) must only run after a successful flush — move them
inside/after the `try` accordingly.

**Verify**: `grep -n "begin_nested" api/src/life_dashboard/domains/budget/service.py` → ≥ 1 match inside `bulk_import_transactions`.

### Step 4: Tests

Create `api/tests/test_import_dedup_constraint.py` with (at minimum):

1. `test_duplicate_external_id_rejected_by_db` — insert two
   `BudgetTransaction` rows with the same `(account_id, external_id)` directly
   via the session (bypassing the service-level set check) and assert the
   second `flush()` raises `IntegrityError`. This proves the index exists in
   the test schema (i.e. Step 1's model declaration works).
2. `test_bulk_import_skips_constraint_conflict` — seed one txn with
   `external_id="t1"`, then call `bulk_import_transactions` with a batch
   containing `external_id="t1"` and a fresh `external_id="t2"`; assert
   `inserted == 1, skipped == 1` and the t2 row exists.
3. `test_null_external_id_not_constrained` — two manual rows with
   `external_id=None`, same account: both insert fine.

Seed fixtures following the pattern in `api/tests/test_auto_budget.py`
(household → profile → account → transactions). Read `budget/models.py` for
required columns — do not guess.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_import_dedup_constraint.py -v` → 3 passed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "uq_budget_txn_account_external_id" api/src/life_dashboard/domains/budget/models.py` → 1 match
- [ ] Migration `0042` exists with `down_revision = "0041"` and the duplicate pre-check
- [ ] `grep -n "begin_nested" api/src/life_dashboard/domains/budget/service.py` → match in `bulk_import_transactions`
- [ ] `cd api && .venv/bin/python -m pytest tests/test_import_dedup_constraint.py` → 3 passed
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check tests` → exit 0; `ruff check src` error count not increased vs. `main`
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `BudgetTransaction` already has a `__table_args__` (drift — merge carefully or report).
- A migration numbered `0042` already exists (renumber only after confirming the chain head).
- `begin_nested()` misbehaves under `aiosqlite` in tests (savepoint support
  issues) — report; a fallback (pre-flush existence re-check) needs maintainer
  sign-off, do not silently switch strategies.
- The full suite fails for reasons unrelated to your diff.
- You find real duplicated `(account_id, external_id)` pairs in any committed
  fixture/db file — report, do not delete.

## Maintenance notes

- Operator must run `alembic upgrade head` on the live DB(s); if the migration
  raises the duplicate error, resolving those rows is an operator task.
- `dedup_hash` remains app-level-only by design; revisit if the same-day
  false-positive caveat (README lower items) is ever redesigned.
- This closes the DB half of idempotency-roadmap coverage for Teller/bulk
  import; plan 012 covers the manual-create path.
