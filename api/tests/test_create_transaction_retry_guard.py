"""Retry-window guard on create_transaction (plan 012, audit #19).

create_transaction computed a dedup_hash but never checked it, so a double-tap
/ network retry / background refetch inserted a second money row. The guard
treats an identical create on the same account within
CREATE_TXN_RETRY_WINDOW_SECONDS as a retry and returns the existing row. A hard
uniqueness rule on dedup_hash would be wrong (two same-price coffees on one day
are legitimate) — deliberate duplicates outside the window still insert.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget import service as budget_service
from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetProfile,
    BudgetTransaction,
)
from life_dashboard.domains.budget.schemas import BudgetTransactionCreate


async def _seed(db):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    user = User(email="a@example.com", password_hash="x", display_name="A")
    db.add(user)
    await db.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main")
    db.add(profile)
    await db.flush()
    account = BudgetAccount(
        household_id=hh.id, owner_user_id=user.id, profile_id=profile.id, name="Checking"
    )
    db.add(account)
    await db.flush()
    return hh, user, account


def _create(account, **overrides):
    base = dict(
        account_id=account.id,
        date=date(2026, 1, 15),
        amount=-12.50,
        description="Coffee",
    )
    base.update(overrides)
    return BudgetTransactionCreate(**base)


async def _count(db, account):
    rows = await db.execute(
        select(BudgetTransaction).where(BudgetTransaction.account_id == account.id)
    )
    return list(rows.scalars().all())


async def test_double_submit_returns_existing_row(db_session):
    hh, user, account = await _seed(db_session)

    first = await budget_service.create_transaction(
        db_session, hh.id, user.id, _create(account)
    )
    second = await budget_service.create_transaction(
        db_session, hh.id, user.id, _create(account)
    )

    assert first.id == second.id  # retry returned the same row
    assert len(await _count(db_session, account)) == 1  # only one money row


async def test_distinct_transactions_both_insert(db_session):
    hh, user, account = await _seed(db_session)

    a = await budget_service.create_transaction(
        db_session, hh.id, user.id, _create(account, amount=-12.50)
    )
    b = await budget_service.create_transaction(
        db_session, hh.id, user.id, _create(account, amount=-99.00)
    )

    assert a.id != b.id
    assert len(await _count(db_session, account)) == 2


async def test_old_identical_transaction_does_not_block(db_session):
    hh, user, account = await _seed(db_session)

    # An identical txn created well outside the retry window must not suppress a
    # new deliberate duplicate. Insert it directly with an explicit old created_at.
    window = budget_service.CREATE_TXN_RETRY_WINDOW_SECONDS
    old = BudgetTransaction(
        household_id=hh.id,
        account_id=account.id,
        owner_user_id=user.id,
        date=date(2026, 1, 15),
        amount=-12.50,
        description="Coffee",
        dedup_hash=budget_service._compute_dedup_hash(
            account.id, date(2026, 1, 15), -12.50, "Coffee"
        ),
        created_at=datetime.now(UTC) - timedelta(seconds=window + 60),
    )
    db_session.add(old)
    await db_session.flush()

    created = await budget_service.create_transaction(
        db_session, hh.id, user.id, _create(account)
    )

    assert created.id != old.id  # a fresh row, not the stale one
    assert len(await _count(db_session, account)) == 2
