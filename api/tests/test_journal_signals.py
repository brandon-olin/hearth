"""Journal signal extraction — coach-002.

The things these tests actually pin down, because they are the ones that were
either broken or easy to break:

* Extraction is **gated three ways** — journal-kind collection, the per-user
  flag, and a configured provider. Any one of them off means no extraction,
  and the note still saves.
* A re-save **updates** the note's row. One row per note, forever. A second
  row would silently double-weight that day in every trend helper.
* A provider that errors, times out, or returns prose instead of JSON must
  never fail the note write. The whole feature is a side-effect.
* Deleting a note removes its signal. The FK cascade only fires on Postgres
  (SQLite does not enforce foreign keys without PRAGMA foreign_keys, which is
  not set) and no ORM relationship covers it, so the service does it. Without
  this, a deleted entry keeps feeding the coach's trend math.

Notes are created through the real notes service rather than by inserting ORM
rows, because the save-time hook is the thing under test.
"""
import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.core.database as database_module
from life_dashboard.ai import journal_signal_service as jss
from life_dashboard.ai.models import AiProvider, AiSettings, JournalSignal
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.database import Base
from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.notes import service as notes_service
from life_dashboard.domains.notes.models import Note
from life_dashboard.domains.notes.schemas import NoteCreate, NoteUpdate

GOOD_JSON = """{
  "sentiment": -0.62,
  "self_talk_valence": "harsh",
  "themes": ["consistency", "work stress"],
  "notable_phrases": ["I keep losing the thread"],
  "energy_level": "low"
}"""


class FakeProvider:
    """Scripted stand-in for AnthropicProvider.

    Responses are consumed one per call; the last repeats. `raises` makes every
    call fail, which is how the "provider is broken" cases are driven.
    """

    def __init__(self, responses=None, *, raises=None):
        self.responses = list(responses or [GOOD_JSON])
        self.raises = raises
        self.calls: list[dict] = []

    async def complete(self, messages, system, *, max_tokens=1024):
        if self.raises is not None:
            raise self.raises
        self.calls.append({"system": system, "user": messages[0]["content"]})
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return text, 10, 20, "fake-model"

    async def validate(self):
        return True, None

    def stream_chat(self, messages, system, *, tools=None, max_tokens=4096):
        raise NotImplementedError


@pytest_asyncio.fixture
async def env(monkeypatch):
    """Household with a journal collection, a plain collection, and AI settings.

    AsyncSessionLocal is pointed at the same in-memory engine so the background
    extraction task writes where the assertions read.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", maker)

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
        plain = Collection(
            household_id=hh.id, created_by_user_id=user.id,
            name="Ideas", domain="notes",
        )
        db.add_all([journal, plain])
        db.add(AiSettings(
            user_id=user.id, provider=AiProvider.anthropic,
            api_key_encrypted="sk-test", ai_journal_extraction_enabled=True,
        ))
        await db.commit()
        ids = {
            "hid": hh.id, "uid": user.id,
            "journal": journal.id, "plain": plain.id, "maker": maker,
        }

    yield ids
    await engine.dispose()


async def _signals(maker, note_id=None):
    async with maker() as db:
        q = select(JournalSignal)
        if note_id is not None:
            q = q.where(JournalSignal.note_id == note_id)
        return list((await db.execute(q)).scalars().all())


# ── Extraction core ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_persists_coerced_fields(env):
    maker = env["maker"]
    provider = FakeProvider()
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="Tuesday, May 26, 2026", content_md="A real entry with words.",
            collection_id=env["journal"], visibility="personal",
            created_at=datetime(2026, 5, 26, 9, tzinfo=UTC),
        )
        db.add(note)
        await db.flush()
        sig = await jss.extract_signals_for_note(db, provider, note, env["uid"])
        await db.commit()

    assert sig is not None
    assert sig.sentiment == Decimal("-0.62")
    assert sig.self_talk_valence == "harsh"
    assert sig.themes == ["consistency", "work stress"]
    assert sig.energy_level == "low"
    assert sig.extraction_version == jss.EXTRACTION_VERSION
    # entry_date comes from the title, not the created_at, when it parses.
    assert sig.entry_date == date(2026, 5, 26)


@pytest.mark.asyncio
async def test_re_extraction_updates_the_same_row(env):
    """A second save must not add a second row — it would double-weight the day."""
    maker = env["maker"]
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="Entry", content_md="First version.",
            collection_id=env["journal"], visibility="personal",
        )
        db.add(note)
        await db.flush()
        await jss.extract_signals_for_note(db, FakeProvider(), note, env["uid"])
        await db.commit()
        note_id = note.id

        second = '{"sentiment": 0.5, "self_talk_valence": "positive", ' \
                 '"themes": ["rest"], "notable_phrases": [], "energy_level": "high"}'
        note.content_md = "Second version."
        await jss.extract_signals_for_note(db, FakeProvider([second]), note, env["uid"])
        await db.commit()

    rows = await _signals(maker, note_id)
    assert len(rows) == 1
    assert rows[0].sentiment == Decimal("0.50")
    assert rows[0].self_talk_valence == "positive"


@pytest.mark.asyncio
async def test_empty_body_extracts_nothing(env):
    maker = env["maker"]
    provider = FakeProvider()
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="Blank", content_md="   ",
            collection_id=env["journal"], visibility="personal",
        )
        db.add(note)
        await db.flush()
        assert await jss.extract_signals_for_note(db, provider, note, env["uid"]) is None
    assert provider.calls == []  # never even asked the model


@pytest.mark.parametrize(
    "payload,field,expected",
    [
        ('{"sentiment": 9.9, "self_talk_valence": "harsh"}', "sentiment", Decimal("1.00")),
        ('{"sentiment": -9.9, "self_talk_valence": "harsh"}', "sentiment", Decimal("-1.00")),
        ('{"sentiment": "banana"}', "sentiment", Decimal("0.00")),
        ('{"sentiment": 0, "self_talk_valence": "furious"}', "self_talk_valence", "neutral"),
        ('{"sentiment": 0, "energy_level": "cosmic"}', "energy_level", None),
        ('{"sentiment": 0, "themes": "not a list"}', "themes", []),
    ],
)
@pytest.mark.asyncio
async def test_malformed_model_output_is_coerced_not_stored_raw(env, payload, field, expected):
    """The model is not trusted. Out-of-range and junk values get clamped."""
    maker = env["maker"]
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="E", content_md="body", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        sig = await jss.extract_signals_for_note(
            db, FakeProvider([payload]), note, env["uid"]
        )
    assert sig is not None
    assert getattr(sig, field) == expected


@pytest.mark.asyncio
async def test_non_json_response_is_swallowed(env):
    maker = env["maker"]
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="E", content_md="body", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        sig = await jss.extract_signals_for_note(
            db, FakeProvider(["I'm sorry, I can't help with that."]), note, env["uid"]
        )
    assert sig is None


@pytest.mark.asyncio
async def test_fenced_json_is_parsed(env):
    """The prompt forbids code fences; the parser tolerates them anyway."""
    maker = env["maker"]
    fenced = "```json\n" + GOOD_JSON + "\n```"
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="E", content_md="body", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        sig = await jss.extract_signals_for_note(
            db, FakeProvider([fenced]), note, env["uid"]
        )
    assert sig is not None and sig.self_talk_valence == "harsh"


@pytest.mark.asyncio
async def test_provider_raising_does_not_propagate(env):
    maker = env["maker"]
    async with maker() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="E", content_md="body", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        sig = await jss.extract_signals_for_note(
            db, FakeProvider(raises=RuntimeError("upstream 500")), note, env["uid"]
        )
    assert sig is None


# ── Save-time gating ──────────────────────────────────────────────────────────

def _spy_background(monkeypatch):
    """Record calls to the detached extraction task without running it.

    Patches the background coroutine rather than asyncio.create_task, because
    `jss.asyncio` is the shared asyncio module — patching create_task through
    it breaks pytest-asyncio's own scheduling.
    """
    spawned: list[uuid.UUID] = []

    async def fake(note_id, user_id, household_id):
        spawned.append(note_id)

    monkeypatch.setattr(jss, "_run_extraction_background", fake)
    return spawned


@pytest.mark.asyncio
async def test_note_in_non_journal_collection_is_not_queued(env, monkeypatch):
    """The kind='journal' gate is checked before any task is spawned."""
    spawned = _spy_background(monkeypatch)

    async with env["maker"]() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="Idea", content_md="Some idea.", collection_id=env["plain"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        await jss.maybe_extract_signals(db, note, env["uid"], env["hid"])
    await asyncio.sleep(0)
    assert spawned == []


@pytest.mark.asyncio
async def test_flag_off_is_not_queued(env, monkeypatch):
    spawned = _spy_background(monkeypatch)

    async with env["maker"]() as db:
        settings = (await db.execute(
            select(AiSettings).where(AiSettings.user_id == env["uid"])
        )).scalar_one()
        settings.ai_journal_extraction_enabled = False
        await db.commit()

        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="Entry", content_md="Body.", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        await jss.maybe_extract_signals(db, note, env["uid"], env["hid"])
    await asyncio.sleep(0)
    assert spawned == []


@pytest.mark.asyncio
async def test_journal_note_is_queued(env, monkeypatch):
    """The positive case — proves the three gates aren't blocking everything."""
    spawned = _spy_background(monkeypatch)

    async with env["maker"]() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title="Entry", content_md="Body.", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        await jss.maybe_extract_signals(db, note, env["uid"], env["hid"])
        note_id = note.id
    await asyncio.sleep(0)
    assert spawned == [note_id]


@pytest.mark.asyncio
async def test_note_save_survives_a_hook_that_explodes(env, monkeypatch):
    """Extraction is a side-effect. A failure in it must not fail the write."""
    async def boom(*a, **kw):
        raise RuntimeError("hook is broken")

    monkeypatch.setattr(jss, "maybe_extract_signals", boom)

    async with env["maker"]() as db:
        resp = await notes_service.create_note(
            db, household_id=env["hid"], user_id=env["uid"],
            data=NoteCreate(
                title="Entry", content_md="This must persist.",
                collection_id=env["journal"],
            ),
        )
    assert resp.content_md == "This must persist."
    async with env["maker"]() as db:
        stored = (await db.execute(
            select(Note).where(Note.id == resp.id)
        )).scalar_one()
        assert stored.content_md == "This must persist."


@pytest.mark.asyncio
async def test_title_only_update_does_not_re_extract(env, monkeypatch):
    """Re-running the model on a title change burns tokens for nothing."""
    calls = []
    async def spy(db, note, user_id, household_id):
        calls.append(note.id)
    monkeypatch.setattr(jss, "maybe_extract_signals", spy)

    async with env["maker"]() as db:
        resp = await notes_service.create_note(
            db, household_id=env["hid"], user_id=env["uid"],
            data=NoteCreate(
                title="Old title", content_md="Body.", collection_id=env["journal"]
            ),
        )
    calls.clear()

    async with env["maker"]() as db:
        await notes_service.update_note(
            db, note_id=resp.id, household_id=env["hid"],
            data=NoteUpdate(title="New title"),
        )
    assert calls == []

    async with env["maker"]() as db:
        await notes_service.update_note(
            db, note_id=resp.id, household_id=env["hid"],
            data=NoteUpdate(content_md="Rewritten body."),
        )
    assert calls == [resp.id]


# ── Deletion ──────────────────────────────────────────────────────────────────

async def _note_with_signal(env, title="Entry"):
    async with env["maker"]() as db:
        note = Note(
            household_id=env["hid"], created_by_user_id=env["uid"],
            title=title, content_md="Body.", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        await jss.extract_signals_for_note(db, FakeProvider(), note, env["uid"])
        await db.commit()
        return note.id


@pytest.mark.asyncio
async def test_deleting_a_note_removes_its_signal(env):
    """SQLite does not enforce the FK cascade, so the service must."""
    note_id = await _note_with_signal(env)
    assert len(await _signals(env["maker"], note_id)) == 1

    async with env["maker"]() as db:
        assert await notes_service.delete_note(
            db, note_id=note_id, household_id=env["hid"]
        )
    assert await _signals(env["maker"], note_id) == []


@pytest.mark.asyncio
async def test_household_wipe_removes_every_signal(env):
    """delete_all_notes is a bulk Core DELETE — it bypasses ORM cascade too."""
    await _note_with_signal(env, "One")
    await _note_with_signal(env, "Two")
    assert len(await _signals(env["maker"])) == 2

    async with env["maker"]() as db:
        await notes_service.delete_all_notes(db, household_id=env["hid"])
    assert await _signals(env["maker"]) == []


@pytest.mark.asyncio
async def test_delete_helper_is_scoped_to_the_household(env):
    """A wipe in one household must not touch another's signals."""
    async with env["maker"]() as db:
        other_hh = Household(name="Neighbours")
        db.add(other_hh)
        await db.flush()
        other_col = Collection(
            household_id=other_hh.id, created_by_user_id=env["uid"],
            name="Journal", domain="notes", kind="journal",
        )
        db.add(other_col)
        await db.flush()
        note = Note(
            household_id=other_hh.id, created_by_user_id=env["uid"],
            title="Theirs", content_md="Body.", collection_id=other_col.id,
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        await jss.extract_signals_for_note(db, FakeProvider(), note, env["uid"])
        await db.commit()
        foreign_note_id = note.id

    await _note_with_signal(env, "Ours")

    async with env["maker"]() as db:
        await notes_service.delete_all_notes(db, household_id=env["hid"])

    remaining = await _signals(env["maker"])
    assert [r.note_id for r in remaining] == [foreign_note_id]


@pytest.mark.asyncio
async def test_delete_signals_for_notes_is_a_noop_on_empty_input(env):
    async with env["maker"]() as db:
        assert await jss.delete_signals_for_notes(db, []) == 0


# ── Trend helpers ─────────────────────────────────────────────────────────────

async def _seed_signals(env, rows):
    """rows: list of (days_ago, sentiment, valence, themes)."""
    today = date(2026, 7, 21)
    async with env["maker"]() as db:
        for days_ago, sentiment, valence, themes in rows:
            note = Note(
                household_id=env["hid"], created_by_user_id=env["uid"],
                title=f"E{days_ago}", content_md="Body.",
                collection_id=env["journal"], visibility="personal",
            )
            db.add(note)
            await db.flush()
            db.add(JournalSignal(
                note_id=note.id, user_id=env["uid"],
                entry_date=today - timedelta(days=days_ago),
                sentiment=Decimal(str(sentiment)), self_talk_valence=valence,
                themes=themes, notable_phrases=[], extraction_version=1,
            ))
        await db.commit()
    return today


@pytest.mark.asyncio
async def test_sentiment_trend_splits_7d_from_30d(env):
    today = await _seed_signals(env, [
        (1, -0.5, "harsh", []), (2, -0.5, "harsh", []),   # inside 7d
        (20, 0.5, "positive", []), (25, 0.5, "positive", []),  # 30d only
    ])
    async with env["maker"]() as db:
        trend = await jss.sentiment_trend(db, env["uid"], today)
    assert trend["avg_7d"] == pytest.approx(-0.5)
    assert trend["avg_30d"] == pytest.approx(0.0)
    assert trend["delta"] == pytest.approx(-0.5)


@pytest.mark.asyncio
async def test_sentiment_trend_with_no_entries_is_all_none(env):
    async with env["maker"]() as db:
        trend = await jss.sentiment_trend(db, env["uid"], date(2026, 7, 21))
    assert trend == {"avg_7d": None, "avg_30d": None, "delta": None}


@pytest.mark.asyncio
async def test_harsh_streak_counts_consecutive_days(env):
    today = await _seed_signals(env, [
        (0, -0.7, "harsh", []), (1, -0.7, "harsh", []), (2, -0.7, "harsh", []),
    ])
    async with env["maker"]() as db:
        assert await jss.harsh_self_talk_streak(db, env["uid"], today) == 3


@pytest.mark.asyncio
async def test_a_missing_day_breaks_the_harsh_streak(env):
    """No entry is not a harsh entry — the run has to be unbroken."""
    today = await _seed_signals(env, [
        (0, -0.7, "harsh", []), (1, -0.7, "harsh", []),
        (3, -0.7, "harsh", []),  # day 2 missing
    ])
    async with env["maker"]() as db:
        assert await jss.harsh_self_talk_streak(db, env["uid"], today) == 2


@pytest.mark.asyncio
async def test_a_non_harsh_day_breaks_the_harsh_streak(env):
    today = await _seed_signals(env, [
        (0, -0.7, "harsh", []), (1, 0.4, "neutral", []), (2, -0.7, "harsh", []),
    ])
    async with env["maker"]() as db:
        assert await jss.harsh_self_talk_streak(db, env["uid"], today) == 1


@pytest.mark.asyncio
async def test_dominant_themes_are_counted_and_ranked(env):
    today = await _seed_signals(env, [
        (1, 0.0, "neutral", ["sleep", "work"]),
        (2, 0.0, "neutral", ["work", "money"]),
        (3, 0.0, "neutral", ["Work"]),          # case-folded into "work"
        (40, 0.0, "neutral", ["ancient"]),      # outside the 14-day window
    ])
    async with env["maker"]() as db:
        themes = await jss.dominant_themes_recent(db, env["uid"], today)
    assert themes[0] == ("work", 3)
    assert "ancient" not in dict(themes)


@pytest.mark.asyncio
async def test_trend_helpers_are_scoped_to_one_user(env):
    """Another member's journal must never reach this user's trend math."""
    async with env["maker"]() as db:
        other = User(email="o@x.com", password_hash="x", display_name="O", is_active=True)
        db.add(other)
        await db.flush()
        note = Note(
            household_id=env["hid"], created_by_user_id=other.id,
            title="Theirs", content_md="Body.", collection_id=env["journal"],
            visibility="personal",
        )
        db.add(note)
        await db.flush()
        db.add(JournalSignal(
            note_id=note.id, user_id=other.id, entry_date=date(2026, 7, 21),
            sentiment=Decimal("-1.00"), self_talk_valence="harsh",
            themes=["theirs"], notable_phrases=[], extraction_version=1,
        ))
        await db.commit()

    async with env["maker"]() as db:
        assert await jss.harsh_self_talk_streak(db, env["uid"], date(2026, 7, 21)) == 0
        assert await jss.dominant_themes_recent(db, env["uid"], date(2026, 7, 21)) == []
        assert (await jss.sentiment_trend(db, env["uid"], date(2026, 7, 21)))["avg_30d"] is None
