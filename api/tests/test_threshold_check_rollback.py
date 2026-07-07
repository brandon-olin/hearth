"""_maybe_check_thresholds must not corrupt the caller's session (plan 013, #15).

The threshold check is best-effort — its failure must never block the primary
write, nor leave the session dirty for the next request. It is wrapped in a
SAVEPOINT: a failure rolls back only its partial work, leaving the outer
transaction clean AND the caller's already-committed objects intact.

Note: this deviates from the plan's literal `await db.rollback()` in the except
block. A bare rollback expires every ORM object in the session, so the caller's
just-created txn would be expired and `create_transaction`'s
`model_validate(txn)` would raise on the failure path (verified). The savepoint
achieves the plan's stated goal — "this helper never affects the caller's
session state" — without that regression. `test_create_transaction_survives_
threshold_failure` guards exactly that real path.
"""

from datetime import date

from sqlalchemy import select

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget import service as budget_service
from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetProfile,
    BudgetTransaction,
)
from life_dashboard.domains.budget.schemas import BudgetTransactionCreate


async def _seed_committed(db):
    hh = Household(name="H")
    db.add(hh)
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
    # Commit so the seed is durable regardless of what the helper does.
    await db.commit()
    return hh, user, account


async def test_threshold_failure_leaves_session_usable(db_session, monkeypatch):
    hh, user, account = await _seed_committed(db_session)

    async def boom(db, household_id):
        # Issue SQL first so the savepoint actually has work to roll back.
        await db.execute(select(1))
        raise RuntimeError("boom")

    monkeypatch.setattr(budget_service, "check_budget_thresholds", boom)

    # Must swallow the failure, not propagate it.
    await budget_service._maybe_check_thresholds(db_session, hh.id, date.today())

    # Session must be clean afterwards: a read and a fresh write both succeed,
    # and the seed objects were not expired by the failure handling.
    await db_session.execute(select(BudgetTransaction))
    db_session.add(
        BudgetTransaction(
            household_id=hh.id,
            account_id=account.id,  # not expired → no lazy IO
            owner_user_id=user.id,
            date=date.today(),
            amount=-5,
            description="After failure",
        )
    )
    await db_session.commit()  # would raise PendingRollbackError without the fix

    rows = (
        await db_session.execute(
            select(BudgetTransaction).where(BudgetTransaction.household_id == hh.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_threshold_success_commits(db_session, monkeypatch):
    """Happy path: no exception, helper runs (current-month guard passes),
    session usable — guards against the fix leaking onto the success path."""
    hh, _user, _account = await _seed_committed(db_session)
    called = {"yes": False}

    async def noop(db, household_id):
        called["yes"] = True

    monkeypatch.setattr(budget_service, "check_budget_thresholds", noop)

    await budget_service._maybe_check_thresholds(db_session, hh.id, date.today())

    assert called["yes"] is True
    await db_session.execute(select(BudgetTransaction))  # session still usable


async def test_create_transaction_survives_threshold_failure(db_session, monkeypatch):
    """The real regression guard: a threshold failure inside create_transaction
    must not break the response — the created txn is still returned and persisted."""
    hh, user, account = await _seed_committed(db_session)

    async def boom(db, household_id):
        await db.execute(select(1))
        raise RuntimeError("boom")

    monkeypatch.setattr(budget_service, "check_budget_thresholds", boom)

    resp = await budget_service.create_transaction(
        db_session,
        hh.id,
        user.id,
        BudgetTransactionCreate(
            account_id=account.id, date=date.today(), amount=-5, description="X"
        ),
    )

    assert resp.id is not None  # response serialized despite the threshold failure
    rows = (
        await db_session.execute(
            select(BudgetTransaction).where(BudgetTransaction.household_id == hh.id)
        )
    ).scalars().all()
    assert len(rows) == 1  # the txn was persisted
