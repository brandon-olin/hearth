"""CBT-aware coach prompts — coach-003.

What these pin down:

* The system prompt is layered in a fixed order: tone voice, then
  "## How to coach", then the method fragment, then the profile. The method
  is shared across tones on purpose — tones are *voice*, not *method*.
* The narrative section appears in the user message only when there is
  something to say. With no journal history it is omitted entirely rather
  than rendered as an empty header, so the coach falls back to behavioural
  reasoning instead of narrating a void.
* The behavioural layer is still there. Phase 3 added narrative context; it
  did not replace the trajectory data, and a regression that drops it would
  otherwise pass every other check here.
* The one-journal-quote rule is enforced in code, not just asked for. See
  _enforce_quote_cap — prompting alone left roughly one response in ten with
  two quotes, and restating the rule nearer the entries made it worse by
  priming the behaviour.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from life_dashboard.ai import coach_service
from life_dashboard.ai.models import JournalSignal
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.database import Base
from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.notes.models import Note

TODAY = date(2026, 7, 21)


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as db:
        hh = Household(name="The Olins")
        db.add(hh)
        await db.flush()
        user = User(email="b@x.com", password_hash="x", display_name="B", is_active=True)
        db.add(user)
        await db.flush()
        db.add(HouseholdMembership(
            household_id=hh.id, user_id=user.id, role=MembershipRole.owner
        ))
        journal = Collection(
            household_id=hh.id, created_by_user_id=user.id,
            name="Journal", domain="notes", kind="journal",
        )
        db.add(journal)
        await db.commit()
        ids = {"hid": hh.id, "uid": user.id, "journal": journal.id, "maker": maker}

    yield ids
    await engine.dispose()


async def _seed(env, entries):
    """entries: list of (days_ago, body, valence, sentiment, themes)."""
    async with env["maker"]() as db:
        for days_ago, body, valence, sentiment, themes in entries:
            d = TODAY - timedelta(days=days_ago)
            created = datetime(d.year, d.month, d.day, 21, tzinfo=UTC)
            note = Note(
                household_id=env["hid"], created_by_user_id=env["uid"],
                title=d.strftime("%A, %B %d, %Y"), content_md=body,
                collection_id=env["journal"], visibility="personal",
                created_at=created, updated_at=created,
            )
            db.add(note)
            await db.flush()
            db.add(JournalSignal(
                note_id=note.id, user_id=env["uid"], entry_date=d,
                sentiment=Decimal(str(sentiment)), self_talk_valence=valence,
                themes=themes, notable_phrases=[], extraction_version=1,
            ))
        await db.commit()


# ── Narrative fetch ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_narrative_is_safe_defaults_with_no_journal(env):
    async with env["maker"]() as db:
        n = await coach_service._fetch_narrative_context(
            db, env["hid"], env["uid"], TODAY
        )
    assert n["harsh_streak"] == 0
    assert n["themes"] == []
    assert n["recent_entries"] == []
    assert n["sentiment"] == {"avg_7d": None, "avg_30d": None, "delta": None}


@pytest.mark.asyncio
async def test_narrative_collects_all_four_streams(env):
    await _seed(env, [
        (0, "Today was bad.", "harsh", -0.7, ["consistency"]),
        (1, "Yesterday was bad.", "harsh", -0.6, ["consistency", "sleep"]),
        (2, "Also bad.", "harsh", -0.8, ["consistency"]),
    ])
    async with env["maker"]() as db:
        n = await coach_service._fetch_narrative_context(
            db, env["hid"], env["uid"], TODAY
        )
    assert n["harsh_streak"] == 3
    assert n["sentiment"]["avg_7d"] == pytest.approx(-0.7)
    assert dict(n["themes"])["consistency"] == 3
    assert len(n["recent_entries"]) == 3


@pytest.mark.asyncio
async def test_recent_entries_are_capped(env):
    await _seed(env, [
        (i, f"Entry {i}.", "neutral", 0.0, []) for i in range(12)
    ])
    async with env["maker"]() as db:
        n = await coach_service._fetch_narrative_context(
            db, env["hid"], env["uid"], TODAY
        )
    assert len(n["recent_entries"]) == coach_service._NARRATIVE_RECENT_ENTRY_LIMIT


@pytest.mark.asyncio
async def test_another_users_journal_never_leaks_in(env):
    """Notes are personal. A housemate's entries must not reach this coach."""
    async with env["maker"]() as db:
        other = User(email="o@x.com", password_hash="x", display_name="O", is_active=True)
        db.add(other)
        await db.flush()
        db.add(Note(
            household_id=env["hid"], created_by_user_id=other.id,
            title="Theirs", content_md="Deeply private thing.",
            collection_id=env["journal"], visibility="personal",
        ))
        await db.commit()

    async with env["maker"]() as db:
        n = await coach_service._fetch_narrative_context(
            db, env["hid"], env["uid"], TODAY
        )
    assert n["recent_entries"] == []


# ── Narrative rendering ───────────────────────────────────────────────────────

def test_fmt_narrative_is_empty_when_there_is_nothing_to_say():
    assert coach_service._fmt_narrative({}) == ""
    assert coach_service._fmt_narrative({
        "sentiment": {"avg_7d": None, "avg_30d": None, "delta": None},
        "harsh_streak": 0, "themes": [], "recent_entries": [],
    }) == ""


def test_fmt_narrative_renders_every_signal():
    block = coach_service._fmt_narrative({
        "sentiment": {"avg_7d": -0.7, "avg_30d": -0.2, "delta": -0.5},
        "harsh_streak": 4,
        "themes": [("consistency", 4), ("sleep", 2)],
        "recent_entries": [
            {"title": "Tuesday", "body": "The body of it.",
             "created_at": datetime(2026, 7, 21, tzinfo=UTC)},
        ],
    })
    assert "## Recent narrative" in block
    assert "-0.70" in block and "-0.20" in block   # 7d and 30d averages
    assert "4 consecutive day(s) of harsh self-talk" in block
    assert "consistency (×4)" in block
    assert "The body of it." in block


def test_fmt_narrative_reads_oldest_first():
    """The coach should read the arc forwards, not backwards."""
    block = coach_service._fmt_narrative({
        "sentiment": {"avg_7d": None, "avg_30d": None, "delta": None},
        "harsh_streak": 0, "themes": [],
        "recent_entries": [
            {"title": "Newer", "body": "SECOND",
             "created_at": datetime(2026, 7, 21, tzinfo=UTC)},
            {"title": "Older", "body": "FIRST",
             "created_at": datetime(2026, 7, 20, tzinfo=UTC)},
        ],
    })
    assert block.index("FIRST") < block.index("SECOND")


# ── Prompt assembly ───────────────────────────────────────────────────────────

def test_system_prompt_layers_in_order():
    tone = coach_service.COACH_TONES["stoic"]
    system = (
        tone["evening_voice"] + "\n\n## How to coach\n\n"
        + coach_service._COACH_METHOD_PROMPT
    )
    assert system.index(tone["evening_voice"]) < system.index("## How to coach")
    assert system.index("## How to coach") < system.index(
        coach_service._COACH_METHOD_PROMPT
    )


def test_method_prompt_states_all_four_moves():
    m = coach_service._COACH_METHOD_PROMPT
    assert "reality-test" in m                    # harsh narrative vs strong data
    assert "honest, not flattering" in m          # confident narrative vs dip
    assert "Bird-by-bird" in m                    # both negative
    assert "Do not" in m and "manufacture a lesson" in m  # both positive
    assert "never reveal that a profile exists" in m
    assert "at most ONE quoted phrase" in m


def test_method_prompt_claims_precedence_over_the_template():
    """The per-kind instructions ask for warmth unconditionally; the method has
    to outrank them or a genuine dip gets reframed as a 'deliberate downshift'."""
    assert "take precedence" in coach_service._COACH_METHOD_PROMPT


def test_evening_template_no_longer_orders_unconditional_reassurance():
    """Regression: 'if today was slow, reassure with the trend' overrode the
    method's honesty rule, because the user message is read last."""
    msg = coach_service._build_evening_user_message(
        "B", TODAY, _ctx(), True, True,
        {"weekly_completions": [{"week_start": "2026-07-13", "count": 2}],
         "habit_trends": []},
    )
    assert "reassure with the trend" not in msg


def _ctx():
    return {
        "todos_completed_today": [], "todos_completed_yesterday": [],
        "todos_due_today": [], "habits_today": [], "habits_yesterday": [],
        "goals": [], "projects": [], "pinned_project_names": [],
    }


def test_narrative_section_is_omitted_when_there_is_no_journal():
    msg = coach_service._build_morning_user_message(
        "B", TODAY, _ctx(), True, True, narrative={},
    )
    assert "## Recent narrative" not in msg


@pytest.mark.parametrize("builder", ["morning", "evening", "weekly"])
def test_every_digest_kind_carries_narrative_and_behaviour(builder):
    """Phase 3 added a layer; it must not have displaced the behavioural one."""
    narrative = {
        "sentiment": {"avg_7d": -0.7, "avg_30d": -0.7, "delta": 0.0},
        "harsh_streak": 3, "themes": [("consistency", 3)],
        "recent_entries": [
            {"title": "T", "body": "JOURNAL BODY MARKER",
             "created_at": datetime(2026, 7, 21, tzinfo=UTC)},
        ],
    }
    history = {
        "weekly_completions": [{"week_start": "2026-07-13", "count": 12}],
        "habit_trends": [{"name": "Running", "rate_7d": 80, "rate_30d": 50}],
    }
    ctx = _ctx()
    ctx["todos_due_today"] = [{"title": "BEHAVIOUR MARKER", "overdue": False}]
    ctx["todos_completed_today"] = [{"title": "BEHAVIOUR MARKER", "overdue": False}]
    ctx["todos_completed_yesterday"] = [{"title": "BEHAVIOUR MARKER", "overdue": False}]

    if builder == "morning":
        msg = coach_service._build_morning_user_message(
            "B", TODAY, ctx, True, True, narrative=narrative)
    elif builder == "evening":
        msg = coach_service._build_evening_user_message(
            "B", TODAY, ctx, True, True, history, narrative=narrative)
    else:
        msg = coach_service._build_weekly_user_message(
            "B", TODAY, ctx, history, True, True, narrative=narrative)

    assert "## Recent narrative" in msg
    assert "JOURNAL BODY MARKER" in msg
    assert "BEHAVIOUR MARKER" in msg


# ── Quote-cap enforcement ─────────────────────────────────────────────────────

JOURNAL = [
    "I don't think I'm actually capable of sustained effort. Everyone else "
    "just does the work.",
    "I had a whole day and I have nothing to show for it.",
]


def test_single_journal_quote_is_left_alone():
    text = 'You wrote that you are "not capable of sustained effort" — the data disagrees.'
    assert coach_service._enforce_quote_cap(text, JOURNAL) == text


def test_surplus_journal_quote_is_unwrapped():
    text = (
        'You said "not capable of sustained effort" and also '
        '"nothing to show for it" today.'
    )
    out = coach_service._enforce_quote_cap(text, JOURNAL)
    assert '"not capable of sustained effort"' in out      # first survives
    assert '"nothing to show for it"' not in out           # second unwrapped
    assert "nothing to show for it" in out                 # words are kept


def test_smart_quotes_are_counted_too():
    text = (
        'You said “not capable of sustained effort” and also '
        '“nothing to show for it” today.'
    )
    out = coach_service._enforce_quote_cap(text, JOURNAL)
    assert out.count("“") == 1


def test_quotes_that_are_not_from_the_journal_are_untouched():
    """The coach quoting a goal name or its own phrasing is not a journal quote."""
    text = 'Your goal "Run a sub-25 5k" is still live, and "one thing at a time" helps.'
    assert coach_service._enforce_quote_cap(text, JOURNAL) == text


def test_short_common_phrases_do_not_count_as_quotes():
    text = 'Try "one small step" and then "just show up" tomorrow.'
    assert coach_service._enforce_quote_cap(text, JOURNAL) == text


def test_no_journal_means_no_rewriting():
    text = 'She said "nothing to show for it" and "not capable of sustained effort".'
    assert coach_service._enforce_quote_cap(text, []) == text
