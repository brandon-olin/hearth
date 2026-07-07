"""DB-level import dedup constraint tests (plan 011).

A partial unique index on budget_transactions (account_id, external_id) WHERE
external_id IS NOT NULL is the race-safe backstop for import dedup, which was
previously application-level only. These prove:
  1. the index exists in the (create_all) test schema and rejects a duplicate,
  2. bulk_import_transactions treats a constraint conflict as a skip, and
  3. NULL external_id rows (manual/CSV) remain unconstrained.
"""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget import service as budget_service
from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetProfile,
    BudgetTransaction,
)
from life_dashboard.domains.budget.schemas import BudgetTransactionCreate


async def _seed_account(db):
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


def _txn(hh, account, **overrides):
    base = dict(
        household_id=hh.id,
        account_id=account.id,
        owner_user_id=account.owner_user_id,
        date=date(2026, 1, 15),
        amount=-100,
        description="Coffee",
    )
    base.update(overrides)
    return BudgetTransaction(**base)


async def test_duplicate_external_id_rejected_by_db(db_session):
    hh, _user, account = await _seed_account(db_session)

    db_session.add(_txn(hh, account, external_id="bank-1"))
    await db_session.flush()

    # Same (account_id, external_id) — the unique index must reject it. This
    # bypasses the service-level set check to hit the DB directly.
    db_session.add(_txn(hh, account, external_id="bank-1", amount=-200, description="Again"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_bulk_import_skips_constraint_conflict(db_session):
    hh, _user, account = await _seed_account(db_session)

    # Pre-existing txn with external_id "t1".
    db_session.add(_txn(hh, account, external_id="t1", description="Existing"))
    await db_session.flush()

    result = await budget_service.bulk_import_transactions(
        db_session,
        hh.id,
        account.id,
        import_source="csv",
        transactions=[
            BudgetTransactionCreate(
                account_id=account.id, date=date(2026, 2, 1),
                amount=-50, description="Dupe of t1", external_id="t1",
            ),
            BudgetTransactionCreate(
                account_id=account.id, date=date(2026, 2, 2),
                amount=-75, description="Fresh", external_id="t2",
            ),
        ],
    )

    assert result.inserted == 1
    assert result.skipped == 1
    # The fresh t2 row now exists; t1 was not duplicated.
    rows = (
        await db_session.execute(
            BudgetTransaction.__table__.select().where(
                BudgetTransaction.account_id == account.id
            )
        )
    ).all()
    external_ids = sorted(r.external_id for r in rows)
    assert external_ids == ["t1", "t2"]


async def test_null_external_id_not_constrained(db_session):
    hh, _user, account = await _seed_account(db_session)

    # Two manual rows (no external_id) with the same account — both must insert.
    db_session.add(_txn(hh, account, external_id=None, description="Manual 1"))
    db_session.add(_txn(hh, account, external_id=None, description="Manual 2"))
    await db_session.flush()  # must not raise

    rows = (
        await db_session.execute(
            BudgetTransaction.__table__.select().where(
                BudgetTransaction.account_id == account.id
            )
        )
    ).all()
    assert len(rows) == 2
