"""Prompt caching on the chat path (plans/020-implement-prompt-caching.md).

Asserting that `_cacheable()` returns the right dict shape would prove almost
nothing — a helper can be perfectly correct and never be wired into a request.
So these tests work outward from the wire:

1. `test_request_payload_*` build a real `stream_chat` payload against a fake
   Anthropic client and assert what the API will actually receive: exactly one
   `cache_control` on the *final* tool, one on the system block, tools ahead of
   system, top-level automatic caching present, and `TOOL_DEFINITIONS` byte-for-
   byte unchanged afterwards (compared against a deepcopy taken before the call).
2. `test_generate_stream_persists_cache_tokens` drives `generate_stream` end to
   end with that same fake client, so the kwargs genuinely reach
   `messages.stream()` and a usage object carrying the two new fields is parsed
   and written to `ai_usage`.

The fake client mimics the SDK's async context-manager stream helper rather
than patching `AnthropicProvider.stream_chat`, because patching the method
under test is how a caching regression would ship unnoticed.
"""
import copy

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from life_dashboard.ai import service as ai_service
from life_dashboard.ai.models import AiConversation, AiUsage
from life_dashboard.ai.provider import AnthropicProvider, _cacheable
from life_dashboard.ai.tools import TOOL_DEFINITIONS
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.database import Base

pytestmark = pytest.mark.asyncio


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeUsage:
    def __init__(self, cache_creation: int, cache_read: int) -> None:
        self.input_tokens = 120
        self.output_tokens = 40
        self.cache_creation_input_tokens = cache_creation
        self.cache_read_input_tokens = cache_read


class _FakeMessage:
    """Stands in for the SDK's final Message: text only, no tool_use blocks."""

    def __init__(self, usage: _FakeUsage) -> None:
        self.content = []
        self.model = "claude-sonnet-4-6"
        self.stop_reason = "end_turn"
        self.usage = usage


class _FakeStream:
    def __init__(self, message: _FakeMessage) -> None:
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    @property
    async def text_stream(self):  # pragma: no cover - replaced below
        raise NotImplementedError

    async def get_final_message(self) -> _FakeMessage:
        return self._message


class _StreamHelper:
    """`async with client.messages.stream(**kwargs)` — records the kwargs."""

    def __init__(self, recorder: list[dict], message: _FakeMessage) -> None:
        self._recorder = recorder
        self._message = message

    def stream(self, **kwargs):
        self._recorder.append(kwargs)
        return _FakeStream(self._message)


class _FakeClient:
    def __init__(self, recorder: list[dict], message: _FakeMessage) -> None:
        self.messages = _StreamHelper(recorder, message)


def _text_stream_patch(chunks: list[str]):
    async def _gen(self):
        for chunk in chunks:
            yield chunk
    return _gen


def _make_provider(
    recorder: list[dict],
    *,
    cache_creation: int = 0,
    cache_read: int = 0,
    chunks: tuple[str, ...] = ("Hello",),
) -> AnthropicProvider:
    """A real AnthropicProvider whose SDK client is swapped for the fake."""
    provider = AnthropicProvider.__new__(AnthropicProvider)
    message = _FakeMessage(_FakeUsage(cache_creation, cache_read))
    provider._client = _FakeClient(recorder, message)
    # text_stream must be an async iterator; patch it on the fake stream class.
    _FakeStream.text_stream = property(
        lambda self: _text_stream_patch(list(chunks))(self)
    )
    return provider


async def _drain(provider: AnthropicProvider, tools: list[dict] | None) -> None:
    async for _ in provider.stream_chat(
        [{"role": "user", "content": "hi"}], "SYSTEM PROMPT", tools=tools
    ):
        pass


# ── 1. The request payload that actually goes over the wire ───────────────────

async def test_request_payload_places_breakpoints_correctly() -> None:
    recorder: list[dict] = []
    provider = _make_provider(recorder)
    tools = [dict(t) for t in TOOL_DEFINITIONS]

    await _drain(provider, tools)

    assert len(recorder) == 1
    kwargs = recorder[0]

    # Tools render before system, so key order in the payload is load-bearing
    # for a human reading it, and the two explicit breakpoints must be exactly
    # where the plan puts them.
    keys = list(kwargs)
    assert keys.index("tools") < keys.index("system")

    sent_tools = kwargs["tools"]
    assert len(sent_tools) == len(TOOL_DEFINITIONS)
    marked = [i for i, t in enumerate(sent_tools) if "cache_control" in t]
    assert marked == [len(sent_tools) - 1], "exactly one breakpoint, on the last tool"
    assert sent_tools[-1]["cache_control"] == {"type": "ephemeral"}

    system = kwargs["system"]
    assert system == [
        {
            "type": "text",
            "text": "SYSTEM PROMPT",
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # Top-level automatic caching walks a breakpoint through message history.
    assert kwargs["cache_control"] == {"type": "ephemeral"}


async def test_tool_definitions_are_never_mutated() -> None:
    """TOOL_DEFINITIONS is a module constant; a request-scoped key on it would
    leak into every later request and every other caller."""
    before = copy.deepcopy(TOOL_DEFINITIONS)

    recorder: list[dict] = []
    provider = _make_provider(recorder)
    await _drain(provider, TOOL_DEFINITIONS)

    assert TOOL_DEFINITIONS == before
    assert not any("cache_control" in t for t in TOOL_DEFINITIONS)
    # ...and the copy that *was* sent is a different object.
    assert recorder[0]["tools"][-1] is not TOOL_DEFINITIONS[-1]


async def test_no_tools_still_caches_system() -> None:
    """Journal mode can pass no tools; the system breakpoint must survive."""
    recorder: list[dict] = []
    provider = _make_provider(recorder)

    await _drain(provider, None)

    kwargs = recorder[0]
    assert "tools" not in kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_cacheable_helper_copies_nested_dicts() -> None:
    """Two calls must not share a cache_control dict — mutating one later
    would silently change the other."""
    tools_a, system_a = _cacheable([{"name": "a"}], "S")
    tools_b, system_b = _cacheable([{"name": "a"}], "S")
    assert tools_a[-1]["cache_control"] is not tools_b[-1]["cache_control"]
    assert system_a[0]["cache_control"] is not system_b[0]["cache_control"]


# ── 2. End-to-end: usage fields survive the streaming path into the DB ────────

@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed(db: AsyncSession) -> tuple[User, Household, AiConversation]:
    household = Household(name="Test House")
    db.add(household)
    await db.flush()
    user = User(email="a@example.com", password_hash="x", display_name="A")
    db.add(user)
    await db.flush()
    db.add(
        HouseholdMembership(
            household_id=household.id, user_id=user.id, role=MembershipRole.owner
        )
    )
    convo = AiConversation(user_id=user.id, household_id=household.id, title="t")
    db.add(convo)
    await db.flush()
    return user, household, convo


async def test_generate_stream_persists_cache_tokens(session: AsyncSession) -> None:
    user, household, convo = await _seed(session)

    recorder: list[dict] = []
    provider = _make_provider(
        recorder, cache_creation=0, cache_read=15_582, chunks=("Hi ", "there")
    )

    events = [
        chunk
        async for chunk in ai_service.generate_stream(
            session,
            provider,
            conversation_id=convo.id,
            user_id=user.id,
            household_id=household.id,
            display_name="A",
            system="SYSTEM PROMPT",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOL_DEFINITIONS,
        )
    ]

    assert any('"type": "done"' in e for e in events), events

    # The kwargs really reached messages.stream() through the live code path.
    assert recorder, "provider.stream_chat was never called"
    assert recorder[0]["cache_control"] == {"type": "ephemeral"}
    assert recorder[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    row = (await session.execute(select(AiUsage))).scalars().one()
    assert row.cache_read_input_tokens == 15_582
    assert row.cache_creation_input_tokens == 0
    assert row.input_tokens == 120
    assert row.output_tokens == 40


async def test_generate_stream_records_cache_writes(session: AsyncSession) -> None:
    """First call of a conversation writes the cache rather than reading it."""
    user, household, convo = await _seed(session)

    recorder: list[dict] = []
    provider = _make_provider(recorder, cache_creation=17_600, cache_read=0)

    async for _ in ai_service.generate_stream(
        session,
        provider,
        conversation_id=convo.id,
        user_id=user.id,
        household_id=household.id,
        display_name="A",
        system="SYSTEM PROMPT",
        messages=[{"role": "user", "content": "hi"}],
        tools=TOOL_DEFINITIONS,
    ):
        pass

    row = (await session.execute(select(AiUsage))).scalars().one()
    assert row.cache_creation_input_tokens == 17_600
    assert row.cache_read_input_tokens == 0


async def test_missing_cache_fields_default_to_zero(session: AsyncSession) -> None:
    """An older SDK response shape has no cache_* attributes at all; the usage
    site must fall back to 0 rather than raising."""
    user, household, convo = await _seed(session)

    class _OldUsage:
        input_tokens = 10
        output_tokens = 5

    recorder: list[dict] = []
    provider = _make_provider(recorder)
    provider._client.messages._message.usage = _OldUsage()

    async for _ in ai_service.generate_stream(
        session,
        provider,
        conversation_id=convo.id,
        user_id=user.id,
        household_id=household.id,
        display_name="A",
        system="S",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
    ):
        pass

    row = (await session.execute(select(AiUsage))).scalars().one()
    assert row.cache_creation_input_tokens == 0
    assert row.cache_read_input_tokens == 0
