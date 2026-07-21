"""Guided journaling — the Talk-it-out session and its check-in modes.

Covers journal-001 (session lifecycle: start, resume, synthesize, save) and
journal-002 (Mood / Body / Rant / Day review modes) as the single flow they
ship as.

What these tests are really pinning down:

* **Saving APPENDS.** The whole feature is worthless — actively harmful — if
  finishing a session clobbers an entry the user had already started by hand.
  The divider only appears when there was something to divide.
* **The mode is locked once chosen.** A second /start carrying a different
  mode is ignored, not honoured. Rant and Day review give the model opposite
  instructions; letting a stray re-mount swap them mid-session would change
  the model's behaviour underneath the user.
* **Day review reads the clock, not the calendar.** Before 4pm local it looks
  ahead; after, it looks back.
* **The opener costs no round trip.** Openers are canned constants, so a mode
  pick renders instantly and cannot fail on a flaky provider.

Every HTTP endpoint is exercised through the ASGI app rather than imported: a
route that is registered but never called is exactly how this feature shipped
a broken endpoint once already.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.core.database as database_module
from life_dashboard.ai import service as ai_service
from life_dashboard.ai.models import AiConversation, AiMessage, AiMessageRole
from life_dashboard.auth.dependencies import get_current_user, require_ai_enabled
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.database import Base, get_db
from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.notes.models import Note
from life_dashboard.events import semantic
from life_dashboard.main import app
from life_dashboard.webhooks.summaries import filter_summary, is_known_event

# ── Pure composition rules (no DB, no provider) ───────────────────────────────


def test_compose_appends_below_a_divider_when_the_entry_already_has_content():
    out = ai_service.compose_journal_entry(
        "Woke up at 5. Straight into the deploy queue.",
        "I came in furious about the deadline moving again.",
    )
    assert out == (
        "Woke up at 5. Straight into the deploy queue.\n"
        "\n"
        "---\n"
        "\n"
        "I came in furious about the deadline moving again."
    )
    # The hand-written half survives verbatim — this is the whole contract.
    assert out.startswith("Woke up at 5. Straight into the deploy queue.")


@pytest.mark.parametrize("existing", [None, "", "   \n\n  "])
def test_compose_omits_the_divider_when_there_was_nothing_to_divide(existing):
    out = ai_service.compose_journal_entry(existing, "Flat today. Grey.")
    assert out == "Flat today. Grey."
    assert "---" not in out


def test_compose_puts_the_transcript_below_its_own_divider_and_heading():
    out = ai_service.compose_journal_entry(
        None,
        "Flat today.",
        "**Coach:** What's up?\n\n**You:** not much",
    )
    assert out == (
        "Flat today.\n"
        "\n"
        "---\n"
        "\n"
        "## Conversation transcript\n"
        "\n"
        "**Coach:** What's up?\n"
        "\n"
        "**You:** not much"
    )


def test_compose_with_both_existing_content_and_a_transcript_uses_two_dividers():
    out = ai_service.compose_journal_entry("Earlier.", "Summary.", "**You:** hi")
    assert out.count("\n---\n") == 2
    assert out.index("Earlier.") < out.index("Summary.") < out.index("**You:** hi")


def test_compose_skips_the_transcript_section_when_the_transcript_is_empty():
    # include_transcript on a session with nothing quotable must not leave a
    # dangling '## Conversation transcript' header over blank space.
    out = ai_service.compose_journal_entry("Earlier.", "Summary.", "   ")
    assert "Conversation transcript" not in out
    assert out.count("---") == 1


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


def test_transcript_labels_the_two_human_facing_roles_and_drops_tool_turns():
    out = ai_service.format_journal_transcript(
        [
            _Msg(AiMessageRole.assistant, "Vent. What's bugging you?"),
            _Msg(AiMessageRole.user, "Kyle moved the deadline again."),
            _Msg(AiMessageRole.tool, '{"tool":"update_profile","ok":true}'),
            _Msg(AiMessageRole.assistant, "  Third time. That's infuriating.  "),
            _Msg(AiMessageRole.user, "   "),
        ]
    )
    assert out == (
        "**Coach:** Vent. What's bugging you?\n"
        "\n"
        "**You:** Kyle moved the deadline again.\n"
        "\n"
        "**Coach:** Third time. That's infuriating."
    )
    # A raw tool payload in someone's journal is noise at best.
    assert "update_profile" not in out


# ── Canned openers (journal-002) ──────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["mood", "body", "rant"])
def test_every_structured_mode_has_an_opener_ready_without_a_provider_call(mode):
    opener = ai_service.canned_opener_for(mode, None)
    assert opener and opener.strip() == opener


def test_day_review_looks_ahead_before_four_and_back_after():
    morning = ai_service.canned_opener_for("day_review", 9)
    evening = ai_service.canned_opener_for("day_review", 20)
    assert "Looking ahead" in morning
    assert "standing out from today" in evening
    assert morning != evening
    # 16:00 is the boundary itself — "before 4pm" is strictly before.
    assert ai_service.canned_opener_for("day_review", 15) == morning
    assert ai_service.canned_opener_for("day_review", 16) == evening
    # No local_hour (older client, blocked clock): fall back to the lens that
    # fits the more common journaling time rather than guessing morning.
    assert ai_service.canned_opener_for("day_review", None) == evening


@pytest.mark.parametrize("mode", [None, "", "blank", "not_a_mode"])
def test_blank_slate_and_unknown_modes_get_no_opener_at_all(mode):
    assert ai_service.canned_opener_for(mode, 9) is None


def test_rant_mode_tells_the_model_to_stay_put_rather_than_reality_test():
    """journal-002 deliberately contradicts coach-003's CBT move here. The
    coach challenges a distorted thought; rant mode must not. If this ever
    starts asserting the opposite, the feature has been "fixed" into
    uselessness."""
    user = User(email="b@x.com", password_hash="x", display_name="Brandon")
    prompt = ai_service._build_journal_system_prompt(user, "", mode="rant")
    assert "Do NOT reality-test" in prompt
    assert "STAY WITH THEM" in prompt

    # And the same prompt without the mode must not carry the override.
    assert "Do NOT reality-test" not in ai_service._build_journal_system_prompt(
        user, "", mode=None
    )


def test_each_mode_layers_its_own_instruction_block_onto_the_journal_prompt():
    user = User(email="b@x.com", password_hash="x", display_name="Brandon")
    for mode, marker in [
        ("mood", "Mode: Mood check"),
        ("body", "Mode: Body check"),
        ("rant", "Mode: Rant"),
        ("day_review", "Mode: Day review"),
    ]:
        prompt = ai_service._build_journal_system_prompt(user, "", mode=mode)
        assert marker in prompt, mode
        # The base contract survives the override in every mode.
        assert "NEVER give advice unsolicited" in prompt


# ── The bus event is this feature's agent surface ─────────────────────────────


def test_the_journal_event_is_deliverable_but_can_never_carry_entry_text():
    assert is_known_event("journal.session_saved")
    leaked = filter_summary(
        "journal.session_saved",
        {
            "mode": "rant",
            "included_transcript": True,
            "message_count": 7,
            "appended_to_existing": True,
            # A future careless caller widening its own summary must not
            # widen the wire. These are the fields that would matter.
            "content_md": "I am so done with this sprint.",
            "summary_md": "I came in furious.",
            "title": "Tuesday, July 21, 2026",
        },
    )
    assert leaked == {
        "mode": "rant",
        "included_transcript": True,
        "message_count": 7,
        "appended_to_existing": True,
    }


# ── HTTP surface ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api(monkeypatch):
    """ASGI client, a household with two members, and a journal collection.

    AsyncSessionLocal is repointed at the same in-memory engine because the
    save path's coach hooks open their own session.
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
        user = User(email="b@x.com", password_hash="x", display_name="Brandon", is_active=True)
        other = User(email="o@x.com", password_hash="x", display_name="Other", is_active=True)
        db.add_all([user, other])
        await db.flush()
        db.add_all(
            [
                HouseholdMembership(
                    household_id=hh.id, user_id=user.id, role=MembershipRole.owner
                ),
                HouseholdMembership(
                    household_id=hh.id, user_id=other.id, role=MembershipRole.member
                ),
            ]
        )
        journal_col = Collection(
            household_id=hh.id,
            created_by_user_id=user.id,
            name="Journaling",
            domain="notes",
            kind="journal",
        )
        plain_col = Collection(
            household_id=hh.id,
            created_by_user_id=user.id,
            name="Reading notes",
            domain="notes",
            kind="notes",
        )
        db.add_all([journal_col, plain_col])
        await db.commit()

    for u in (user, other):
        u.household_id = hh.id
        u.household_name = hh.name
    user.role = MembershipRole.owner.value
    other.role = MembershipRole.member.value

    async def _override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_ai_enabled] = lambda: user

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "maker": maker,
            "hid": hh.id,
            "user": user,
            "other": other,
            "journal_col": journal_col.id,
            "plain_col": plain_col.id,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


async def _make_note(maker, hid, uid, collection_id, *, title="Tuesday", content=None):
    async with maker() as db:
        note = Note(
            household_id=hid,
            created_by_user_id=uid,
            title=title,
            content_md=content,
            collection_id=collection_id,
        )
        db.add(note)
        await db.commit()
        return note.id


async def _note_body(maker, note_id) -> str:
    async with maker() as db:
        return (
            await db.execute(select(Note.content_md).where(Note.id == note_id))
        ).scalar_one()


class _StubProvider:
    """Stands in for the Anthropic provider on the /finish path."""

    def __init__(self, text="I came in furious and left tired."):
        self.text = text
        self.calls = []

    async def complete(self, messages, system, *, max_tokens=1024):
        self.calls.append({"system": system, "user": messages[0]["content"]})
        return self.text, 10, 20, "fake-model"


async def test_start_creates_a_session_and_asks_for_a_mode(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    r = await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_new"] is True
    assert body["needs_mode_pick"] is True
    assert body["mode"] is None
    # The mount call must not spend a provider round trip on an opener.
    assert body["opening_message"] is None


async def test_start_refuses_a_note_that_is_not_a_journal_entry(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["plain_col"]
    )
    r = await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    assert r.status_code == 400
    assert "journal" in r.json()["detail"].lower()


async def test_start_refuses_a_loose_note_with_no_collection(api):
    note_id = await _make_note(api["maker"], api["hid"], api["user"].id, None)
    r = await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    assert r.status_code == 400


async def test_start_cannot_reach_another_members_journal_entry(api):
    """Journal entries are the most personal data in the app. A note owned by
    a housemate must 404 even though we share a household."""
    note_id = await _make_note(
        api["maker"], api["hid"], api["other"].id, api["journal_col"]
    )
    r = await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    assert r.status_code == 404


async def test_start_404s_on_a_note_that_does_not_exist(api):
    r = await api["client"].post(
        "/ai/journal/start", json={"note_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404


async def test_picking_a_mode_seeds_the_canned_opener_as_the_first_turn(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})

    r = await api["client"].post(
        "/ai/journal/start",
        json={"note_id": str(note_id), "mode": "rant", "local_hour": 20},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "rant"
    assert body["needs_mode_pick"] is False
    assert body["opening_message"] == ai_service.canned_opener_for("rant", 20)

    # Persisted as a real assistant turn, so the transcript the model sees
    # (and the one the user can re-read) both start from the same place.
    async with api["maker"]() as db:
        rows = (
            await db.execute(
                select(AiMessage).where(
                    AiMessage.conversation_id == uuid.UUID(body["conversation_id"])
                )
            )
        ).scalars().all()
    assert [m.role for m in rows] == [AiMessageRole.assistant]
    assert rows[0].content == body["opening_message"]


async def test_the_mode_is_locked_once_chosen(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    await api["client"].post(
        "/ai/journal/start", json={"note_id": str(note_id), "mode": "rant"}
    )

    # Rant tells the model to stay put; mood tells it to probe. A stray
    # re-mount must not swap them underneath a session in progress.
    r = await api["client"].post(
        "/ai/journal/start", json={"note_id": str(note_id), "mode": "mood"}
    )
    assert r.json()["mode"] == "rant"
    assert r.json()["opening_message"] is None  # no second opener either

    async with api["maker"]() as db:
        conv = (
            await db.execute(
                select(AiConversation).where(AiConversation.note_id == note_id)
            )
        ).scalar_one()
        assert conv.mode == "rant"
        count = len(
            (
                await db.execute(
                    select(AiMessage).where(AiMessage.conversation_id == conv.id)
                )
            ).scalars().all()
        )
    assert count == 1


async def test_day_review_branches_on_the_users_local_hour(api):
    morning_note = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"], title="Morning"
    )
    evening_note = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"], title="Evening"
    )
    for nid, hour in ((morning_note, 9), (evening_note, 20)):
        await api["client"].post("/ai/journal/start", json={"note_id": str(nid)})

    morning = (
        await api["client"].post(
            "/ai/journal/start",
            json={"note_id": str(morning_note), "mode": "day_review", "local_hour": 9},
        )
    ).json()["opening_message"]
    evening = (
        await api["client"].post(
            "/ai/journal/start",
            json={"note_id": str(evening_note), "mode": "day_review", "local_hour": 20},
        )
    ).json()["opening_message"]

    assert "Looking ahead" in morning
    assert "standing out from today" in evening


async def test_reopening_resumes_the_same_conversation(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    first = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    await api["client"].post(
        "/ai/journal/start", json={"note_id": str(note_id), "mode": "mood"}
    )
    again = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()

    assert again["conversation_id"] == first["conversation_id"]
    assert again["is_new"] is False
    assert again["mode"] == "mood"
    assert again["needs_mode_pick"] is False


async def test_reopening_before_picking_a_mode_shows_the_picker_again(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    again = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    assert again["is_new"] is False
    assert again["needs_mode_pick"] is True


async def test_the_resumed_transcript_is_readable_so_the_overlay_can_rehydrate(api):
    """The client reopens a session by reading the conversation back. If this
    stops returning turns, a resumed session renders blank and 'Finish' never
    becomes available."""
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    started = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    await api["client"].post(
        "/ai/journal/start", json={"note_id": str(note_id), "mode": "rant"}
    )
    async with api["maker"]() as db:
        await ai_service.append_message(
            db,
            uuid.UUID(started["conversation_id"]),
            AiMessageRole.user,
            "Kyle moved the deadline again.",
        )
        await db.commit()

    r = await api["client"].get(f"/ai/conversations/{started['conversation_id']}")
    assert r.status_code == 200
    roles = [m["role"] for m in r.json()["messages"]]
    assert roles == ["assistant", "user"]


async def test_save_appends_to_an_entry_the_user_already_started(api):
    """The one thing this feature must never do is eat what was already there."""
    note_id = await _make_note(
        api["maker"],
        api["hid"],
        api["user"].id,
        api["journal_col"],
        content="Woke up at 5. Straight into the deploy queue.",
    )
    conv = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()["conversation_id"]

    r = await api["client"].post(
        "/ai/journal/save",
        json={
            "conversation_id": conv,
            "content_md": "I came in furious about the deadline.",
            "include_transcript": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["note_id"] == str(note_id)

    body = await _note_body(api["maker"], note_id)
    assert body == (
        "Woke up at 5. Straight into the deploy queue.\n"
        "\n"
        "---\n"
        "\n"
        "I came in furious about the deadline."
    )


async def test_saving_twice_keeps_appending_rather_than_replacing(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    conv = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()["conversation_id"]

    for text in ("First pass.", "Second pass."):
        r = await api["client"].post(
            "/ai/journal/save",
            json={"conversation_id": conv, "content_md": text,
                  "include_transcript": False},
        )
        assert r.status_code == 200

    body = await _note_body(api["maker"], note_id)
    assert "First pass." in body
    assert body.endswith("Second pass.")


async def test_save_with_the_transcript_toggle_on_appends_the_conversation(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    started = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    await api["client"].post(
        "/ai/journal/start", json={"note_id": str(note_id), "mode": "mood"}
    )
    async with api["maker"]() as db:
        await ai_service.append_message(
            db, uuid.UUID(started["conversation_id"]), AiMessageRole.user, "flat I guess"
        )
        await db.commit()

    r = await api["client"].post(
        "/ai/journal/save",
        json={
            "conversation_id": started["conversation_id"],
            "content_md": "Flat today.",
            "include_transcript": True,
        },
    )
    assert r.status_code == 200

    body = await _note_body(api["maker"], note_id)
    assert "## Conversation transcript" in body
    assert "**You:** flat I guess" in body
    assert body.index("Flat today.") < body.index("## Conversation transcript")


async def test_save_with_the_transcript_toggle_off_keeps_the_conversation_private(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    started = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    async with api["maker"]() as db:
        await ai_service.append_message(
            db,
            uuid.UUID(started["conversation_id"]),
            AiMessageRole.user,
            "something I would rather not have quoted back",
        )
        await db.commit()

    await api["client"].post(
        "/ai/journal/save",
        json={
            "conversation_id": started["conversation_id"],
            "content_md": "Flat today.",
            "include_transcript": False,
        },
    )
    body = await _note_body(api["maker"], note_id)
    assert body == "Flat today."
    assert "rather not have quoted back" not in body


async def test_saving_announces_the_session_without_carrying_the_entry(api, monkeypatch):
    recorded = []

    def _spy(db, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(semantic, "record", _spy)

    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"], content="Earlier."
    )
    started = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    await api["client"].post(
        "/ai/journal/start", json={"note_id": str(note_id), "mode": "rant"}
    )
    await api["client"].post(
        "/ai/journal/save",
        json={
            "conversation_id": started["conversation_id"],
            "content_md": "I came in furious.",
            "include_transcript": False,
        },
    )

    assert len(recorded) == 1
    evt = recorded[0]
    assert evt["event"] == "journal.session_saved"
    assert evt["entity_type"] == "note"
    assert evt["entity_id"] == note_id
    assert evt["summary"] == {
        "mode": "rant",
        "included_transcript": False,
        "message_count": 0,
        "appended_to_existing": True,
    }
    assert "I came in furious." not in str(evt["summary"])


async def test_save_rejects_a_conversation_that_is_not_a_journal_session(api):
    async with api["maker"]() as db:
        conv = AiConversation(
            user_id=api["user"].id,
            household_id=api["hid"],
            title="Regular chat",
            kind="chat",
        )
        db.add(conv)
        await db.commit()
        conv_id = conv.id

    r = await api["client"].post(
        "/ai/journal/save",
        json={"conversation_id": str(conv_id), "content_md": "x",
              "include_transcript": False},
    )
    assert r.status_code == 404


async def test_save_cannot_target_another_members_session(api):
    note_id = await _make_note(
        api["maker"], api["hid"], api["other"].id, api["journal_col"]
    )
    async with api["maker"]() as db:
        conv = AiConversation(
            user_id=api["other"].id,
            household_id=api["hid"],
            title="Journal",
            kind="journal",
            note_id=note_id,
        )
        db.add(conv)
        await db.commit()
        conv_id = conv.id

    r = await api["client"].post(
        "/ai/journal/save",
        json={"conversation_id": str(conv_id), "content_md": "x",
              "include_transcript": False},
    )
    assert r.status_code == 404


async def test_finish_synthesizes_a_first_person_summary_without_saving_it(api, monkeypatch):
    stub = _StubProvider("I came in furious and left tired.")
    monkeypatch.setattr(ai_service, "get_provider", lambda _s: stub)

    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"], content="Earlier."
    )
    started = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()
    async with api["maker"]() as db:
        await ai_service.append_message(
            db, uuid.UUID(started["conversation_id"]), AiMessageRole.user, "so done"
        )
        await db.commit()

    r = await api["client"].post(f"/ai/journal/{started['conversation_id']}/finish")
    assert r.status_code == 200
    assert r.json()["summary_md"] == "I came in furious and left tired."

    # The user reviews and edits before anything is written — /finish must
    # leave the entry untouched.
    assert await _note_body(api["maker"], note_id) == "Earlier."

    # And the prompt has to actually ask for 'I' voice, or coach-002 ends up
    # extracting signals from a third-person report about the user.
    assert "First person" in stub.calls[0]["system"]
    assert "NEVER\n  third person" in stub.calls[0]["system"]


async def test_finish_says_so_when_there_is_nothing_to_summarize(api, monkeypatch):
    monkeypatch.setattr(ai_service, "get_provider", lambda _s: _StubProvider())
    note_id = await _make_note(
        api["maker"], api["hid"], api["user"].id, api["journal_col"]
    )
    started = (
        await api["client"].post("/ai/journal/start", json={"note_id": str(note_id)})
    ).json()

    r = await api["client"].post(f"/ai/journal/{started['conversation_id']}/finish")
    assert r.status_code == 400
    assert "Not enough" in r.json()["detail"]


async def test_finish_cannot_reach_another_members_session(api, monkeypatch):
    monkeypatch.setattr(ai_service, "get_provider", lambda _s: _StubProvider())
    async with api["maker"]() as db:
        conv = AiConversation(
            user_id=api["other"].id,
            household_id=api["hid"],
            title="Journal",
            kind="journal",
        )
        db.add(conv)
        await db.commit()
        conv_id = conv.id

    r = await api["client"].post(f"/ai/journal/{conv_id}/finish")
    assert r.status_code == 404
