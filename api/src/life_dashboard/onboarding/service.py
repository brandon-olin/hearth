"""Sample household data — seeding, clearing, and the guards around both.

onboarding-002. Three invariants shape everything here:

1. **Never seed over content the user created.** The trigger is not "the wizard
   finished"; it is "the wizard finished *and* this household is genuinely
   empty". :func:`household_has_real_data` asks the domain tables directly and
   discounts anything already in the manifest, so a household exploring sample
   data still reads as empty until the user writes something of their own.

2. **Seeding and clearing are both idempotent.** Seeding short-circuits on the
   manifest, so a retried request, a double-tapped button, or a background
   refetch cannot double the data. Clearing deletes by manifest id and tolerates
   rows that are already gone, so a second call returns 200 with zero counts
   rather than half-deleting anything.

3. **Clearing removes only what the seeder made.** Deletion walks the manifest
   child-first (see ``DEMO_ENTITY_TYPES``) so no cascade ever runs ahead of it.
   The one row that can acquire user-created children — the demo budget account,
   whose transactions cascade — is checked before deletion and left in place if
   the user has since put a real transaction on it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import User
from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetProfile,
    BudgetTransaction,
)
from life_dashboard.domains.budget.service import seed_default_profiles
from life_dashboard.domains.calendar_events.models import CalendarEvent
from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.collections.service import seed_default_journal_collection
from life_dashboard.domains.contacts.models import Contact
from life_dashboard.domains.documents.models import Document
from life_dashboard.domains.goals.models import Goal
from life_dashboard.domains.habits.models import Habit, HabitOccurrence
from life_dashboard.domains.notes.models import Note
from life_dashboard.domains.projects.models import Project, ProjectGoal
from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient, RecipeStep
from life_dashboard.domains.todos.models import Todo
from life_dashboard.onboarding.models import DEMO_ENTITY_TYPES, DemoDataRecord
from life_dashboard.onboarding.schemas import (
    ClearDemoDataResponse,
    DemoDataStatus,
    SeedDemoDataResponse,
)

#: Preference key holding the per-member wizard flag. Set to False at account
#: creation, flipped to True when the wizard finishes. A *missing* key means a
#: member who predates the wizard — treated as completed, never re-prompted.
WIZARD_FLAG_KEY = "onboarding_completed"
#: Preference key holding the module ids the member picked in the wizard.
WIZARD_MODULES_KEY = "onboarding_modules"

#: entity_type → (model, id attribute). The clear path resolves rows through
#: this map; an entity_type absent here is skipped rather than raising, so a
#: manifest row written by a newer seeder can't break an older clear.
_ENTITY_MODELS = {
    "budget_transaction": BudgetTransaction,
    "todo": Todo,
    "habit": Habit,
    "recipe": Recipe,
    "note": Note,
    "goal": Goal,
    "project": Project,
    "budget_category": BudgetCategory,
    "budget_category_group": BudgetCategoryGroup,
    "budget_account": BudgetAccount,
}


# ── Real-data detection ───────────────────────────────────────────────────────

async def _manifest_ids(
    db: AsyncSession, household_id: uuid.UUID
) -> dict[str, set[uuid.UUID]]:
    """Every entity the seeder created for this household, grouped by type."""
    rows = (
        await db.execute(
            select(DemoDataRecord.entity_type, DemoDataRecord.entity_id).where(
                DemoDataRecord.household_id == household_id
            )
        )
    ).all()
    out: dict[str, set[uuid.UUID]] = {}
    for entity_type, entity_id in rows:
        out.setdefault(entity_type, set()).add(entity_id)
    return out


async def household_has_real_data(
    db: AsyncSession, household_id: uuid.UUID
) -> bool:
    """True when this household holds anything the *user* created.

    Deliberately broader than the set of domains the seeder writes to: the
    question is "would seeding here be an intrusion?", and a household with
    contacts and a calendar full of events is plainly in use even if its to-do
    list is empty.

    Two kinds of row are discounted, and both are bootstrap artefacts rather
    than user content:

    * anything in the demo manifest — sample data is not a reason to refuse to
      re-seed, and more importantly the banner must be able to say "you have no
      real data yet" while sample data is on screen;
    * the system "To-dos" project and the default Journal collection, which
      every household gets at signup before the user has done anything.

    Returns on the first non-empty table — this runs on the wizard's last step,
    so short-circuiting matters more than a complete tally.
    """
    demo = await _manifest_ids(db, household_id)

    checks: list[tuple[type, str, list]] = [
        (Todo, "todo", []),
        (Habit, "habit", []),
        (Recipe, "recipe", []),
        (Note, "note", []),
        (Goal, "goal", []),
        # The system "To-dos" project is seeded at signup — not user content.
        (Project, "project", [Project.is_system.is_(False)]),
        (BudgetTransaction, "budget_transaction", []),
        (BudgetCategory, "budget_category", []),
        (BudgetAccount, "budget_account", []),
        (CalendarEvent, None, []),
        (Document, None, []),
        (Contact, None, []),
    ]

    for model, entity_type, extra in checks:
        stmt = select(func.count()).select_from(model).where(
            model.household_id == household_id
        )
        for clause in extra:
            stmt = stmt.where(clause)
        seeded = demo.get(entity_type) if entity_type else None
        if seeded:
            stmt = stmt.where(model.id.not_in(seeded))
        if (await db.execute(stmt)).scalar_one() > 0:
            return True

    # A user-created collection beyond the default Journal also counts.
    collections = (
        await db.execute(
            select(func.count())
            .select_from(Collection)
            .where(
                Collection.household_id == household_id,
                Collection.kind.is_distinct_from("journal"),
            )
        )
    ).scalar_one()
    return collections > 0


# ── Status ────────────────────────────────────────────────────────────────────

async def demo_data_status(
    db: AsyncSession, household_id: uuid.UUID
) -> DemoDataStatus:
    """Manifest counts by entity type — what the dashboard banner reads."""
    rows = (
        await db.execute(
            select(DemoDataRecord.entity_type, func.count())
            .where(DemoDataRecord.household_id == household_id)
            .group_by(DemoDataRecord.entity_type)
        )
    ).all()
    counts = {entity_type: count for entity_type, count in rows if count}
    return DemoDataStatus(present=bool(counts), counts=counts)


def wizard_completed(user: User) -> bool:
    """Whether this member has finished the first-run wizard.

    A missing key means the account predates the wizard — treated as completed
    so established users are never dropped back into onboarding. Only an
    explicit ``False``, written at account creation, means "show the wizard".
    """
    return (user.preferences or {}).get(WIZARD_FLAG_KEY, True) is not False


def wizard_modules(user: User) -> list[str]:
    """Module ids the member picked in the wizard, or [] if none/malformed."""
    raw = (user.preferences or {}).get(WIZARD_MODULES_KEY)
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, str)]


# ── Seeding ───────────────────────────────────────────────────────────────────

def _record(
    db: AsyncSession, household_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> None:
    db.add(
        DemoDataRecord(
            household_id=household_id, entity_type=entity_type, entity_id=entity_id
        )
    )


async def seed_demo_data(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SeedDemoDataResponse:
    """Fill an empty household with explorable sample content.

    Idempotent on two levels. The manifest check below makes a repeat call a
    no-op, and the unique constraint on ``demo_data_records`` would stop a
    double-write even if two requests raced past it. Both guards run before
    anything is created, so a second call never leaves a partial second copy.

    Returns ``seeded=False`` with a ``reason`` when it declines — that is a
    successful outcome, not an error.
    """
    existing = await demo_data_status(db, household_id)
    if existing.present:
        return SeedDemoDataResponse(
            seeded=False, reason="already_seeded", counts=existing.counts
        )

    if await household_has_real_data(db, household_id):
        return SeedDemoDataResponse(seeded=False, reason="household_has_data")

    today = date.today()

    # Bootstrap structure the seeder writes *into* — budget profiles and the
    # Journal collection. Both helpers commit, so they run before anything is
    # recorded in the manifest; otherwise their commit would flush a half-built
    # sample set that a later failure could not roll back.
    profile = await _default_budget_profile(db, household_id, user_id)
    journal = await _journal_collection(db, household_id, user_id)

    await _seed_tasks(db, household_id, user_id, today)
    await _seed_habits(db, household_id, user_id, today)
    await _seed_budget(db, household_id, user_id, today, profile)
    await _seed_recipes(db, household_id, user_id)
    await _seed_note(db, household_id, user_id, today, journal)

    await db.commit()
    return SeedDemoDataResponse(
        seeded=True, counts=(await demo_data_status(db, household_id)).counts
    )


async def _default_budget_profile(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> BudgetProfile:
    """The profile the budget page opens on, creating the default pair if needed.

    Ordered by ``(sort_order, name)`` to mirror ``budget.service.list_profiles``
    exactly, because the budget page auto-selects ``profiles[0]``. Seeding into
    any other profile would put the sample transactions one dropdown away from
    a user who has never seen the dropdown — the page would greet them with
    "No transactions yet" while holding twelve. Following the same ordering the
    UI follows keeps the two in step if the default profile set ever changes.

    Profiles are never recorded in the manifest. Every household gets the
    Personal/Household pair as structure, the same way it gets a system project;
    clearing sample data should leave the household budget-ready, not tear the
    scaffolding out from under it.
    """
    stmt = (
        select(BudgetProfile)
        .where(BudgetProfile.household_id == household_id)
        .order_by(BudgetProfile.sort_order, BudgetProfile.name)
        .limit(1)
    )
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is not None:
        return profile
    await seed_default_profiles(db, household_id, user_id)
    return (await db.execute(stmt)).scalar_one()


async def _journal_collection(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> Collection:
    """The household's Journal collection, creating it if signup somehow didn't.

    Bootstrap structure, not sample data: it is not recorded in the manifest, so
    clearing empties the journal rather than removing it.
    """
    stmt = select(Collection).where(
        Collection.household_id == household_id, Collection.kind == "journal"
    )
    journal = (await db.execute(stmt)).scalar_one_or_none()
    if journal is not None:
        return journal
    await seed_default_journal_collection(db, household_id, user_id)
    return (await db.execute(stmt)).scalar_one()


async def _seed_tasks(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID, today: date
) -> None:
    """A project, a goal linked to it, and five to-dos — one overdue, one due today.

    The to-dos land in the household's system "To-dos" project so they show up
    where the app already points new users, rather than in a project they have
    to go find.
    """
    system_project = (
        await db.execute(
            select(Project).where(
                Project.household_id == household_id, Project.is_system.is_(True)
            )
        )
    ).scalar_one_or_none()

    project = Project(
        household_id=household_id,
        created_by_user_id=user_id,
        name="Kitchen Refresh",
        description="A sample project — repaint, replace the pulls, and re-tile the splashback.",
        status="in_progress",
        due_date=today + timedelta(days=45),
        show_in_nav=False,
        sort_order=1,
    )
    db.add(project)
    await db.flush()
    _record(db, household_id, "project", project.id)

    goal = Goal(
        household_id=household_id,
        created_by_user_id=user_id,
        title="Finish the kitchen refresh",
        description="A sample goal, linked to the Kitchen Refresh project.",
        status="active",
        priority="medium",
        target_value=3,
        current_value=1,
        unit="phases",
        due_date=today + timedelta(days=45),
    )
    db.add(goal)
    await db.flush()
    _record(db, household_id, "goal", goal.id)

    # The join row is not recorded separately: it cascades from either side, and
    # both sides are in the manifest.
    db.add(ProjectGoal(project_id=project.id, goal_id=goal.id))

    todos = [
        ("Book the plumber", today - timedelta(days=3), "high", system_project),
        ("Take the recycling out", today, "medium", system_project),
        ("Pick paint samples", today + timedelta(days=2), "medium", project),
        ("Order cabinet pulls", today + timedelta(days=6), "low", project),
        ("Plan next week's meals", today + timedelta(days=4), "low", system_project),
    ]
    for title, due, priority, parent in todos:
        todo = Todo(
            household_id=household_id,
            created_by_user_id=user_id,
            project_id=parent.id if parent is not None else None,
            title=title,
            status="pending",
            priority=priority,
            due_date=due,
            visibility="household",
        )
        db.add(todo)
        await db.flush()
        _record(db, household_id, "todo", todo.id)


async def _seed_habits(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID, today: date
) -> None:
    """Three habits covering both cadences the tracker supports."""
    specs = [
        ("Drink water", "Eight glasses a day.", "daily", {"start_date": today.isoformat()}),
        (
            "Work out",
            "Three sessions a week.",
            "weekly",
            {"times_per_period": 3, "start_date": today.isoformat()},
        ),
        (
            "Journal",
            "A few lines before bed.",
            "daily",
            {"start_date": today.isoformat(), "link": {"path": "/notes", "label": "Notes"}},
        ),
    ]
    for name, description, frequency, cadence in specs:
        habit = Habit(
            household_id=household_id,
            created_by_user_id=user_id,
            name=name,
            description=description,
            frequency=frequency,
            cadence=cadence,
            status="active",
            visibility="household",
        )
        db.add(habit)
        await db.flush()
        _record(db, household_id, "habit", habit.id)


async def _seed_budget(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    today: date,
    profile: BudgetProfile,
) -> None:
    """One account, four categories in a group, and twelve transactions this month."""
    account = BudgetAccount(
        household_id=household_id,
        owner_user_id=user_id,
        profile_id=profile.id,
        name="Sample Checking",
        account_type="checking",
        scope="shared",
        currency="USD",
        current_balance=2840.00,
        balance_updated_at=datetime.now(UTC),
    )
    db.add(account)
    await db.flush()
    _record(db, household_id, "budget_account", account.id)

    group = BudgetCategoryGroup(
        household_id=household_id,
        profile_id=profile.id,
        name="Everyday Spending",
        sort_order=2,
        is_income=False,
    )
    db.add(group)
    await db.flush()
    _record(db, household_id, "budget_category_group", group.id)

    category_specs = [
        ("Groceries", 600.00, "🛒"),
        ("Dining out", 200.00, "🍜"),
        ("Transport", 150.00, "🚌"),
        ("Home & garden", 250.00, "🪴"),
    ]
    categories: dict[str, BudgetCategory] = {}
    for sort_order, (name, monthly, icon) in enumerate(category_specs):
        category = BudgetCategory(
            household_id=household_id,
            profile_id=profile.id,
            name=name,
            default_scope="shared",
            group_id=group.id,
            default_monthly_amount=monthly,
            icon=icon,
            sort_order=sort_order,
        )
        db.add(category)
        await db.flush()
        _record(db, household_id, "budget_category", category.id)
        categories[name] = category

    # Twelve transactions spread across the current month. Day-of-month values
    # are clamped so this seeds correctly on the 1st and in February alike.
    month_start = today.replace(day=1)
    last_day = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    def day(n: int) -> date:
        return month_start + timedelta(days=min(n, last_day.day) - 1)

    transactions = [
        (2, -84.32, "WHOLE FOODS MKT", "Whole Foods", "Groceries"),
        (3, -12.40, "BLUE BOTTLE COFFEE", "Blue Bottle", "Dining out"),
        (5, -46.15, "SHELL OIL 574", "Shell", "Transport"),
        (7, -119.87, "TRADER JOE'S #443", "Trader Joe's", "Groceries"),
        (9, -63.20, "THE GOOD FORK", "The Good Fork", "Dining out"),
        (11, -28.99, "ACE HARDWARE", "Ace Hardware", "Home & garden"),
        (13, -92.44, "TRADER JOE'S #443", "Trader Joe's", "Groceries"),
        (16, -18.75, "METRO TRANSIT", "Metro Transit", "Transport"),
        (18, -134.10, "GARDEN CENTER", "Garden Center", "Home & garden"),
        (21, -22.50, "TACO STAND", "Taco Stand", "Dining out"),
        (24, -76.03, "WHOLE FOODS MKT", "Whole Foods", "Groceries"),
        (26, -41.60, "SHELL OIL 574", "Shell", "Transport"),
    ]
    for day_of_month, amount, description, merchant, category_name in transactions:
        txn = BudgetTransaction(
            household_id=household_id,
            account_id=account.id,
            owner_user_id=user_id,
            category_id=categories[category_name].id,
            date=day(day_of_month),
            amount=amount,
            currency="USD",
            description=description,
            merchant_name=merchant,
            scope="shared",
            import_source="manual",
        )
        db.add(txn)
        await db.flush()
        _record(db, household_id, "budget_transaction", txn.id)


async def _seed_recipes(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Two recipes with ingredients and steps.

    Ingredients and steps are not recorded individually — they cascade from the
    recipe, which is in the manifest, and they cannot outlive it.
    """
    specs = [
        {
            "name": "Weeknight Pasta",
            "description": "A sample recipe. Ready in the time the water boils.",
            "prep_time_minutes": 10,
            "cook_time_minutes": 15,
            "servings": 4,
            "ingredients": [
                ("Spaghetti", 400, "g", None),
                ("Garlic", 4, "cloves", "thinly sliced"),
                ("Olive oil", 3, "tbsp", None),
                ("Chilli flakes", 1, "tsp", "to taste"),
                ("Parmesan", 60, "g", "finely grated"),
                ("Flat-leaf parsley", 1, "handful", "chopped"),
            ],
            "steps": [
                "Boil the pasta in well-salted water until just shy of al dente.",
                "Warm the oil, garlic and chilli in a wide pan over low heat.",
                "Drain the pasta, keeping a cup of the water, and add it to the pan.",
                "Toss with the parmesan and enough pasta water to make it glossy.",
                "Finish with the parsley and more cheese.",
            ],
        },
        {
            "name": "Sheet-Pan Roast Chicken",
            "description": "A sample recipe. One pan, one hour, very little washing up.",
            "prep_time_minutes": 15,
            "cook_time_minutes": 50,
            "servings": 4,
            "ingredients": [
                ("Chicken thighs", 8, "pieces", "bone-in, skin-on"),
                ("Baby potatoes", 750, "g", "halved"),
                ("Red onion", 2, None, "cut into wedges"),
                ("Lemon", 1, None, "sliced"),
                ("Olive oil", 3, "tbsp", None),
                ("Thyme", 6, "sprigs", None),
            ],
            "steps": [
                "Heat the oven to 200°C / 400°F.",
                "Toss the potatoes and onion with oil, salt and thyme on a sheet pan.",
                "Nestle the chicken and lemon slices on top, skin side up.",
                "Roast for 45–50 minutes, until the skin is crisp and the potatoes are tender.",
                "Rest for five minutes before serving.",
            ],
        },
    ]

    for spec in specs:
        recipe = Recipe(
            household_id=household_id,
            created_by_user_id=user_id,
            name=spec["name"],
            description=spec["description"],
            prep_time_minutes=spec["prep_time_minutes"],
            cook_time_minutes=spec["cook_time_minutes"],
            servings=spec["servings"],
            visibility="household",
        )
        db.add(recipe)
        await db.flush()
        _record(db, household_id, "recipe", recipe.id)

        for sort_order, (name, quantity, unit, notes) in enumerate(spec["ingredients"]):
            db.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    name=name,
                    quantity=quantity,
                    unit=unit,
                    notes=notes,
                    sort_order=sort_order,
                )
            )
        for step_number, instruction in enumerate(spec["steps"], start=1):
            db.add(
                RecipeStep(
                    recipe_id=recipe.id, step_number=step_number, instruction=instruction
                )
            )


async def _seed_note(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    today: date,
    journal: Collection,
) -> None:
    """One note in the household's Journal collection."""
    # Built by hand rather than with strftime: the no-pad day directive is
    # "%-d" on glibc/BSD and "%#d" on Windows, and neither is portable.
    title = f"{today:%A, %B} {today.day}, {today.year}"

    note = Note(
        household_id=household_id,
        created_by_user_id=user_id,
        collection_id=journal.id,
        title=title,
        content_md=(
            "This is a sample journal entry so the Journal doesn't start empty.\n\n"
            "Notes are plain markdown. Link them together with `[[double brackets]]` "
            "and the backlinks build themselves.\n\n"
            "Clear the sample data from the dashboard banner whenever you're ready "
            "to start your own."
        ),
        visibility="household",
    )
    db.add(note)
    await db.flush()
    _record(db, household_id, "note", note.id)


# ── Clearing ──────────────────────────────────────────────────────────────────

async def _account_has_user_transactions(
    db: AsyncSession, account_id: uuid.UUID, demo_transaction_ids: set[uuid.UUID]
) -> bool:
    """True when a transaction the seeder did NOT create sits on this account.

    ``budget_transactions.account_id`` cascades on delete, so dropping the demo
    account would silently take a transaction the user added to it. That is the
    one place in this feature where clearing could destroy real content, so it
    is the one place that checks before deleting.
    """
    stmt = select(func.count()).select_from(BudgetTransaction).where(
        BudgetTransaction.account_id == account_id
    )
    if demo_transaction_ids:
        stmt = stmt.where(BudgetTransaction.id.not_in(demo_transaction_ids))
    return (await db.execute(stmt)).scalar_one() > 0


async def _detach_and_delete_children(
    db: AsyncSession, manifest: dict[str, set[uuid.UUID]]
) -> None:
    """Do by hand what the FK declarations promise, so both engines agree.

    Every relationship handled here is already declared ``ON DELETE CASCADE`` or
    ``ON DELETE SET NULL``, and Postgres honours them. The SQLite/Tauri tier does
    not enable ``PRAGMA foreign_keys``, so the identical delete would leave
    orphaned ingredients and to-dos pointing at a project that no longer exists.
    Writing both halves explicitly means clearing behaves the same wherever it
    runs, instead of depending on which engine is underneath.

    Two different jobs, in order:

    * **Detach** — null out references *from* rows that survive. A to-do the
      user filed under the sample project must outlive it, unparented.
    * **Delete** — remove rows that hang off a seeded parent and cannot
      meaningfully outlive it. None of these is independently addressable in the
      UI: an ingredient belongs to its recipe, an occurrence to its habit.
    """
    recipe_ids = manifest.get("recipe")
    habit_ids = manifest.get("habit")
    project_ids = manifest.get("project")
    goal_ids = manifest.get("goal")
    category_ids = manifest.get("budget_category")
    group_ids = manifest.get("budget_category_group")

    # ── Detach survivors ──────────────────────────────────────────────────
    if project_ids:
        await db.execute(
            update(Todo).where(Todo.project_id.in_(project_ids)).values(project_id=None)
        )
        await db.execute(
            update(Project)
            .where(Project.parent_id.in_(project_ids))
            .values(parent_id=None)
        )
    if goal_ids:
        await db.execute(
            update(Habit).where(Habit.goal_id.in_(goal_ids)).values(goal_id=None)
        )
        await db.execute(
            update(Recipe).where(Recipe.goal_id.in_(goal_ids)).values(goal_id=None)
        )
        await db.execute(
            update(Goal).where(Goal.parent_id.in_(goal_ids)).values(parent_id=None)
        )
    if category_ids:
        await db.execute(
            update(BudgetTransaction)
            .where(BudgetTransaction.category_id.in_(category_ids))
            .values(category_id=None)
        )
    if group_ids:
        await db.execute(
            update(BudgetCategory)
            .where(BudgetCategory.group_id.in_(group_ids))
            .values(group_id=None)
        )

    # ── Delete owned children ─────────────────────────────────────────────
    if recipe_ids:
        await db.execute(
            delete(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids))
        )
        await db.execute(delete(RecipeStep).where(RecipeStep.recipe_id.in_(recipe_ids)))
    if habit_ids:
        await db.execute(
            delete(HabitOccurrence).where(HabitOccurrence.habit_id.in_(habit_ids))
        )
    if project_ids:
        await db.execute(
            delete(ProjectGoal).where(ProjectGoal.project_id.in_(project_ids))
        )
    if goal_ids:
        await db.execute(delete(ProjectGoal).where(ProjectGoal.goal_id.in_(goal_ids)))


async def clear_demo_data(
    db: AsyncSession, household_id: uuid.UUID
) -> ClearDemoDataResponse:
    """Delete every row in this household's demo manifest, and nothing else.

    Idempotent: with no manifest rows this deletes nothing and returns 200 with
    ``cleared=False``. Deletion order is child-first
    (:data:`~life_dashboard.onboarding.models.DEMO_ENTITY_TYPES`) so a cascade
    never reaches a row before the manifest does.
    """
    manifest = await _manifest_ids(db, household_id)
    if not manifest:
        return ClearDemoDataResponse(cleared=False)

    await _detach_and_delete_children(db, manifest)

    demo_transaction_ids = manifest.get("budget_transaction", set())
    counts: dict[str, int] = {}
    retained: dict[str, int] = {}

    for entity_type in DEMO_ENTITY_TYPES:
        ids = manifest.get(entity_type)
        if not ids:
            continue
        model = _ENTITY_MODELS.get(entity_type)
        if model is None:
            continue

        deletable = set(ids)
        if entity_type == "budget_account":
            for account_id in sorted(ids, key=str):
                if await _account_has_user_transactions(
                    db, account_id, demo_transaction_ids
                ):
                    deletable.discard(account_id)
            kept = len(ids) - len(deletable)
            if kept:
                retained[entity_type] = kept

        if not deletable:
            continue

        result = await db.execute(
            delete(model).where(
                model.household_id == household_id, model.id.in_(deletable)
            )
        )
        # rowcount counts rows that still existed. A row the user deleted by
        # hand before clearing is simply not counted — the honest number.
        if result.rowcount:
            counts[entity_type] = result.rowcount

    # The manifest goes entirely, including entries for a retained account. Once
    # its sample transactions are gone and only the user's own remain, that
    # account is the user's, not sample data — keeping it flagged would leave
    # the dashboard banner up forever with nothing left to clear.
    await db.execute(
        delete(DemoDataRecord).where(DemoDataRecord.household_id == household_id)
    )

    await db.commit()
    return ClearDemoDataResponse(cleared=True, counts=counts, retained=retained)
