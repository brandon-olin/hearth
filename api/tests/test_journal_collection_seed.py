"""Guards the invariant that infra-004 removed the boot hook for.

`backfill_journal_kind` used to re-seed a journal collection for any household
missing one on every boot. That scan is gone (folded into migration 0046), so
the invariant now rests entirely on `seed_default_journal_collection` being
called at household creation. ADR-014 action item 7 calls for a test in place
of the permanent boot scan — this is it.
"""

from sqlalchemy import func, select

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.collections.service import seed_default_journal_collection


async def _journal_count(db, household_id) -> int:
    return (await db.execute(
        select(func.count(Collection.id)).where(
            Collection.household_id == household_id,
            Collection.kind == "journal",
        )
    )).scalar_one()


async def test_seed_creates_exactly_one_journal_collection(db_session):
    hh = Household(name="H")
    user = User(email="seed@example.com", password_hash="x", display_name="Seed")
    db_session.add_all([hh, user])
    await db_session.flush()

    result = await seed_default_journal_collection(
        db_session, household_id=hh.id, user_id=user.id
    )

    assert result.kind == "journal"
    assert result.name == "Journal"
    assert await _journal_count(db_session, hh.id) == 1


async def test_seed_is_idempotent(db_session):
    """A retried signup (or a second call from the setup path) must not create
    a duplicate — the same behaviour migration 0046 relies on."""
    hh = Household(name="H")
    user = User(email="seed2@example.com", password_hash="x", display_name="Seed")
    db_session.add_all([hh, user])
    await db_session.flush()

    first = await seed_default_journal_collection(
        db_session, household_id=hh.id, user_id=user.id
    )
    second = await seed_default_journal_collection(
        db_session, household_id=hh.id, user_id=user.id
    )

    assert first.id == second.id
    assert await _journal_count(db_session, hh.id) == 1
