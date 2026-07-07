"""Correctness test for batched auto-budget aggregation (plan 009).

`auto_budget_fixed_categories` now sums every category for a period in a single
grouped query instead of one query per (period, category). This proves the
batched aggregation yields the same average as the old per-category loop.

The sampled window is the last N *full* calendar months relative to today, so
the fixture places transactions in months computed from `date.today()` rather
than hardcoded dates — otherwise the test would break as the calendar advances.
"""

from datetime import date

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget import service as budget_service
from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetProfile,
    BudgetTransaction,
)


def _nth_full_month(today: date, n: int) -> tuple[int, int]:
    """Return (year, month) of the Nth full calendar month before `today`.

    n=1 is last month (the most recent full month the function samples).
    """
    month = today.month - n
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return year, month


async def _seed(db):
    today = date.today()
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    user = User(email="a@example.com", password_hash="x", display_name="A")
    db.add(user)
    await db.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main")
    db.add(profile)
    await db.flush()
    group = BudgetCategoryGroup(
        household_id=hh.id, profile_id=profile.id, name="Fixed Monthly"
    )
    db.add(group)
    await db.flush()
    cat = BudgetCategory(
        household_id=hh.id, profile_id=profile.id, name="Groceries", group_id=group.id
    )
    db.add(cat)
    await db.flush()
    account = BudgetAccount(
        household_id=hh.id, owner_user_id=user.id, profile_id=profile.id, name="Checking"
    )
    db.add(account)
    await db.flush()

    # -100 spend in each of the two most recent full months → average 100.
    for n in (1, 2):
        yr, mo = _nth_full_month(today, n)
        db.add(
            BudgetTransaction(
                household_id=hh.id,
                account_id=account.id,
                owner_user_id=user.id,
                category_id=cat.id,
                date=date(yr, mo, 15),
                amount=-100,
                description="Grocery run",
                is_transfer=False,
            )
        )
    await db.flush()
    return hh, profile, cat


async def test_auto_budget_computes_average_monthly_spend(db_session):
    hh, profile, cat = await _seed(db_session)

    updated = await budget_service.auto_budget_fixed_categories(
        db_session, hh.id, profile_id=profile.id, months=3
    )

    await db_session.refresh(cat)
    assert float(cat.default_monthly_amount) == 100.0  # avg of two -100 months
    assert len(updated) == 1
    assert updated[0]["months_sampled"] == 2
    assert updated[0]["new_amount"] == 100.0


async def test_transfers_excluded_from_auto_budget(db_session):
    """A transfer in the window must not count toward the spend average."""
    hh, profile, cat = await _seed(db_session)
    today = date.today()
    yr, mo = _nth_full_month(today, 1)
    # A large transfer in a sampled month — must be ignored (is_transfer=True).
    account = (
        await db_session.execute(
            BudgetAccount.__table__.select().where(BudgetAccount.household_id == hh.id)
        )
    ).first()
    db_session.add(
        BudgetTransaction(
            household_id=hh.id,
            account_id=account.id,
            owner_user_id=account.owner_user_id,
            category_id=cat.id,
            date=date(yr, mo, 20),
            amount=-5000,
            description="Transfer to savings",
            is_transfer=True,
        )
    )
    await db_session.flush()

    await budget_service.auto_budget_fixed_categories(
        db_session, hh.id, profile_id=profile.id, months=3
    )

    await db_session.refresh(cat)
    assert float(cat.default_monthly_amount) == 100.0  # transfer excluded → still 100
