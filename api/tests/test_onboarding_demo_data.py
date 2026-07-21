"""Sample-data seeding and clearing (onboarding-002).

The three properties worth a regression test are the three that can silently
destroy or duplicate user content:

* seeding is idempotent, and refuses a household that already has content;
* clearing removes exactly the manifest and nothing else, even when the user
  created rows that hang off a seeded parent;
* clearing twice is a no-op rather than a half-delete.

Everything else the seeder produces (how many recipes, which merchants) is
content, not contract — asserted only loosely so copy edits don't break tests.
"""

import uuid

from sqlalchemy import func, select

from life_dashboard.auth.models import Household, User
from life_dashboard.domains.budget.models import BudgetAccount, BudgetTransaction
from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.habits.models import Habit
from life_dashboard.domains.notes.models import Note
from life_dashboard.domains.projects.models import Project
from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient
from life_dashboard.domains.todos.models import Todo
from life_dashboard.onboarding import service as onboarding
from life_dashboard.onboarding.models import DemoDataRecord


async def _household(db, email: str) -> tuple[Household, User]:
    hh = Household(name="Test Household")
    user = User(email=email, password_hash="x", display_name="Tester")
    db.add_all([hh, user])
    await db.flush()
    return hh, user


async def _count(db, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return (await db.execute(stmt)).scalar_one()


# ── Seeding ───────────────────────────────────────────────────────────────────

async def test_seed_creates_content_across_every_domain(db_session):
    hh, user = await _household(db_session, "seed@example.com")

    result = await onboarding.seed_demo_data(db_session, hh.id, user.id)

    assert result.seeded is True
    assert result.reason is None
    # 5 to-dos, one overdue and one due today; 3 habits; 4 categories with 12
    # transactions; 2 recipes; 1 goal linked to 1 project; 1 note.
    assert result.counts == {
        "todo": 5,
        "habit": 3,
        "goal": 1,
        "project": 1,
        "budget_account": 1,
        "budget_category_group": 1,
        "budget_category": 4,
        "budget_transaction": 12,
        "recipe": 2,
        "note": 1,
    }

    # Recipes really have ingredients, not just a name.
    assert await _count(db_session, RecipeIngredient) >= 10


async def test_seeded_todos_include_one_overdue_and_one_due_today(db_session):
    from datetime import date

    hh, user = await _household(db_session, "due@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    due_dates = (
        await db_session.execute(select(Todo.due_date).where(Todo.household_id == hh.id))
    ).scalars().all()
    today = date.today()
    assert any(d < today for d in due_dates), "expected an overdue sample to-do"
    assert any(d == today for d in due_dates), "expected a sample to-do due today"


async def test_budget_sample_data_lands_in_the_profile_the_ui_opens_on(db_session):
    """The budget page auto-selects profiles[0] ordered by (sort_order, name).
    Seeding anywhere else greets a new user with "No transactions yet" on a
    page that is holding twelve of them, one dropdown away."""
    from life_dashboard.domains.budget.models import BudgetCategory, BudgetProfile

    hh, user = await _household(db_session, "profile@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    first_profile = (
        await db_session.execute(
            select(BudgetProfile)
            .where(BudgetProfile.household_id == hh.id)
            .order_by(BudgetProfile.sort_order, BudgetProfile.name)
            .limit(1)
        )
    ).scalar_one()
    account = (
        await db_session.execute(
            select(BudgetAccount).where(BudgetAccount.household_id == hh.id)
        )
    ).scalar_one()
    assert account.profile_id == first_profile.id

    categories = (
        await db_session.execute(
            select(BudgetCategory).where(BudgetCategory.household_id == hh.id)
        )
    ).scalars().all()
    assert {c.profile_id for c in categories} == {first_profile.id}


async def test_seeded_note_lands_in_the_journal_collection(db_session):
    hh, user = await _household(db_session, "journal@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    journal = (
        await db_session.execute(
            select(Collection).where(
                Collection.household_id == hh.id, Collection.kind == "journal"
            )
        )
    ).scalar_one()
    note = (
        await db_session.execute(select(Note).where(Note.household_id == hh.id))
    ).scalar_one()
    assert note.collection_id == journal.id


async def test_seeding_twice_does_not_duplicate(db_session):
    """The manifest short-circuit is the guard a retried request hits."""
    hh, user = await _household(db_session, "twice@example.com")

    first = await onboarding.seed_demo_data(db_session, hh.id, user.id)
    second = await onboarding.seed_demo_data(db_session, hh.id, user.id)

    assert first.seeded is True
    assert second.seeded is False
    assert second.reason == "already_seeded"
    assert second.counts == first.counts
    assert await _count(db_session, Todo, household_id=hh.id) == 5
    assert await _count(db_session, Habit, household_id=hh.id) == 3
    assert await _count(db_session, Recipe, household_id=hh.id) == 2


async def test_household_with_real_data_is_never_seeded(db_session):
    hh, user = await _household(db_session, "busy@example.com")
    db_session.add(
        Todo(household_id=hh.id, created_by_user_id=user.id, title="My own to-do")
    )
    await db_session.flush()

    result = await onboarding.seed_demo_data(db_session, hh.id, user.id)

    assert result.seeded is False
    assert result.reason == "household_has_data"
    assert await _count(db_session, Todo, household_id=hh.id) == 1
    assert await _count(db_session, DemoDataRecord, household_id=hh.id) == 0


async def test_bootstrap_rows_do_not_count_as_real_data(db_session):
    """The system To-dos project and default Journal exist before the user has
    done anything — a household holding only those is still empty."""
    from life_dashboard.domains.collections.service import seed_default_journal_collection
    from life_dashboard.domains.projects.service import seed_system_project

    hh, user = await _household(db_session, "fresh@example.com")
    await seed_system_project(db_session, hh.id, user.id)
    await seed_default_journal_collection(db_session, hh.id, user.id)

    assert await onboarding.household_has_real_data(db_session, hh.id) is False
    assert (await onboarding.seed_demo_data(db_session, hh.id, user.id)).seeded is True


async def test_sample_data_alone_does_not_read_as_real_data(db_session):
    """Otherwise the banner could never truthfully say the household is empty."""
    hh, user = await _household(db_session, "sample@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    assert await onboarding.household_has_real_data(db_session, hh.id) is False


# ── Status ────────────────────────────────────────────────────────────────────

async def test_status_reports_presence_and_counts(db_session):
    hh, user = await _household(db_session, "status@example.com")

    before = await onboarding.demo_data_status(db_session, hh.id)
    assert before.present is False
    assert before.counts == {}

    await onboarding.seed_demo_data(db_session, hh.id, user.id)
    after = await onboarding.demo_data_status(db_session, hh.id)
    assert after.present is True
    assert after.counts["todo"] == 5


# ── Clearing ──────────────────────────────────────────────────────────────────

async def test_clear_removes_every_seeded_record(db_session):
    hh, user = await _household(db_session, "clear@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    result = await onboarding.clear_demo_data(db_session, hh.id)

    assert result.cleared is True
    assert result.counts["todo"] == 5
    for model in (Todo, Habit, Recipe, Note, BudgetTransaction, BudgetAccount):
        assert await _count(db_session, model, household_id=hh.id) == 0
    assert await _count(db_session, DemoDataRecord, household_id=hh.id) == 0
    # Children of seeded parents go with them on both engines, not just Postgres.
    assert await _count(db_session, RecipeIngredient) == 0
    # Bootstrap structure survives — clearing empties the journal, not deletes it.
    assert await _count(db_session, Collection, household_id=hh.id) == 1


async def test_clear_preserves_records_the_user_created(db_session):
    hh, user = await _household(db_session, "mine@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    mine = Todo(household_id=hh.id, created_by_user_id=user.id, title="Call the vet")
    my_habit = Habit(household_id=hh.id, created_by_user_id=user.id, name="Stretch")
    db_session.add_all([mine, my_habit])
    await db_session.flush()

    await onboarding.clear_demo_data(db_session, hh.id)

    surviving = (
        await db_session.execute(select(Todo).where(Todo.household_id == hh.id))
    ).scalars().all()
    assert [t.title for t in surviving] == ["Call the vet"]
    assert await _count(db_session, Habit, household_id=hh.id) == 1


async def test_clear_unparents_a_user_todo_filed_in_the_sample_project(db_session):
    """The FK says SET NULL; SQLite doesn't enforce it, so the service must."""
    hh, user = await _household(db_session, "nested@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    sample_project = (
        await db_session.execute(
            select(Project).where(
                Project.household_id == hh.id, Project.is_system.is_(False)
            )
        )
    ).scalar_one()
    mine = Todo(
        household_id=hh.id,
        created_by_user_id=user.id,
        title="Measure the splashback",
        project_id=sample_project.id,
    )
    db_session.add(mine)
    await db_session.flush()

    await onboarding.clear_demo_data(db_session, hh.id)
    await db_session.refresh(mine)

    assert mine.project_id is None
    assert await _count(db_session, Project, household_id=hh.id) == 0


async def test_clear_keeps_a_sample_account_that_holds_a_real_transaction(db_session):
    """budget_transactions.account_id CASCADEs — deleting the sample account
    would take the user's transaction with it. It is retained instead."""
    hh, user = await _household(db_session, "account@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    account = (
        await db_session.execute(
            select(BudgetAccount).where(BudgetAccount.household_id == hh.id)
        )
    ).scalar_one()
    from datetime import date

    mine = BudgetTransaction(
        household_id=hh.id,
        account_id=account.id,
        owner_user_id=user.id,
        date=date.today(),
        amount=-9.99,
        description="MY OWN COFFEE",
    )
    db_session.add(mine)
    await db_session.flush()

    result = await onboarding.clear_demo_data(db_session, hh.id)

    assert result.retained == {"budget_account": 1}
    assert await _count(db_session, BudgetAccount, household_id=hh.id) == 1
    surviving = (
        await db_session.execute(
            select(BudgetTransaction).where(BudgetTransaction.household_id == hh.id)
        )
    ).scalars().all()
    assert [t.description for t in surviving] == ["MY OWN COFFEE"]
    # The manifest still goes: with its sample transactions gone the account is
    # the user's now, and the banner has nothing left to offer to clear.
    assert await _count(db_session, DemoDataRecord, household_id=hh.id) == 0


async def test_clear_is_idempotent(db_session):
    hh, user = await _household(db_session, "twiceclear@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    first = await onboarding.clear_demo_data(db_session, hh.id)
    second = await onboarding.clear_demo_data(db_session, hh.id)

    assert first.cleared is True
    assert second.cleared is False
    assert second.counts == {}


async def test_clear_on_a_household_that_never_seeded_is_a_no_op(db_session):
    hh, _ = await _household(db_session, "never@example.com")

    result = await onboarding.clear_demo_data(db_session, hh.id)

    assert result.cleared is False
    assert result.counts == {}


async def test_clear_is_scoped_to_one_household(db_session):
    """The manifest is per household; one household clearing must not reach
    another's sample data."""
    hh_a, user_a = await _household(db_session, "a@example.com")
    hh_b, user_b = await _household(db_session, "b@example.com")
    await onboarding.seed_demo_data(db_session, hh_a.id, user_a.id)
    await onboarding.seed_demo_data(db_session, hh_b.id, user_b.id)

    await onboarding.clear_demo_data(db_session, hh_a.id)

    assert await _count(db_session, Todo, household_id=hh_a.id) == 0
    assert await _count(db_session, Todo, household_id=hh_b.id) == 5
    assert await _count(db_session, DemoDataRecord, household_id=hh_b.id) > 0


async def test_seeding_can_run_again_after_clearing(db_session):
    hh, user = await _household(db_session, "again@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)
    await onboarding.clear_demo_data(db_session, hh.id)

    result = await onboarding.seed_demo_data(db_session, hh.id, user.id)

    assert result.seeded is True
    assert await _count(db_session, Todo, household_id=hh.id) == 5


async def test_clear_tolerates_a_manifest_row_whose_entity_is_gone(db_session):
    """A user who deleted a sample to-do by hand must not break the Clear button."""
    hh, user = await _household(db_session, "ghost@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)

    todo = (
        await db_session.execute(select(Todo).where(Todo.household_id == hh.id).limit(1))
    ).scalar_one()
    await db_session.delete(todo)
    await db_session.flush()

    result = await onboarding.clear_demo_data(db_session, hh.id)

    assert result.cleared is True
    assert result.counts["todo"] == 4  # the honest number: four still existed
    assert await _count(db_session, DemoDataRecord, household_id=hh.id) == 0


async def test_clear_ignores_a_manifest_row_of_an_unknown_entity_type(db_session):
    """Forward compatibility: a row written by a newer seeder must not raise."""
    hh, user = await _household(db_session, "future@example.com")
    await onboarding.seed_demo_data(db_session, hh.id, user.id)
    db_session.add(
        DemoDataRecord(
            household_id=hh.id, entity_type="workout_template", entity_id=uuid.uuid4()
        )
    )
    await db_session.flush()

    result = await onboarding.clear_demo_data(db_session, hh.id)

    assert result.cleared is True
    assert "workout_template" not in result.counts


# ── Wizard flag ───────────────────────────────────────────────────────────────

async def test_wizard_flag_reads_from_preferences_per_member(db_session):
    fresh = User(email="new@example.com", password_hash="x",
                 preferences={"onboarding_completed": False})
    done = User(email="done@example.com", password_hash="x",
                preferences={"onboarding_completed": True})
    # Predates the wizard entirely — must not be dropped back into onboarding.
    legacy = User(email="old@example.com", password_hash="x", preferences=None)
    other_prefs = User(email="theme@example.com", password_hash="x",
                       preferences={"theme": {"accentId": "blue"}})

    assert onboarding.wizard_completed(fresh) is False
    assert onboarding.wizard_completed(done) is True
    assert onboarding.wizard_completed(legacy) is True
    assert onboarding.wizard_completed(other_prefs) is True


async def test_wizard_modules_tolerates_malformed_preferences(db_session):
    assert onboarding.wizard_modules(
        User(email="a@x.com", password_hash="x",
             preferences={"onboarding_modules": ["finance", "habits"]})
    ) == ["finance", "habits"]
    assert onboarding.wizard_modules(
        User(email="b@x.com", password_hash="x", preferences={"onboarding_modules": "finance"})
    ) == []
    assert onboarding.wizard_modules(
        User(email="c@x.com", password_hash="x", preferences=None)
    ) == []
