# Plan 003: Fix cross-household write in the goals → budget-category sync

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/domains/goals/service.py`
> If it changed since this plan was written, compare the "Current state" excerpts
> against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (adds a scoping filter + threads one argument; no change to legitimate same-household behavior)
- **Depends on**: plans/002-verification-baseline.md (for the `db_session` fixture the test uses)
- **Category**: security
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

`_sync_financial_link` in the goals service updates a `BudgetCategory` row selected
**only by its id**, with no `household_id` filter — and that id
(`financial_link.category_id`) comes straight from the request body. An
authenticated member of household A can create or update a goal whose
`financial_link` points at a `BudgetCategory` UUID belonging to household B, and on
commit the code overwrites **household B's** `default_monthly_amount`. This is a
cross-tenant write: a direct violation of the codebase's #1 invariant ("every DB
query in a service must filter by `household_id`", `.claude/rules/core-invariants.md`).
Exploitability is bounded by UUIDs being unguessable, but the isolation boundary is
definitively broken and a single leaked/logged category UUID makes it live. Every
other query in this service is correctly scoped — this one function is the outlier.

## Current state

File: `api/src/life_dashboard/domains/goals/service.py`.

The vulnerable function (lines 17–41):

```python
async def _sync_financial_link(
    db: AsyncSession,
    financial_link: dict | None,
) -> None:
    """
    If a spending_cap link is set, keep BudgetCategory.default_monthly_amount
    in sync with the goal's monthly_limit.
    """
    if not financial_link or financial_link.get("type") != "spending_cap":
        return
    category_id_str = financial_link.get("category_id")
    monthly_limit = financial_link.get("monthly_limit")
    if not category_id_str or monthly_limit is None:
        return

    try:
        category_id = uuid.UUID(category_id_str)
    except (ValueError, AttributeError):
        return

    from life_dashboard.domains.budget.models import BudgetCategory
    result = await db.execute(select(BudgetCategory).where(BudgetCategory.id == category_id))  # ← UNSCOPED
    category = result.scalar_one_or_none()
    if category is not None:
        category.default_monthly_amount = float(monthly_limit)
```

The two call sites both already have `household_id` in scope:

- `create_goal` (line 71): `await _sync_financial_link(db, data.financial_link)` — the
  enclosing function has `household_id: uuid.UUID` as a parameter.
- `update_goal` (line 138): `await _sync_financial_link(db, data.financial_link)` — the
  enclosing function has `household_id: uuid.UUID` as a parameter.

`BudgetCategory` (`budget/models.py:229`) has a `household_id` column
(`mapped_column(Uuid(), ForeignKey("households.id"...))`). The correct pattern used
everywhere else in the codebase is `.where(Model.id == x, Model.household_id == household_id)`.

Convention: service functions return `None` / silently no-op when a referenced entity
isn't found in-scope — they do NOT raise `HTTPException` (that's the router's job).
So if the category isn't found in the caller's household, the sync should simply skip
(exactly as it already does when `scalar_one_or_none()` returns `None`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run API tests | `cd api && .venv/bin/python -m pytest tests/test_goals_financial_link.py -v` | all pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | all pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |
| Confirm no unscoped select remains | `grep -n "select(BudgetCategory)" api/src/life_dashboard/domains/goals/service.py` | the match includes `household_id` |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/goals/service.py` (edit `_sync_financial_link` and its two callers)
- `api/tests/test_goals_financial_link.py` (create)

**Out of scope**:
- `api/src/life_dashboard/domains/budget/` — do not change budget models or services.
- The `financial_link` schema/shape — do not add validation there; the fix is the
  scoping filter.
- Any other function in `goals/service.py` — they are already correctly scoped.

## Git workflow

- Branch: `advisor/003-fix-cross-household-budget-write`
- Commit style: conventional commits, e.g.
  `fix(goals): scope budget-category sync to the caller's household`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Thread `household_id` into `_sync_financial_link` and add the scope filter

Change the function signature and the query:

```python
async def _sync_financial_link(
    db: AsyncSession,
    household_id: uuid.UUID,
    financial_link: dict | None,
) -> None:
    ...
    from life_dashboard.domains.budget.models import BudgetCategory
    result = await db.execute(
        select(BudgetCategory).where(
            BudgetCategory.id == category_id,
            BudgetCategory.household_id == household_id,
        )
    )
    category = result.scalar_one_or_none()
    if category is not None:
        category.default_monthly_amount = float(monthly_limit)
```

(Only the signature and the `select(...).where(...)` change; the rest of the body is
unchanged. A cross-household `category_id` now yields `None` and the sync no-ops,
which is the correct silent-skip behavior.)

**Verify**: `grep -n "BudgetCategory.household_id == household_id" api/src/life_dashboard/domains/goals/service.py` → one match.

### Step 2: Update both call sites to pass `household_id`

- `create_goal` (~line 71): `await _sync_financial_link(db, household_id, data.financial_link)`
- `update_goal` (~line 138): `await _sync_financial_link(db, household_id, data.financial_link)`

**Verify**: `grep -n "_sync_financial_link(db, household_id" api/src/life_dashboard/domains/goals/service.py` → two matches.

### Step 3: Add a regression test

Create `api/tests/test_goals_financial_link.py`. It seeds two households, each with a
budget profile + category, then asserts that a goal in household B **cannot** modify
household A's category, and that same-household sync still works. Use the `db_session`
fixture from `conftest.py` (created in plan 002).

```python
import uuid

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget.models import BudgetCategory, BudgetProfile
from life_dashboard.domains.goals.schemas import GoalCreate
from life_dashboard.domains.goals import service as goals_service


async def _seed_household_with_category(db, *, monthly=100.0):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main")
    db.add(profile)
    await db.flush()
    cat = BudgetCategory(
        household_id=hh.id, profile_id=profile.id, name="Groceries",
        default_monthly_amount=monthly,
    )
    db.add(cat)
    await db.flush()
    return hh, cat


async def test_cannot_sync_category_from_another_household(db_session):
    hh_a, cat_a = await _seed_household_with_category(db_session, monthly=100.0)
    hh_b, _cat_b = await _seed_household_with_category(db_session, monthly=50.0)
    user_b = User(email="b@example.com", password_hash="x", display_name="B")
    db_session.add(user_b)
    await db_session.flush()

    # Household B tries to point a spending_cap at Household A's category.
    await goals_service.create_goal(
        db_session,
        hh_b.id,
        user_b.id,
        GoalCreate(
            title="Cap",
            financial_link={
                "type": "spending_cap",
                "category_id": str(cat_a.id),
                "monthly_limit": 999.0,
            },
        ),
    )

    await db_session.refresh(cat_a)
    assert float(cat_a.default_monthly_amount) == 100.0  # UNCHANGED — cross-household write blocked


async def test_same_household_sync_still_works(db_session):
    hh, cat = await _seed_household_with_category(db_session, monthly=100.0)
    user = User(email="a@example.com", password_hash="x", display_name="A")
    db_session.add(user)
    await db_session.flush()

    await goals_service.create_goal(
        db_session,
        hh.id,
        user.id,
        GoalCreate(
            title="Cap",
            financial_link={
                "type": "spending_cap",
                "category_id": str(cat.id),
                "monthly_limit": 250.0,
            },
        ),
    )

    await db_session.refresh(cat)
    assert float(cat.default_monthly_amount) == 250.0  # in-household sync applied
```

Notes for the executor:
- `GoalCreate` may require other fields; read `goals/schemas.py` and supply the minimum
  required (title is likely the only required one — add others only if construction fails).
- If `create_goal` commits internally (it calls `await db.commit()`), the `db_session`
  fixture's connection still sees the row because it's the same connection — `refresh`
  will reflect the committed value. If you hit an "object is not bound to a session"
  error after commit, re-`select` the category by id instead of `refresh`.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_goals_financial_link.py -v` → both tests pass. Crucially, `test_cannot_sync_category_from_another_household` must pass **only because of the fix** — if you temporarily revert Step 1, it should fail (optional sanity check).

## Test plan

- `test_cannot_sync_category_from_another_household` — the security regression: a
  household-B goal must not mutate household-A's category.
- `test_same_household_sync_still_works` — guards against over-correcting (the
  legitimate same-household sync must still function).
- Model after the seeding pattern above; this is the first service-layer test — later
  plans reuse the `_seed_household_*` helper shape.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `cd api && .venv/bin/python -m pytest tests/test_goals_financial_link.py` → 2 passed
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `grep -n "select(BudgetCategory)" api/src/life_dashboard/domains/goals/service.py` → the query includes `BudgetCategory.household_id == household_id`
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `_sync_financial_link` body no longer matches the "Current state" excerpt (drift).
- `create_goal` / `update_goal` do not have a `household_id` parameter in scope at the
  call sites (they should — if not, the fix is larger and the assumption is wrong).
- The test cannot construct `GoalCreate`/`BudgetCategory`/`BudgetProfile` because a
  required field is unknown — report the missing field rather than guessing repeatedly.
- Plan 002 has not been executed (no `db_session` fixture / no `conftest.py`) — this
  plan's test depends on it.

## Maintenance notes

- Any future `financial_link` sub-type that writes to another domain's table must
  apply the same `household_id` scoping — treat `_sync_financial_link` as the
  cautionary example.
- Reviewer should scan the rest of `goals/service.py` (and any cross-domain writes
  elsewhere) for the same "select foreign entity by id only" shape; SECURITY-09 in the
  audit flagged `notes/service.py:148` and `templates/service.py:286` as lower-confidence
  read-back cousins worth a follow-up look (out of scope here).
- Follow-up deferred: a broader "cross-domain writes must be household-scoped" lint or
  review checklist.
