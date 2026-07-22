"""chat-001 — the chat context resolver.

Two things these tests exist to prove:

1. Each formatter actually produces content. `resolve_chat_context` wraps
   every formatter in a try/except so a stale ref can never break a chat
   turn — which means a formatter reading a field that doesn't exist fails
   *silently* and the feature quietly does nothing. Asserting on the
   rendered text is the only way to catch that.

2. Visibility is enforced before anything is read. Passing another user's
   personal resource id must yield "" — no title, no body, nothing.
"""
from decimal import Decimal

from life_dashboard.ai.chat_context_resolver import resolve_chat_context
from life_dashboard.ai.schemas import ChatContextRef
from life_dashboard.auth.models import Household, User
from life_dashboard.core.visibility import (
    VISIBILITY_HOUSEHOLD,
    VISIBILITY_PERSONAL,
)
from life_dashboard.domains.documents.models import Document
from life_dashboard.domains.goals.models import Goal
from life_dashboard.domains.habits.models import Habit
from life_dashboard.domains.notes.models import Note
from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient, RecipeStep
from life_dashboard.domains.todos.models import Todo


async def _household_with_two_users(db):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    alice = User(email="alice@example.com", password_hash="x", display_name="Alice")
    bob = User(email="bob@example.com", password_hash="x", display_name="Bob")
    db.add_all([alice, bob])
    await db.flush()
    return hh, alice, bob


# ── No context / unknown type ─────────────────────────────────────────────────

async def test_none_ref_produces_no_block(db_session):
    """The context field is optional — every pre-existing chat call still works."""
    assert await resolve_chat_context(db_session, None, None, None) == ""


async def test_missing_resource_is_silent(db_session):
    import uuid

    hh, alice, _ = await _household_with_two_users(db_session)
    ref = ChatContextRef(type="note", id=uuid.uuid4())
    assert await resolve_chat_context(db_session, alice.id, hh.id, ref) == ""


# ── Per-type formatters ───────────────────────────────────────────────────────

async def test_note_renders_title_and_body(db_session):
    hh, alice, _ = await _household_with_two_users(db_session)
    note = Note(
        household_id=hh.id,
        created_by_user_id=alice.id,
        visibility=VISIBILITY_PERSONAL,
        title="Rough week",
        content_md="I keep missing the gym and then beating myself up about it.",
    )
    db_session.add(note)
    await db_session.flush()

    out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="note", id=note.id)
    )
    assert "What the user is currently viewing" in out
    assert "Rough week" in out
    assert "beating myself up" in out


async def test_recipe_renders_ingredients_and_steps(db_session):
    """The ingredient/step relationships are lazy='noload' — these have to be
    queried explicitly or the AI gets a bare recipe name."""
    hh, alice, _ = await _household_with_two_users(db_session)
    recipe = Recipe(
        household_id=hh.id,
        created_by_user_id=alice.id,
        visibility=VISIBILITY_HOUSEHOLD,
        name="Weeknight Dan Dan Noodles",
        description="Fast, salty, mildly spicy.",
        servings=2,
        prep_time_minutes=10,
        cook_time_minutes=15,
    )
    db_session.add(recipe)
    await db_session.flush()
    db_session.add_all([
        RecipeIngredient(
            recipe_id=recipe.id, name="gochujang", quantity=Decimal("2.00"),
            unit="tbsp", sort_order=0,
        ),
        RecipeIngredient(
            recipe_id=recipe.id, name="sesame paste", quantity=Decimal("3"),
            unit="tbsp", notes="or tahini", sort_order=1,
        ),
        RecipeStep(recipe_id=recipe.id, step_number=1, instruction="Boil the noodles."),
        RecipeStep(recipe_id=recipe.id, step_number=2, instruction="Whisk the sauce."),
    ])
    await db_session.flush()

    out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="recipe", id=recipe.id)
    )
    assert "Weeknight Dan Dan Noodles" in out
    assert "Servings: 2" in out and "Prep: 10m" in out and "Cook: 15m" in out
    assert "- 2 tbsp gochujang" in out          # Decimal("2.00") → "2"
    assert "- 3 tbsp sesame paste (or tahini)" in out
    assert "1. Boil the noodles." in out
    assert "2. Whisk the sauce." in out


async def test_document_renders_title_description_and_body(db_session):
    hh, alice, _ = await _household_with_two_users(db_session)
    doc = Document(
        household_id=hh.id,
        created_by_user_id=alice.id,
        visibility=VISIBILITY_HOUSEHOLD,
        title="Move-out checklist",
        slug="move-out-checklist",
        description="Everything due before the 30th.",
        source_markdown="- Cancel the internet\n- Book the elevator",
    )
    db_session.add(doc)
    await db_session.flush()

    out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="document", id=doc.id)
    )
    assert "Move-out checklist" in out
    assert "Everything due before the 30th." in out
    assert "Book the elevator" in out


async def test_todo_goal_habit_render(db_session):
    hh, alice, _ = await _household_with_two_users(db_session)
    todo = Todo(
        household_id=hh.id, created_by_user_id=alice.id,
        visibility=VISIBILITY_HOUSEHOLD, title="Renew passport",
        status="pending", description="Photos already taken.",
    )
    goal = Goal(
        household_id=hh.id, created_by_user_id=alice.id,
        visibility=VISIBILITY_HOUSEHOLD, title="Read 24 books",
        status="active", target_value=Decimal("24"), current_value=Decimal("9"),
        unit="books",
    )
    habit = Habit(
        household_id=hh.id, created_by_user_id=alice.id,
        visibility=VISIBILITY_HOUSEHOLD, name="Morning walk",
        status="active", frequency="weekly",
        cadence={"days_of_week": [0, 2, 4]},
    )
    db_session.add_all([todo, goal, habit])
    await db_session.flush()

    todo_out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="todo", id=todo.id)
    )
    assert "Renew passport" in todo_out and "Photos already taken." in todo_out

    goal_out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="goal", id=goal.id)
    )
    assert "Read 24 books" in goal_out and "9/24 books" in goal_out

    habit_out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="habit", id=habit.id)
    )
    assert "Morning walk" in habit_out
    assert "Frequency: weekly" in habit_out
    assert "Days: Mon, Wed, Fri" in habit_out   # not a raw JSON dict
    assert "days_of_week" not in habit_out


# ── Security ──────────────────────────────────────────────────────────────────

async def test_personal_note_of_another_user_is_refused(db_session):
    """Bob passes the id of Alice's personal note. Nothing about it may leak."""
    hh, alice, bob = await _household_with_two_users(db_session)
    note = Note(
        household_id=hh.id,
        created_by_user_id=alice.id,
        visibility=VISIBILITY_PERSONAL,
        title="Therapy notes",
        content_md="Private reflections about my brother.",
    )
    db_session.add(note)
    await db_session.flush()

    ref = ChatContextRef(type="note", id=note.id)
    assert await resolve_chat_context(db_session, alice.id, hh.id, ref) != ""  # author can
    out = await resolve_chat_context(db_session, bob.id, hh.id, ref)
    assert out == ""
    assert "Therapy" not in out and "brother" not in out


async def test_personal_resources_of_another_user_are_refused_for_every_type(db_session):
    hh, alice, bob = await _household_with_two_users(db_session)
    common = dict(
        household_id=hh.id,
        created_by_user_id=alice.id,
        visibility=VISIBILITY_PERSONAL,
    )
    recipe = Recipe(name="Secret sauce", **common)
    doc = Document(title="Salary letter", slug="salary-letter", **common)
    todo = Todo(title="Call the lawyer", status="pending", **common)
    goal = Goal(title="Leave the job", status="active", **common)
    habit = Habit(name="Journaling", status="active", frequency="daily", **common)
    db_session.add_all([recipe, doc, todo, goal, habit])
    await db_session.flush()

    for ref, secret in [
        (ChatContextRef(type="recipe", id=recipe.id), "Secret sauce"),
        (ChatContextRef(type="document", id=doc.id), "Salary letter"),
        (ChatContextRef(type="todo", id=todo.id), "Call the lawyer"),
        (ChatContextRef(type="goal", id=goal.id), "Leave the job"),
        (ChatContextRef(type="habit", id=habit.id), "Journaling"),
    ]:
        assert await resolve_chat_context(db_session, alice.id, hh.id, ref) != ""
        out = await resolve_chat_context(db_session, bob.id, hh.id, ref)
        assert out == "", f"{ref.type} leaked to a non-owner"
        assert secret not in out


async def test_resource_in_another_household_is_refused(db_session):
    hh, alice, _ = await _household_with_two_users(db_session)
    other_hh = Household(name="Other")
    db_session.add(other_hh)
    await db_session.flush()
    note = Note(
        household_id=other_hh.id,
        created_by_user_id=alice.id,          # same user id, wrong household
        visibility=VISIBILITY_HOUSEHOLD,
        title="Other household note",
        content_md="Should never surface.",
    )
    db_session.add(note)
    await db_session.flush()

    out = await resolve_chat_context(
        db_session, alice.id, hh.id, ChatContextRef(type="note", id=note.id)
    )
    assert out == ""


async def test_household_shared_note_resolves_for_another_member(db_session):
    """The mirror of the security test — visibility must not be over-tight
    either. A household-visible note is readable by any member."""
    hh, alice, bob = await _household_with_two_users(db_session)
    note = Note(
        household_id=hh.id,
        created_by_user_id=alice.id,
        visibility=VISIBILITY_HOUSEHOLD,
        title="Shared reading list",
        content_md="Books we both want to get to.",
    )
    db_session.add(note)
    await db_session.flush()

    out = await resolve_chat_context(
        db_session, bob.id, hh.id, ChatContextRef(type="note", id=note.id)
    )
    assert "Shared reading list" in out
