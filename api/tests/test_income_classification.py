"""Regression test for unified income classification in trends (plan 010).

`get_spending_trends` used to classify income by a hardcoded group-name match
(`lower(group.name) == "income"`), while `get_analytics`/`get_summary` use the
explicit `BudgetCategoryGroup.is_income` flag. A household that renamed its
income group (e.g. "Salary") therefore got correct income everywhere except the
trends chart. This test pins the fix: trends now uses the `is_income` flag, so a
renamed income group is still counted as income (and not double-counted as an
expense). It fails against the pre-fix code.
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


async def test_renamed_income_group_counts_as_income_in_trends(db_session):
    hh = Household(name="H")
    db_session.add(hh)
    await db_session.flush()
    user = User(email="a@example.com", password_hash="x", display_name="A")
    db_session.add(user)
    await db_session.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main")
    db_session.add(profile)
    await db_session.flush()
    account = BudgetAccount(
        household_id=hh.id, owner_user_id=user.id, profile_id=profile.id, name="Checking"
    )
    db_session.add(account)
    await db_session.flush()

    # Income group NOT named "Income" — the whole point of the is_income flag.
    grp = BudgetCategoryGroup(
        household_id=hh.id, profile_id=profile.id, name="Salary", is_income=True
    )
    db_session.add(grp)
    await db_session.flush()
    cat = BudgetCategory(
        household_id=hh.id, profile_id=profile.id, name="Paycheck", group_id=grp.id
    )
    db_session.add(cat)
    await db_session.flush()

    today = date.today()
    db_session.add(
        BudgetTransaction(
            household_id=hh.id,
            account_id=account.id,
            owner_user_id=user.id,
            category_id=cat.id,
            amount=1000,
            date=today,
            description="Paycheck",
            is_transfer=False,
        )
    )
    await db_session.flush()

    results = await budget_service.get_spending_trends(
        db_session, hh.id, user.id, months=6
    )

    row = next(
        r for r in results if r["year"] == today.year and r["month"] == today.month
    )
    assert row["total_income"] == 1000.0  # counted as income despite group name "Salary"
    assert row["total_expenses"] == 0.0  # and NOT double-counted as an expense


async def test_uncategorized_positive_amount_is_not_income(db_session):
    """A positive transaction with no category/group is an inflow but not income
    (outer join → NULL is_income coalesces to False)."""
    hh = Household(name="H")
    db_session.add(hh)
    await db_session.flush()
    user = User(email="b@example.com", password_hash="x", display_name="B")
    db_session.add(user)
    await db_session.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main")
    db_session.add(profile)
    await db_session.flush()
    account = BudgetAccount(
        household_id=hh.id, owner_user_id=user.id, profile_id=profile.id, name="Checking"
    )
    db_session.add(account)
    await db_session.flush()

    today = date.today()
    db_session.add(
        BudgetTransaction(
            household_id=hh.id,
            account_id=account.id,
            owner_user_id=user.id,
            category_id=None,  # no category → outer-joined group is NULL
            amount=250,
            date=today,
            description="Uncategorized refund",
            is_transfer=False,
        )
    )
    await db_session.flush()

    results = await budget_service.get_spending_trends(
        db_session, hh.id, user.id, months=6
    )
    row = next(
        r for r in results if r["year"] == today.year and r["month"] == today.month
    )
    # NULL is_income → not income; positive-non-income → counted as (negative) expense offset.
    assert row["total_income"] == 0.0
