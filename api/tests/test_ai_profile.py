"""AI profile: bootstrap, incremental proposer, and key validation.

Covers coach-001 (bootstrap pass), coach-001b (notes-driven incremental
proposer), and coach-005 (silent profile + auto-bootstrap on key save + key
validation) as the single end state they landed as.

The three things worth stating up front, because they are what the tests are
really pinning down:

* The profile is written **directly** to member_ai_memory.memory_text. There
  is no pending/accept/reject queue any more — the rows in
  user_profile_updates are an audit log inserted with status='accepted'.
* The incremental proposer's counter advances **even when the model says
  SKIP**, so a user can never buy more than one proposer call per N notes.
* An API key is validated **before** it is persisted. A rejected key must
  leave the stored key exactly as it was.

Every HTTP endpoint touched here is called through the ASGI app rather than
imported, because a route that is registered but never exercised is how a
broken endpoint shipped last time.
"""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.ai.profile_service as profile_service
import life_dashboard.ai.router as ai_router
import life_dashboard.core.database as database_module
from life_dashboard.ai.models import (
    AiProvider,
    AiSettings,
    MemberAiMemory,
    UserProfileUpdate,
)
from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.database import Base, get_db
from life_dashboard.domains.goals.models import Goal
from life_dashboard.domains.habits.models import Habit
from life_dashboard.domains.notes import service as notes_service
from life_dashboard.domains.notes.schemas import NoteCreate, NoteUpdate
from life_dashboard.domains.todos.models import Todo
from life_dashboard.main import app

DRAFTED_PROFILE = """## Current focuses
Rebuilding the back deck and shipping the household dashboard.

## What works for me
Short sessions in the morning, before the house wakes up.
"""


class FakeProvider:
    """Stands in for AnthropicProvider.

    `responses` is consumed one per complete() call; the last one repeats so a
    test that does not care how many calls happen does not have to script them
    all. Every prompt is recorded so tests can assert what the proposer was
    actually shown.
    """

    def __init__(self, responses=None, *, valid=True, error=None, raises=None):
        self.responses = list(responses or [DRAFTED_PROFILE])
        self.valid = valid
        self.error = error
        self.raises = raises
        self.calls: list[dict] = []
        self.validate_calls = 0

    async def complete(self, messages, system, *, max_tokens=1024):
        if self.raises is not None:
            raise self.raises
        self.calls.append({"system": system, "user": messages[0]["content"]})
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return text, 10, 20, "fake-model"

    async def validate(self):
        self.validate_calls += 1
        return (True, None) if self.valid else (False, self.error or "Invalid API key.")

    def stream_chat(self, messages, system, *, tools=None, max_tokens=4096):
        raise NotImplementedError


@pytest_asyncio.fixture
async def api(monkeypatch):
    """ASGI client + a seeded household, on a session factory the background
    tasks share.

    The proposer and the auto-bootstrap both open their *own* session via
    core.database.AsyncSessionLocal, so that factory is pointed at the same
    in-memory engine — otherwise a background task would write to a different
    database than the one the assertions read.
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
        user = User(
            email="brandon@x.com", password_hash="x", display_name="Brandon", is_active=True
        )
        db.add(user)
        await db.flush()
        db.add(
            HouseholdMembership(
                household_id=hh.id, user_id=user.id, role=MembershipRole.owner
            )
        )
        await db.commit()

    user.household_id = hh.id
    user.household_name = hh.name
    user.role = MembershipRole.owner.value

    async def _override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield {"client": client, "maker": maker, "hid": hh.id, "uid": user.id}

    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_source_material(maker, hid, uid):
    """Notes, a goal, a habit, and a completed todo — one of each source the
    bootstrap pass is specified to read."""
    async with maker() as db:
        db.add(
            Goal(
                household_id=hid,
                created_by_user_id=uid,
                title="Run a sub-25 5k",
                status="active",
            )
        )
        db.add(
            Habit(
                household_id=hid,
                created_by_user_id=uid,
                name="Morning pages",
                frequency="daily",
                status="active",
            )
        )
        db.add(
            Todo(
                household_id=hid,
                created_by_user_id=uid,
                assigned_to_user_id=uid,
                title="Sand the deck boards",
                status="done",
                completed_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
        await db.commit()
        await notes_service.create_note(
            db,
            hid,
            uid,
            NoteCreate(
                title="Deck rebuild log",
                content_md="Pulled the old boards today. Slow going but satisfying.",
            ),
        )


async def _memory(maker, uid) -> MemberAiMemory:
    async with maker() as db:
        return (
            await db.execute(select(MemberAiMemory).where(MemberAiMemory.user_id == uid))
        ).scalar_one()


async def _settings_row(maker, uid) -> AiSettings:
    async with maker() as db:
        return (
            await db.execute(select(AiSettings).where(AiSettings.user_id == uid))
        ).scalar_one_or_none()


async def _drain_background_tasks():
    """Let fire-and-forget asyncio tasks spawned during a request finish.

    The proposer and the auto-bootstrap are both detached tasks by design (a
    note save must not wait on an AI call), so tests have to yield to the loop
    before asserting on what they wrote.
    """
    for _ in range(10):
        pending = [
            t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
        ]
        if not pending:
            return
        await asyncio.wait(pending, timeout=5)


# ── coach-001: bootstrap pass ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_writes_profile_directly_and_stamps_timestamp(api, monkeypatch):
    """POST /ai/profile/bootstrap applies the draft itself — no review step."""
    await _seed_source_material(api["maker"], api["hid"], api["uid"])
    fake = FakeProvider()
    monkeypatch.setattr(ai_router.service, "get_provider", lambda s: fake)

    resp = await api["client"].post("/ai/profile/bootstrap")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bootstrap_skipped"] is False
    assert body["update"]["source"] == "bootstrap"
    # The audit row is inserted already-resolved; there is no queue to drain.
    assert body["update"]["status"] == "accepted"

    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == DRAFTED_PROFILE.strip()
    assert memory.last_bootstrapped_at is not None

    # And nothing is left pending for a UI that no longer exists.
    async with api["maker"]() as db:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(UserProfileUpdate)
                .where(UserProfileUpdate.status == "pending")
            )
        ).scalar_one()
    assert pending == 0


@pytest.mark.asyncio
async def test_bootstrap_prompt_includes_every_declared_source(api, monkeypatch):
    """Notes, goals, habits and the 90-day completed-todo window all reach the
    model — a bootstrap that silently read only notes would still look fine
    from the outside."""
    await _seed_source_material(api["maker"], api["hid"], api["uid"])
    fake = FakeProvider()
    monkeypatch.setattr(ai_router.service, "get_provider", lambda s: fake)

    await api["client"].post("/ai/profile/bootstrap")

    prompt = fake.calls[0]["user"]
    assert "Deck rebuild log" in prompt
    assert "Pulled the old boards today" in prompt
    assert "Run a sub-25 5k" in prompt
    assert "Morning pages" in prompt
    assert "Sand the deck boards" in prompt


@pytest.mark.asyncio
async def test_bootstrap_with_no_source_material_skips_but_still_stamps(api, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(ai_router.service, "get_provider", lambda s: fake)

    resp = await api["client"].post("/ai/profile/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bootstrap_skipped"] is True
    assert body["update"] is None
    assert fake.calls == []  # no data → no reason to spend a call

    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == ""
    # Stamped anyway: bootstrap *ran*, it just had nothing to work with.
    assert memory.last_bootstrapped_at is not None


@pytest.mark.asyncio
async def test_bootstrap_returns_503_without_a_provider(api, monkeypatch):
    monkeypatch.setattr(ai_router.service, "get_provider", lambda s: None)
    resp = await api["client"].post("/ai/profile/bootstrap")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_profile_is_readable_and_directly_editable_for_debugging(api):
    """The /ai/profile endpoints stay behind the UI removal — they are the
    only way to inspect or repair a profile now."""
    resp = await api["client"].get("/ai/profile")
    assert resp.status_code == 200
    assert resp.json()["content_md"] == ""

    resp = await api["client"].patch("/ai/profile", json={"content_md": "## Current focuses\nX"})
    assert resp.status_code == 200
    assert resp.json()["content_md"] == "## Current focuses\nX"

    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == "## Current focuses\nX"


@pytest.mark.asyncio
async def test_profile_is_injected_into_the_coach_prompt(api):
    """The coach reads the profile through this fragment; an empty profile
    contributes nothing rather than an empty header."""
    async with api["maker"]() as db:
        assert await profile_service.load_profile_context(db, api["uid"]) == ""

    await api["client"].patch("/ai/profile", json={"content_md": DRAFTED_PROFILE})

    async with api["maker"]() as db:
        fragment = await profile_service.load_profile_context(db, api["uid"])
    assert "What you know about this person" in fragment
    assert "Rebuilding the back deck" in fragment
    assert "name-drop" in fragment  # the do-not-mention-the-profile instruction


@pytest.mark.asyncio
async def test_chat_picks_up_the_profile_with_no_code_of_its_own(api):
    """The chatbot was already reading memory_text, so writing the profile
    there is what makes chat benefit for free. This pins that down: nothing
    in the chat path knows the word 'profile'."""
    from life_dashboard.ai import service as ai_service
    from life_dashboard.ai.models import AiConversation

    await api["client"].patch("/ai/profile", json={"content_md": DRAFTED_PROFILE})

    async with api["maker"]() as db:
        conv = AiConversation(user_id=api["uid"], household_id=api["hid"], title="t")
        db.add(conv)
        await db.commit()

        user = (await db.execute(select(User).where(User.id == api["uid"]))).scalar_one()
        memory = await ai_service.get_or_create_memory(db, api["uid"])
        system, _messages = await ai_service.build_chat_context(db, conv.id, user, memory)

    assert "Rebuilding the back deck" in system


# ── coach-005: key validation + auto-bootstrap ────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_api_key_returns_400_and_is_never_persisted(api, monkeypatch):
    rejecting = FakeProvider(valid=False, error="Invalid API key — Anthropic rejected it.")
    monkeypatch.setattr(ai_router, "AnthropicProvider", None, raising=False)
    monkeypatch.setattr(
        "life_dashboard.ai.provider.AnthropicProvider", lambda key: rejecting
    )

    resp = await api["client"].patch("/ai/settings", json={"api_key": "sk-ant-bogus"})
    assert resp.status_code == 400, resp.text
    assert "Invalid API key" in resp.json()["detail"]
    assert rejecting.validate_calls == 1

    row = await _settings_row(api["maker"], api["uid"])
    assert row is None or row.api_key_encrypted is None


@pytest.mark.asyncio
async def test_invalid_key_does_not_clobber_an_already_good_key(api, monkeypatch):
    """The dangerous version of the previous test: a user with a working key
    who fat-fingers a new one must keep the working one."""
    async with api["maker"]() as db:
        db.add(
            AiSettings(
                user_id=api["uid"],
                provider=AiProvider.anthropic,
                api_key_encrypted="sk-ant-good",
            )
        )
        await db.commit()

    rejecting = FakeProvider(valid=False, error="Invalid API key.")
    monkeypatch.setattr(
        "life_dashboard.ai.provider.AnthropicProvider", lambda key: rejecting
    )

    resp = await api["client"].patch("/ai/settings", json={"api_key": "sk-ant-typo"})
    assert resp.status_code == 400

    row = await _settings_row(api["maker"], api["uid"])
    assert row.api_key_encrypted == "sk-ant-good"


@pytest.mark.asyncio
async def test_valid_key_persists_and_auto_bootstraps_a_profileless_user(api, monkeypatch):
    await _seed_source_material(api["maker"], api["hid"], api["uid"])
    fake = FakeProvider()
    monkeypatch.setattr("life_dashboard.ai.provider.AnthropicProvider", lambda key: fake)
    monkeypatch.setattr(ai_router.service, "get_provider", lambda s: fake)

    resp = await api["client"].patch("/ai/settings", json={"api_key": "sk-ant-good"})
    assert resp.status_code == 200, resp.text
    assert fake.validate_calls == 1

    row = await _settings_row(api["maker"], api["uid"])
    assert row.api_key_encrypted == "sk-ant-good"

    await _drain_background_tasks()

    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == DRAFTED_PROFILE.strip()
    assert memory.last_bootstrapped_at is not None


@pytest.mark.asyncio
async def test_saving_the_same_key_again_does_not_rebootstrap(api, monkeypatch):
    await _seed_source_material(api["maker"], api["hid"], api["uid"])
    fake = FakeProvider()
    monkeypatch.setattr("life_dashboard.ai.provider.AnthropicProvider", lambda key: fake)
    monkeypatch.setattr(ai_router.service, "get_provider", lambda s: fake)

    await api["client"].patch("/ai/settings", json={"api_key": "sk-ant-good"})
    await _drain_background_tasks()
    assert len(fake.calls) == 1

    await api["client"].patch("/ai/settings", json={"api_key": "sk-ant-good"})
    await _drain_background_tasks()
    assert len(fake.calls) == 1, "a populated profile must not be re-bootstrapped"


@pytest.mark.asyncio
async def test_clearing_the_key_leaves_the_profile_intact(api, monkeypatch):
    await api["client"].patch("/ai/profile", json={"content_md": DRAFTED_PROFILE})
    async with api["maker"]() as db:
        db.add(
            AiSettings(
                user_id=api["uid"],
                provider=AiProvider.anthropic,
                api_key_encrypted="sk-ant-good",
            )
        )
        await db.commit()

    resp = await api["client"].patch("/ai/settings", json={"clear_api_key": True})
    assert resp.status_code == 200

    row = await _settings_row(api["maker"], api["uid"])
    assert row.api_key_encrypted is None
    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == DRAFTED_PROFILE.strip()


@pytest.mark.asyncio
async def test_settings_update_without_a_key_never_probes_the_provider(api, monkeypatch):
    """Changing retention must not burn a validation call."""
    fake = FakeProvider()
    monkeypatch.setattr("life_dashboard.ai.provider.AnthropicProvider", lambda key: fake)

    resp = await api["client"].patch("/ai/settings", json={"retention_days": 30})
    assert resp.status_code == 200
    assert fake.validate_calls == 0


# ── coach-001b: notes-driven incremental proposer ─────────────────────────────


@pytest_asyncio.fixture
async def spy_proposer(monkeypatch):
    """Replace the detached proposer task with a recorder.

    Gating (has bootstrap run? is the threshold met? did the counter move?) is
    what these tests are about, and it is decided entirely in
    maybe_propose_from_notes before the task is spawned.
    """
    calls: list[tuple] = []

    async def _record(user_id, household_id):
        calls.append((user_id, household_id))

    monkeypatch.setattr(profile_service, "_run_incremental_proposer", _record)
    return calls


async def _add_notes(maker, hid, uid, n, prefix="Note"):
    async with maker() as db:
        for i in range(n):
            await notes_service.create_note(
                db,
                hid,
                uid,
                NoteCreate(title=f"{prefix} {i}", content_md=f"Body of {prefix} {i}."),
            )


@pytest.mark.asyncio
async def test_proposer_never_runs_before_bootstrap(api, spy_proposer):
    """Six notes — comfortably over the threshold — and still nothing, because
    the incremental path must not invent a profile from scratch."""
    await _add_notes(api["maker"], api["hid"], api["uid"], 6)
    await _drain_background_tasks()

    assert spy_proposer == []
    memory = await _memory(api["maker"], api["uid"])
    assert memory.notes_at_last_proposal == 0


@pytest.mark.asyncio
async def test_proposer_fires_exactly_once_per_threshold(api, spy_proposer):
    await _mark_bootstrapped(api["maker"], api["uid"])

    await _add_notes(api["maker"], api["hid"], api["uid"], 4)
    await _drain_background_tasks()
    assert spy_proposer == [], "under the threshold — nothing should fire"

    await _add_notes(api["maker"], api["hid"], api["uid"], 1, prefix="Fifth")
    await _drain_background_tasks()
    assert len(spy_proposer) == 1

    memory = await _memory(api["maker"], api["uid"])
    assert memory.notes_at_last_proposal == 5

    # The next four are again under the threshold: one call per N notes, not
    # one call per note once the profile exists.
    await _add_notes(api["maker"], api["hid"], api["uid"], 4, prefix="Later")
    await _drain_background_tasks()
    assert len(spy_proposer) == 1


@pytest.mark.asyncio
async def test_counter_advances_even_when_the_model_skips(api, monkeypatch):
    """The whole point of the counter: a SKIP still costs the user their
    proposer call for that batch."""
    await _mark_bootstrapped(api["maker"], api["uid"])
    async with api["maker"]() as db:
        db.add(
            AiSettings(
                user_id=api["uid"],
                provider=AiProvider.anthropic,
                api_key_encrypted="sk-ant-good",
            )
        )
        await db.commit()

    fake = FakeProvider(responses=["SKIP"])
    monkeypatch.setattr("life_dashboard.ai.service.get_provider", lambda s: fake)

    await _add_notes(api["maker"], api["hid"], api["uid"], 5)
    await _drain_background_tasks()

    assert len(fake.calls) == 1
    assert "Bias toward SKIP" in fake.calls[0]["user"]

    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == ""  # SKIP wrote nothing
    assert memory.notes_at_last_proposal == 5  # …but the batch was spent

    # Four more notes must not buy another call.
    await _add_notes(api["maker"], api["hid"], api["uid"], 4, prefix="After")
    await _drain_background_tasks()
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_proposer_applies_an_update_directly_when_it_finds_signal(api, monkeypatch):
    await _mark_bootstrapped(api["maker"], api["uid"], memory_text="## Current focuses\nOld.")
    async with api["maker"]() as db:
        db.add(
            AiSettings(
                user_id=api["uid"],
                provider=AiProvider.anthropic,
                api_key_encrypted="sk-ant-good",
            )
        )
        await db.commit()

    fake = FakeProvider(responses=[DRAFTED_PROFILE])
    monkeypatch.setattr("life_dashboard.ai.service.get_provider", lambda s: fake)

    await _add_notes(api["maker"], api["hid"], api["uid"], 5)
    await _drain_background_tasks()

    memory = await _memory(api["maker"], api["uid"])
    assert memory.memory_text == DRAFTED_PROFILE.strip()

    async with api["maker"]() as db:
        rows = (
            await db.execute(
                select(UserProfileUpdate).where(UserProfileUpdate.source == "incremental")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "accepted"  # audit trail, not a queue


@pytest.mark.asyncio
async def test_a_failing_proposer_never_breaks_the_note_save(api, monkeypatch):
    await _mark_bootstrapped(api["maker"], api["uid"])

    async def _explode(db, user_id, household_id):
        raise RuntimeError("AI provider misconfigured")

    monkeypatch.setattr(profile_service, "maybe_propose_from_notes", _explode)

    async with api["maker"]() as db:
        note = await notes_service.create_note(
            db,
            api["hid"],
            api["uid"],
            NoteCreate(title="Survives", content_md="The commit must land."),
        )
    assert note.title == "Survives"

    async with api["maker"]() as db:
        count = (
            await db.execute(select(func.count()).select_from(notes_service.Note))
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_editing_notes_also_drives_the_threshold_check(api, spy_proposer):
    """Updates run the same gate, attributed to the note's author."""
    await _mark_bootstrapped(api["maker"], api["uid"])
    await _add_notes(api["maker"], api["hid"], api["uid"], 5)
    await _drain_background_tasks()
    assert len(spy_proposer) == 1

    async with api["maker"]() as db:
        note_id = (
            await db.execute(select(notes_service.Note.id).limit(1))
        ).scalar_one()
        await notes_service.update_note(
            db, note_id, api["hid"], NoteUpdate(content_md="Rewritten body.")
        )
    await _drain_background_tasks()
    # No *new* notes, so the delta is still 0 — the edit checks but does not
    # trigger. Net-new is the unit, per the counter's name.
    assert len(spy_proposer) == 1


async def _mark_bootstrapped(maker, uid, memory_text=""):
    async with maker() as db:
        memory = MemberAiMemory(
            user_id=uid,
            memory_text=memory_text,
            last_bootstrapped_at=datetime.now(UTC),
            notes_at_last_proposal=0,
        )
        db.add(memory)
        await db.commit()
