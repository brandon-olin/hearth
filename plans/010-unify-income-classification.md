# Plan 010: Unify income classification on the `is_income` group flag

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/domains/budget/service.py`
> `budget/service.py` changes often — locate the code by the `get_spending_trends`
> function and the string `"income"` in its `case(...)` expression, not by line number.
> If the excerpt below no longer matches, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (aligns one reporting surface with the other two; guarded by a test)
- **Depends on**: plans/002-verification-baseline.md (for the `db_session` fixture)
- **Category**: bug
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

The budget domain classifies "income" two different ways in two reporting functions:

- `get_analytics` (and `get_summary`) use the group's explicit **`is_income` boolean flag**
  — the intended, user-controllable signal. Its comment (`service.py:1529-1531`) says: "Use
  the explicit is_income flag on the group ... rather than a hardcoded name match. This lets
  users name their income group anything they like (Salary, Inflows, etc.)."
- `get_spending_trends` instead uses a **hardcoded name match** `func.lower(group.name) == "income"`
  — and its own comment (`service.py:2734`) falsely claims it "matches get_analytics/get_summary".

So a household that renames its income group (explicitly supported) gets correct income in
the analytics/summary views but **wrong income in the trends chart** — the same numbers
diverge across surfaces, and a comment actively lies about it. This unifies trends onto the
`is_income` flag.

## Current state

File: `api/src/life_dashboard/domains/budget/service.py`.

The correct pattern, in `get_analytics` (~line 1532):
```python
        is_income_group = bool(row.group_is_income)   # explicit flag, not a name match
```

`BudgetCategoryGroup.is_income` is a real column (`budget/models.py:223`):
```python
    is_income: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
```

The buggy name-match, in `get_spending_trends` (~lines 2735–2761), inside the `agg_stmt`
`case(...)` expressions:
```python
        agg_stmt = (
            select(
                func.sum(
                    case(
                        (
                            and_(
                                BudgetTransaction.amount > 0,
                                func.lower(BudgetCategoryGroup.name) == "income",   # ← name match
                            ),
                            BudgetTransaction.amount,
                        ),
                        else_=0,
                    )
                ).label("total_income"),
                func.sum(
                    case(
                        (BudgetTransaction.amount < 0, BudgetTransaction.amount),
                        (
                            and_(
                                BudgetTransaction.amount > 0,
                                func.lower(func.coalesce(BudgetCategoryGroup.name, "")) != "income",  # ← name match
                            ),
                            BudgetTransaction.amount,
                        ),
                        else_=0,
                    )
                ).label("total_expenses"),
            )
            .join(BudgetAccount, ...)
            .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .outerjoin(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(...)
        )
```

The join to `BudgetCategoryGroup` is an **outer** join, so `is_income` can be NULL for
transactions with no category/group — those must be treated as **not income** (same as the
old `coalesce(name, "") != "income"` did).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_income_classification.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |
| Confirm name-match gone | `grep -n '== "income"' api/src/life_dashboard/domains/budget/service.py` | only line ~1755 (`effective_type == "income"`, unrelated) remains — none inside `get_spending_trends` |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/budget/service.py` (edit the two `case` conditions in `get_spending_trends`, and fix its misleading comment)
- `api/tests/test_income_classification.py` (create)

**Out of scope**:
- `get_analytics` / `get_summary` — already correct; do not touch.
- Line ~1755 `elif effective_type == "income":` — that's a recurrence/rule `type`, NOT a
  group name; leave it.
- Any other function in `budget/service.py`.

## Git workflow

- Branch: `advisor/010-unify-income-classification`
- Commit style: e.g. `fix(budget): classify trends income by is_income flag, not group name`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Replace both name-match conditions with the `is_income` flag

In `get_spending_trends`'s `agg_stmt`:

- The **income** branch condition:
  ```python
  func.lower(BudgetCategoryGroup.name) == "income",
  ```
  becomes:
  ```python
  BudgetCategoryGroup.is_income.is_(True),
  ```

- The **expense** positive-branch (non-income) condition:
  ```python
  func.lower(func.coalesce(BudgetCategoryGroup.name, "")) != "income",
  ```
  becomes (NULL group → not income, preserving the outer-join semantics):
  ```python
  func.coalesce(BudgetCategoryGroup.is_income, False).is_(False),
  ```

### Step 2: Fix the misleading comment

Update the comment above `agg_stmt` (currently ~line 2734) so it is true, e.g.:

```python
        # Income is scoped to categories whose group has is_income=True (matches
        # get_analytics/get_summary, which use the same explicit flag).
```

**Verify**: `grep -n "BudgetCategoryGroup.is_income" api/src/life_dashboard/domains/budget/service.py` → at least two new matches inside `get_spending_trends`; `grep -n '== "income"' api/src/life_dashboard/domains/budget/service.py` → the only remaining match is the unrelated `effective_type == "income"` (~line 1755).

### Step 3: Add a regression test with a renamed income group

Create `api/tests/test_income_classification.py`. The key case: a group flagged
`is_income=True` but **named something other than "Income"** must still be counted as income
by `get_spending_trends`. Read the `get_spending_trends` signature first (params for months,
profile_id, account_id, user_id).

```python
from datetime import date

from life_dashboard.auth.models import Household
from life_dashboard.domains.budget.models import (
    BudgetAccount, BudgetCategory, BudgetCategoryGroup, BudgetProfile, BudgetTransaction,
)
from life_dashboard.domains.budget import service as budget_service


async def test_renamed_income_group_counts_as_income_in_trends(db_session):
    hh = Household(name="H"); db_session.add(hh); await db_session.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main"); db_session.add(profile); await db_session.flush()
    account = BudgetAccount(household_id=hh.id, profile_id=profile.id, name="Checking")  # adjust required fields
    db_session.add(account); await db_session.flush()

    # Income group NOT named "Income" — the whole point of the is_income flag.
    grp = BudgetCategoryGroup(household_id=hh.id, profile_id=profile.id, name="Salary", is_income=True)
    db_session.add(grp); await db_session.flush()
    cat = BudgetCategory(household_id=hh.id, profile_id=profile.id, name="Paycheck", group_id=grp.id)
    db_session.add(cat); await db_session.flush()

    # A positive (income) transaction this month.
    today = date.today()
    db_session.add(BudgetTransaction(
        household_id=hh.id, account_id=account.id, category_id=cat.id,
        amount=1000, date=today, is_transfer=False,
    ))
    await db_session.flush()

    results = await budget_service.get_spending_trends(db_session, hh.id, ...)  # fill real args (months incl. today)
    # Find the row for the current month and assert income was recognized.
    row = next(r for r in results if r["year"] == today.year and r["month"] == today.month)
    assert row["total_income"] == 1000.0   # counted as income despite the group name "Salary"
    # And it must NOT be double-counted as an expense.
    assert row.get("total_expenses", 0) in (0, 0.0)
```

Adaptation notes:
- Supply required columns for `BudgetAccount`/`BudgetCategoryGroup`/`BudgetTransaction`
  (read `budget/models.py`); if any required field is unknown, STOP rather than guessing.
- Read `get_spending_trends`'s real return-dict keys — if it's not `total_income`/`year`/
  `month`, adjust the assertions to the actual keys (the excerpt in "Current state" shows the
  result dict is built with `"year"`, `"month"`, and the labels `total_income`/`total_expenses`).
- Ensure the `months` argument (or default window) includes the current month so the
  transaction falls in range.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_income_classification.py -v` → pass. (Against the pre-fix code this test fails, because "Salary" ≠ "income" — it is the regression guard.)

## Test plan

- `test_renamed_income_group_counts_as_income_in_trends` — the exact divergence the bug
  causes: a renamed income group must be recognized as income in the trends surface, matching
  analytics/summary.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "BudgetCategoryGroup.is_income" api/src/life_dashboard/domains/budget/service.py` → new matches inside `get_spending_trends`
- [ ] `grep -n '== "income"' api/src/life_dashboard/domains/budget/service.py` → only the unrelated `effective_type == "income"` remains
- [ ] `cd api && .venv/bin/python -m pytest tests/test_income_classification.py` → pass
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `get_spending_trends` `case(...)` expressions no longer match the "Current state" excerpt (drift).
- Required model columns for the test fixture are unknown — report them; don't guess repeatedly.
- `get_spending_trends`'s parameters or return-dict keys differ from the excerpt — read the
  real signature and reconcile before writing assertions.
- After the change the test still fails — verify the outer-join NULL handling
  (`coalesce(is_income, False)`) is correct for transactions without a group.

## Maintenance notes

- Any *new* budget reporting surface must classify income by `BudgetCategoryGroup.is_income`,
  never by group name. Treat this as the canonical rule; `get_analytics` is the reference.
- Reviewer should grep the whole file for other `== "income"` name comparisons introduced
  later.
- Follow-up deferred: a small shared helper (e.g. `_income_case(...)`) so all three surfaces
  share one classification expression and can't drift again — worth doing when the budget
  god-module is split (audit finding #20 / DEBT-01).
