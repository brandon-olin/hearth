"""Tests for the Alexa skill webhook (voice-002).

The endpoint reuses the domain services (via the same idempotent functions as
the MCP write tools), so these tests focus on what the voice surface adds:

  * account linking — a request with no / dead token is answered with a spoken
    LinkAccount prompt, never an error, and never touches data;
  * the four intents map to the right service and speak a natural reply;
  * writes are idempotent and record a ``source="voice"`` audit row;
  * token scope ∩ member ceiling gates each intent exactly as elsewhere;
  * request verification helpers (applicationId, timestamp, cert URL) reject the
    forgeries they exist to stop.

Data lives in a shared in-memory engine; the router resolves its session from
``get_db``, overridden here, and the service resolves auth from that same
session, so one PAT drives the whole stack over the wire.
"""
import base64
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from life_dashboard.audit.models import AuditLog
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_service import create_token
from life_dashboard.core.database import Base, get_db
from life_dashboard.domains.grocery_lists.models import GroceryItem, GroceryList
from life_dashboard.domains.habits.models import Habit, HabitOccurrence
from life_dashboard.domains.todos.models import Todo
from life_dashboard.main import app
from life_dashboard.voice import signature

ALL_WRITE = {"todos": "write", "grocery": "write", "habits": "write", "calendar": "write"}


# ── Envelope builders ─────────────────────────────────────────────────────────

def _intent_body(name, slots=None, *, token="__use_alice__", app_id="amzn1.ask.skill.hearth"):
    system = {"application": {"applicationId": app_id}}
    if token is not None:
        system["user"] = {"accessToken": token}
    return {
        "version": "1.0",
        "context": {"System": system},
        "request": {
            "type": "IntentRequest",
            "requestId": "r-" + name,
            "timestamp": datetime.now(UTC).isoformat(),
            "intent": {
                "name": name,
                "slots": {k: {"name": k, "value": v} for k, v in (slots or {}).items()},
            },
        },
    }


def _speech(resp_json: dict) -> str:
    return resp_json["response"].get("outputSpeech", {}).get("text", "")


def _has_link_card(resp_json: dict) -> bool:
    return resp_json["response"].get("card", {}).get("type") == "LinkAccount"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with maker() as db:
            yield db

    app.dependency_overrides[get_db] = _override_get_db

    async with maker() as db:
        household = Household(name="The Olins")
        db.add(household)
        await db.flush()
        alice = User(email="a@x.com", password_hash="x", display_name="Alice", is_active=True)
        db.add(alice)
        await db.flush()
        db.add(HouseholdMembership(
            household_id=household.id, user_id=alice.id, role=MembershipRole.owner
        ))
        db.add(Habit(household_id=household.id, created_by_user_id=alice.id,
                     name="Floss", frequency="daily", status="active", visibility="household"))
        db.add(GroceryList(household_id=household.id, created_by_user_id=alice.id,
                           name="Weekly shop", status="active", visibility="household"))
        # A pending todo due today, so QueryTodos has something to count.
        db.add(Todo(household_id=household.id, created_by_user_id=alice.id,
                    title="Pay rent", status="pending", visibility="household",
                    due_date=date.today()))
        await db.commit()

        _, raw_alice = await create_token(db, alice.id, "Echo", ALL_WRITE, None)
        _, raw_readonly = await create_token(db, alice.id, "Read only", {"todos": "read"}, None)
        alice_id, hh_id = alice.id, household.id

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    yield {
        "client": client, "maker": maker, "raw_alice": raw_alice,
        "raw_readonly": raw_readonly, "alice_id": alice_id, "household_id": hh_id,
    }
    await client.aclose()
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


def _token_of(body):
    return body.get("context", {}).get("System", {}).get("user", {}).get("accessToken")


async def _post(env, body):
    if _token_of(body) == "__use_alice__":
        body["context"]["System"]["user"]["accessToken"] = env["raw_alice"]
    return await env["client"].post("/voice/alexa", json=body)


async def _count(maker, model, **filters):
    async with maker() as db:
        q = select(func.count()).select_from(model)
        for col, val in filters.items():
            q = q.where(getattr(model, col) == val)
        return (await db.execute(q)).scalar_one()


# ── Account linking ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_token_returns_link_account_card(env):
    resp = await _post(env, _intent_body("QueryTodos", token=None))
    assert resp.status_code == 200
    body = resp.json()
    assert _has_link_card(body)
    assert "link your account" in _speech(body).lower()


@pytest.mark.asyncio
async def test_revoked_token_returns_graceful_unable_to_connect(env):
    """The feature's final step: revoke the token, Alexa gets a graceful reply."""
    body = _intent_body("QueryTodos", token="hearth_pat_deadbeefdeadbeef")
    resp = await _post(env, body)
    assert resp.status_code == 200
    out = resp.json()
    assert _has_link_card(out)
    assert "trouble connecting" in _speech(out).lower()


# ── Intents ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_grocery_item(env):
    resp = await _post(env, _intent_body("AddGroceryItem", {"item": "milk"}))
    assert resp.status_code == 200
    assert "milk" in _speech(resp.json()).lower()
    assert await _count(env["maker"], GroceryItem, name="milk") == 1


@pytest.mark.asyncio
async def test_add_grocery_item_is_idempotent(env):
    await _post(env, _intent_body("AddGroceryItem", {"item": "milk"}))
    second = await _post(env, _intent_body("AddGroceryItem", {"item": "Milk"}))
    assert "already on your shopping list" in _speech(second.json()).lower()
    assert await _count(env["maker"], GroceryItem, name="milk") == 1


@pytest.mark.asyncio
async def test_create_todo(env):
    resp = await _post(env, _intent_body("CreateTodo", {"task": "call the dentist"}))
    assert resp.status_code == 200
    assert "call the dentist" in _speech(resp.json()).lower()
    async with env["maker"]() as db:
        todo = (await db.execute(
            select(Todo).where(Todo.title == "call the dentist")
        )).scalar_one()
        assert todo.visibility == "household"   # voice never writes personal


@pytest.mark.asyncio
async def test_check_in_habit(env):
    resp = await _post(env, _intent_body("CheckInHabit", {"habit": "floss"}))
    assert resp.status_code == 200
    assert "floss" in _speech(resp.json()).lower()
    assert await _count(env["maker"], HabitOccurrence) == 1

    second = await _post(env, _intent_body("CheckInHabit", {"habit": "Floss"}))
    assert "already checked off" in _speech(second.json()).lower()
    assert await _count(env["maker"], HabitOccurrence) == 1   # no double count


@pytest.mark.asyncio
async def test_check_in_unknown_habit(env):
    resp = await _post(env, _intent_body("CheckInHabit", {"habit": "skydiving"}))
    assert "couldn't find" in _speech(resp.json()).lower()
    assert await _count(env["maker"], HabitOccurrence) == 0


@pytest.mark.asyncio
async def test_query_todos_counts_due_today(env):
    resp = await _post(env, _intent_body("QueryTodos"))
    assert resp.status_code == 200
    assert "one to-do due today" in _speech(resp.json()).lower()


@pytest.mark.asyncio
async def test_missing_slot_is_spoken_not_errored(env):
    resp = await _post(env, _intent_body("AddGroceryItem", {}))
    assert resp.status_code == 200
    assert "didn't catch" in _speech(resp.json()).lower()
    assert await _count(env["maker"], GroceryItem) == 0


# ── Built-in intents / request types ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_launch_request_welcomes_and_keeps_session_open(env):
    body = {
        "version": "1.0",
        "context": {"System": {"application": {"applicationId": "amzn1.ask.skill.hearth"}}},
        "request": {"type": "LaunchRequest", "requestId": "r-launch",
                    "timestamp": datetime.now(UTC).isoformat()},
    }
    resp = await _post(env, body)
    out = resp.json()
    assert out["response"]["shouldEndSession"] is False
    assert "hearth" in _speech(out).lower()


@pytest.mark.asyncio
async def test_help_intent(env):
    resp = await _post(env, _intent_body("AMAZON.HelpIntent"))
    out = resp.json()
    assert out["response"]["shouldEndSession"] is False
    assert "shopping list" in _speech(out).lower()


@pytest.mark.asyncio
async def test_stop_intent_ends_session(env):
    resp = await _post(env, _intent_body("AMAZON.StopIntent"))
    out = resp.json()
    assert out["response"]["shouldEndSession"] is True
    assert "goodbye" in _speech(out).lower()


@pytest.mark.asyncio
async def test_unknown_intent_falls_back(env):
    resp = await _post(env, _intent_body("SomethingWeird"))
    assert "didn't catch" in _speech(resp.json()).lower()


# ── Scope + ceiling ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_only_token_cannot_write(env):
    body = _intent_body("AddGroceryItem", {"item": "eggs"}, token="__readonly__")
    body["context"]["System"]["user"]["accessToken"] = env["raw_readonly"]
    resp = await env["client"].post("/voice/alexa", json=body)
    assert resp.status_code == 200
    assert "permission" in _speech(resp.json()).lower()
    assert await _count(env["maker"], GroceryItem, name="eggs") == 0


@pytest.mark.asyncio
async def test_read_only_token_can_query(env):
    body = _intent_body("QueryTodos", token="__readonly__")
    body["context"]["System"]["user"]["accessToken"] = env["raw_readonly"]
    resp = await env["client"].post("/voice/alexa", json=body)
    assert "due today" in _speech(resp.json()).lower()


# ── Audit attribution ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_records_voice_audit_row(env):
    await _post(env, _intent_body("CreateTodo", {"task": "audited todo"}))
    async with env["maker"]() as db:
        row = (await db.execute(
            select(AuditLog).where(AuditLog.entity_type == "todo")
        )).scalar_one()
        assert row.source == "voice"
        assert row.action == "create"
        assert row.actor_user_id == env["alice_id"]
        assert row.token_id is not None


@pytest.mark.asyncio
async def test_deduped_write_records_no_second_audit_row(env):
    await _post(env, _intent_body("CreateTodo", {"task": "once"}))
    await _post(env, _intent_body("CreateTodo", {"task": "once"}))
    assert await _count(env["maker"], AuditLog, entity_type="todo") == 1


# ── applicationId gate (router) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_application_id_rejected(env, monkeypatch):
    from life_dashboard.core.settings import settings
    monkeypatch.setattr(settings, "alexa_skill_id", "amzn1.ask.skill.hearth")
    body = _intent_body("QueryTodos", app_id="amzn1.ask.skill.someone-else")
    resp = await _post(env, body)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_matching_application_id_allowed(env, monkeypatch):
    from life_dashboard.core.settings import settings
    monkeypatch.setattr(settings, "alexa_skill_id", "amzn1.ask.skill.hearth")
    resp = await _post(env, _intent_body("QueryTodos", app_id="amzn1.ask.skill.hearth"))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_malformed_body_rejected(env):
    resp = await env["client"].post("/voice/alexa", json={"nonsense": True})
    assert resp.status_code == 400


# ── Request-verification helpers ──────────────────────────────────────────────

def test_check_application_id():
    signature.check_application_id("skill-a", None)          # no expected → allowed
    signature.check_application_id("skill-a", "skill-a")     # match → allowed
    with pytest.raises(signature.AlexaVerificationError):
        signature.check_application_id("skill-b", "skill-a")


def test_check_timestamp_window():
    now = datetime.now(UTC)
    signature.check_timestamp(now, now=now)                                  # fresh
    signature.check_timestamp(now - timedelta(seconds=100), now=now)         # within 150s
    with pytest.raises(signature.AlexaVerificationError):
        signature.check_timestamp(now - timedelta(seconds=200), now=now)     # stale
    with pytest.raises(signature.AlexaVerificationError):
        signature.check_timestamp(None, now=now)                             # missing


def test_validate_cert_url():
    signature._validate_cert_url("https://s3.amazonaws.com/echo.api/echo-api-cert.pem")
    signature._validate_cert_url("https://s3.amazonaws.com:443/echo.api/x.pem")
    for bad in [
        "http://s3.amazonaws.com/echo.api/x.pem",            # not https
        "https://evil.example.com/echo.api/x.pem",           # wrong host
        "https://s3.amazonaws.com/notecho/x.pem",            # wrong path
        "https://s3.amazonaws.com/echo.api/../evil/x.pem",   # traversal
        "https://s3.amazonaws.com:8080/echo.api/x.pem",      # wrong port
        "",
    ]:
        with pytest.raises(signature.AlexaVerificationError):
            signature._validate_cert_url(bad)


# ── Full signature verification (self-signed cert, mocked S3 fetch) ────────────

_CERT_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"


def _make_cert(*, san="echo-api.amazon.com", not_before=None, not_after=None):
    """A self-signed RSA cert with the given SAN and validity window, plus its
    private key — stands in for Amazon's Alexa signing certificate."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM)


def _sign(key, body: bytes) -> str:
    return base64.b64encode(key.sign(body, rsa_padding.PKCS1v15(), hashes.SHA1())).decode()


def _patch_fetch(monkeypatch, pem: bytes):
    """Redirect signature._load_signing_key's httpx fetch to return `pem`."""
    class _Resp:
        content = pem

        def raise_for_status(self):
            pass

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(signature.httpx, "AsyncClient", _Client)


@pytest.mark.asyncio
async def test_verify_signature_accepts_valid_request(monkeypatch):
    signature._CERT_CACHE.clear()
    key, pem = _make_cert()
    _patch_fetch(monkeypatch, pem)
    body = b'{"request":{"type":"IntentRequest"}}'
    await signature.verify_signature(body, _CERT_URL, _sign(key, body))  # no raise


@pytest.mark.asyncio
async def test_verify_signature_rejects_tampered_body(monkeypatch):
    signature._CERT_CACHE.clear()
    key, pem = _make_cert()
    _patch_fetch(monkeypatch, pem)
    sig = _sign(key, b"original body")
    with pytest.raises(signature.AlexaVerificationError):
        await signature.verify_signature(b"tampered body", _CERT_URL, sig)


@pytest.mark.asyncio
async def test_verify_signature_rejects_expired_cert(monkeypatch):
    signature._CERT_CACHE.clear()
    now = datetime.now(UTC)
    key, pem = _make_cert(not_before=now - timedelta(days=10), not_after=now - timedelta(days=1))
    _patch_fetch(monkeypatch, pem)
    body = b"x"
    with pytest.raises(signature.AlexaVerificationError):
        await signature.verify_signature(body, _CERT_URL, _sign(key, body))


@pytest.mark.asyncio
async def test_verify_signature_rejects_non_alexa_cert(monkeypatch):
    signature._CERT_CACHE.clear()
    key, pem = _make_cert(san="evil.example.com")
    _patch_fetch(monkeypatch, pem)
    body = b"x"
    with pytest.raises(signature.AlexaVerificationError):
        await signature.verify_signature(body, _CERT_URL, _sign(key, body))


@pytest.mark.asyncio
async def test_verify_signature_rejects_bad_base64(monkeypatch):
    signature._CERT_CACHE.clear()
    _key, pem = _make_cert()
    _patch_fetch(monkeypatch, pem)
    with pytest.raises(signature.AlexaVerificationError):
        await signature.verify_signature(b"x", _CERT_URL, "!!! not base64 !!!")


@pytest.mark.asyncio
async def test_expired_cache_entry_is_refetched_and_revalidated(monkeypatch):
    """A cached key past its not_valid_after must not be reused — the cert is
    re-fetched and re-validated, so a request signed by the *fresh* key verifies
    (which is only possible if the stale cached key was dropped)."""
    signature._CERT_CACHE.clear()
    stale_key, _ = _make_cert()
    signature._CERT_CACHE[_CERT_URL] = (
        stale_key.public_key(), datetime.now(UTC) - timedelta(seconds=1)
    )
    fresh_key, pem = _make_cert()
    _patch_fetch(monkeypatch, pem)
    body = b"payload"
    await signature.verify_signature(body, _CERT_URL, _sign(fresh_key, body))
    assert signature._CERT_CACHE[_CERT_URL][1] > datetime.now(UTC)
