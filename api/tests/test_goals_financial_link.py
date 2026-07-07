from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget.models import BudgetCategory, BudgetProfile
from life_dashboard.domains.goals import service as goals_service
from life_dashboard.domains.goals.schemas import GoalCreate


async def _seed_household_with_category(db, *, monthly=100.0):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    profile = BudgetProfile(household_id=hh.id, name="Main")
    db.add(profile)
    await db.flush()
    cat = BudgetCategory(
        household_id=hh.id,
        profile_id=profile.id,
        name="Groceries",
        default_monthly_amount=monthly,
    )
    db.add(cat)
    await db.flush()
    return hh, cat


async def test_cannot_sync_category_from_another_household(db_session):
    hh_a, cat_a = await _seed_household_with_category(db_session, monthly=100.0)
    hh_b, _ = await _seed_household_with_category(db_session, monthly=50.0)
    user_b = User(email="b@example.com", password_hash="x", display_name="B")
    db_session.add(user_b)
    await db_session.flush()
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
    assert float(cat.default_monthly_amount) == 250.0
