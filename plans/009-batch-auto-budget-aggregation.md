# Plan 009: Collapse the auto-budget per-category N+1 into one grouped query per period

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/domains/budget/service.py`
> `budget/service.py` is large and actively changing — line numbers may shift. Locate the
> code by the `auto_budget_fixed_categories` function name and the `for yr, mo in periods:`
> loop, not by absolute line number. If the excerpt below no longer matches, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (produces identical per-category monthly sums with fewer queries)
- **Depends on**: plans/002-verification-baseline.md (for the `db_session` fixture)
- **Category**: perf
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

`auto_budget_fixed_categories` computes each category's average monthly spend over a
window by looping **periods × categories** and issuing one aggregate query per
(period, category) pair. For a typical 6-month window and 30 categories that is 180
sequential DB round-trips for a single "auto-budget" action — latency scales with
category count × window. This violates `.claude/rules/performance.md` ("Never query
inside a loop... batch-load in one query and group in Python"). The fix collapses the
inner per-category loop into **one grouped query per period**, cutting round-trips from
`periods × categories` to `periods` (e.g. 180 → 6) while producing identical results.

## Current state

File: `api/src/life_dashboard/domains/budget/service.py`, inside
`auto_budget_fixed_categories`. The N+1 (currently around lines 1055–1080):

```python
    categories = cat_result.scalars().all()
    if not categories:
        return []

    # Accumulate monthly expense totals per category
    period_totals: dict[uuid.UUID, list[float]] = {cat.id: [] for cat in categories}

    for yr, mo in periods:
        _, last_day = _cal.monthrange(yr, mo)
        from datetime import date as _d2
        date_from = _d2(yr, mo, 1)
        date_to   = _d2(yr, mo, last_day)

        for cat in categories:                                    # ← inner N+1
            stmt = select(func.sum(BudgetTransaction.amount)).where(
                BudgetTransaction.household_id == household_id,
                BudgetTransaction.category_id == cat.id,
                BudgetTransaction.date >= date_from,
                BudgetTransaction.date <= date_to,
                BudgetTransaction.amount < 0,          # expenses only (negative = spend)
                BudgetTransaction.is_transfer == False,  # noqa: E712
            )
            result = await db.execute(stmt)
            total = result.scalar_one_or_none()
            if total is not None and total != 0:
                period_totals[cat.id].append(abs(float(total)))
```

Downstream, `period_totals[cat.id]` (a list of monthly spend totals) is averaged and
persisted. **Read the code after this block** to see exactly what it does with
`period_totals` (it computes an average and writes it to each category — confirm the
target field before writing the test).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_auto_budget.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/budget/service.py` (edit only the inner loop of `auto_budget_fixed_categories`)
- `api/tests/test_auto_budget.py` (create)

**Out of scope**:
- The rest of `auto_budget_fixed_categories` (the averaging/persist logic below the loop) — unchanged.
- Every other function in `budget/service.py`.
- The larger "single query for all periods at once" optimization — deliberately deferred
  (see Maintenance notes) to keep this change SQLite-safe and low-risk.

## Git workflow

- Branch: `advisor/009-batch-auto-budget-aggregation`
- Commit style: e.g. `perf(budget): batch auto-budget category sums per period`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Replace the inner per-category loop with one grouped query per period

Keep the outer `for yr, mo in periods:` loop. Replace the inner `for cat in categories:`
loop with a single query grouped by `category_id`:

```python
    category_ids = [cat.id for cat in categories]
    period_totals: dict[uuid.UUID, list[float]] = {cat.id: [] for cat in categories}

    for yr, mo in periods:
        _, last_day = _cal.monthrange(yr, mo)
        from datetime import date as _d2
        date_from = _d2(yr, mo, 1)
        date_to   = _d2(yr, mo, last_day)

        stmt = (
            select(
                BudgetTransaction.category_id,
                func.sum(BudgetTransaction.amount).label("total"),
            )
            .where(
                BudgetTransaction.household_id == household_id,
                BudgetTransaction.category_id.in_(category_ids),
                BudgetTransaction.date >= date_from,
                BudgetTransaction.date <= date_to,
                BudgetTransaction.amount < 0,          # expenses only
                BudgetTransaction.is_transfer == False,  # noqa: E712
            )
            .group_by(BudgetTransaction.category_id)
        )
        for cat_id, total in (await db.execute(stmt)).all():
            if total is not None and total != 0:
                period_totals[cat_id].append(abs(float(total)))
```

This preserves the exact same filters (household, category set, date range, expenses-only,
non-transfer) and the same `abs(...)` / skip-zero logic — it just fetches all categories'
sums for the period in one query. The downstream averaging/persist code is untouched and
still reads `period_totals[cat.id]`.

**Verify**: `grep -n "for cat in categories" api/src/life_dashboard/domains/budget/service.py` → the match count for THIS function drops (the inner loop is gone). `grep -n "group_by(BudgetTransaction.category_id)" api/src/life_dashboard/domains/budget/service.py` → at least one match.

### Step 2: Add a correctness test on a small fixture

Create `api/tests/test_auto_budget.py`. First **read the full `auto_budget_fixed_categories`
signature and its return value / persisted field** (what it writes as the computed average),
then seed a minimal fixture and assert the average is correct. Skeleton:

```python
from datetime import date

from life_dashboard.auth.models import Household
from life_dashboard.domains.budget.models import (
    BudgetAccount, BudgetCategory, BudgetProfile, BudgetTransaction,
)
from life_dashboard.domains.budget import service as budget_service


async def _seed(db):
    hh = Household(name="H"); db.add(hh); await db.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main"); db.add(profile); await db.flush()
    account = BudgetAccount(household_id=hh.id, profile_id=profile.id, name="Checking")  # adjust required fields
    db.add(account); await db.flush()
    cat = BudgetCategory(household_id=hh.id, profile_id=profile.id, name="Groceries")
    db.add(cat); await db.flush()
    # Two months, -100 spend each → average 100
    for d in (date(2026, 1, 15), date(2026, 2, 15)):
        db.add(BudgetTransaction(
            household_id=hh.id, account_id=account.id, category_id=cat.id,
            amount=-100, date=d, is_transfer=False,
        ))
    await db.flush()
    return hh, profile, cat


async def test_auto_budget_computes_average_monthly_spend(db_session):
    hh, profile, cat = await _seed(db_session)
    # Call auto_budget_fixed_categories with the real signature (read it first).
    await budget_service.auto_budget_fixed_categories(db_session, hh.id, ...)  # fill args
    await db_session.refresh(cat)
    assert float(cat.default_monthly_amount) == 100.0   # adjust to the real persisted field
```

Adaptation notes (IMPORTANT — read the code, don't guess):
- `BudgetAccount` / `BudgetTransaction` have required columns you must supply (read
  `budget/models.py`). If a required field is unclear, that's a STOP, not a guess.
- The function's real parameters (window length, profile filter, which field it writes)
  must come from reading its signature and body. Set the fixture's months to match the
  default window, or pass the window explicitly so both spend months are included.
- If the function writes to a field other than `default_monthly_amount`, assert on that
  field instead.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_auto_budget.py -v` → pass.

## Test plan

- `test_auto_budget_computes_average_monthly_spend` — a two-month, one-category fixture with
  known spend, asserting the computed average, which proves the batched aggregation yields
  the same numbers as the old per-category loop.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "group_by(BudgetTransaction.category_id)" api/src/life_dashboard/domains/budget/service.py` → ≥ 1 match
- [ ] The inner `for cat in categories:` aggregate loop no longer exists in `auto_budget_fixed_categories`
- [ ] `cd api && .venv/bin/python -m pytest tests/test_auto_budget.py` → pass
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `auto_budget_fixed_categories` loop no longer matches the "Current state" excerpt (drift).
- You cannot determine `auto_budget_fixed_categories`'s real parameters or which field it
  persists — report what you found; do not guess arguments repeatedly.
- Required columns on `BudgetAccount`/`BudgetTransaction` are unknown — report them.
- The batched query returns different totals than expected on the fixture — the filters may
  differ from the excerpt; re-read and reconcile before adjusting the source.

## Maintenance notes

- A further optimization exists: one query grouped by `(category_id, year, month)` over the
  whole window would cut this to a single query total. It's deferred here because `extract`
  / date-part grouping behaves differently across SQLite (tests) and Postgres (prod) and
  needs a Postgres-backed test to verify. Revisit once a Postgres CI job exists.
- The same audit flagged sibling N+1s in this file — `get_spending_trends` (fixed in plan
  010's neighborhood is a *different* bug; the trends N+1 is a separate follow-up) and
  `auto_categorize_transactions` (finding #16). Neither is in scope here.
- Reviewer should confirm the filters in the grouped query exactly match the original
  per-category query (household, date range, `amount < 0`, `is_transfer == False`).
