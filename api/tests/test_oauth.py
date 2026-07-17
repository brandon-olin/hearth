"""Tests for the OAuth 2.1 layer in front of PATs (security-007).

Covers the five verification steps in feature_list.json:

  1. The authorization-code + PKCE flow with dynamic client registration works.
  2. A completed grant mints a scoped PAT that authorizes *identically* to a
     directly-issued PAT (same get_current_user / _enforce_pat_scope path).
  3. A confidential (Alexa/Google-style) client completes the flow end-to-end
     over HTTP and the resulting token is tied to the household account.
  4. Per-token rate limiting is enforced on the cloud tier (and only there).
  5. Local/self-hosted expose no OAuth surface and still accept a pasted PAT.
"""
import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from life_dashboard.auth import pat_rate_limit
from life_dashboard.auth.dependencies import (
    _enforce_pat_rate_limit,
    _enforce_pat_scope,
)
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_service import authenticate_token
from life_dashboard.core.database import Base
from life_dashboard.core.settings import settings
from life_dashboard.oauth import service
from life_dashboard.oauth.metadata import authorization_server_metadata
from life_dashboard.oauth.models import OAuthAuthorizationCode
from life_dashboard.oauth.router import require_cloud_tier
from life_dashboard.oauth.scopes import OAuthScopeError, parse_scope, to_scope_string
from life_dashboard.oauth.service import OAuthError

# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db, role=MembershipRole.member) -> User:
    household = Household(name="Test Household")
    db.add(household)
    await db.flush()
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="x",
        display_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(HouseholdMembership(household_id=household.id, user_id=user.id, role=role))
    await db.commit()
    user.household_id = household.id
    user.role = role.value
    return user


def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, S256 challenge) satisfying RFC 7636."""
    verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def _register(db, method="none", redirect="https://client.example/cb"):
    return await service.register_client(
        db,
        client_name="Test Client",
        redirect_uris=[redirect],
        token_endpoint_auth_method=method,
        grant_types=["authorization_code"],
        scope=None,
    )


class _FakeURL:
    def __init__(self, path):
        self.path = path


class _FakeRequest:
    def __init__(self, path, method):
        self.url = _FakeURL(path)
        self.method = method


@pytest.fixture(autouse=True)
def _clean_rate_limiter():
    pat_rate_limit.reset()
    yield
    pat_rate_limit.reset()


# ── Scope translation (pure) ───────────────────────────────────────────────────

def test_parse_scope_valid():
    assert parse_scope("todos:write calendar:read") == {
        "todos": "write",
        "calendar": "read",
    }


def test_parse_scope_write_beats_read_for_same_domain():
    assert parse_scope("todos:read todos:write") == {"todos": "write"}


def test_parse_scope_rejects_empty():
    with pytest.raises(OAuthScopeError):
        parse_scope("")
    with pytest.raises(OAuthScopeError):
        parse_scope("   ")
    with pytest.raises(OAuthScopeError):
        parse_scope(None)


def test_parse_scope_rejects_missing_level():
    with pytest.raises(OAuthScopeError, match="domain.*level"):
        parse_scope("todos")


def test_parse_scope_rejects_unknown_domain():
    with pytest.raises(OAuthScopeError, match="Unknown scope domain"):
        parse_scope("nuclear:write")


def test_to_scope_string_roundtrip_is_sorted():
    assert to_scope_string({"todos": "write", "calendar": "read"}) == (
        "calendar:read todos:write"
    )


# ── PKCE verification (pure) ───────────────────────────────────────────────────

def test_pkce_accepts_matching_verifier():
    verifier, challenge = _pkce_pair()
    assert service._verify_pkce(verifier, challenge)


def test_pkce_rejects_wrong_verifier():
    _, challenge = _pkce_pair()
    other, _ = _pkce_pair()
    assert not service._verify_pkce(other, challenge)


def test_pkce_rejects_too_short_verifier():
    # Below the RFC 7636 minimum of 43 chars.
    assert not service._verify_pkce("tooshort", "irrelevant")


def test_pkce_rejects_non_ascii_verifier_without_raising():
    # A non-ASCII verifier of valid length must fail verification, not raise
    # UnicodeEncodeError (which would degrade to a 500 instead of invalid_grant).
    assert not service._verify_pkce("é" * 50, "irrelevant")


@pytest.mark.asyncio
async def test_exchange_non_ascii_verifier_is_oauth_error(db_session):
    """The non-ASCII verifier surfaces as a structured invalid_grant, not a 500."""
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    _verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)
    with pytest.raises(OAuthError, match="PKCE"):
        await service.exchange_code(
            db_session,
            grant_type="authorization_code",
            code=raw_code,
            redirect_uri="https://client.example/cb",
            code_verifier="é" * 50,
            client_id=client.client_id,
            client_secret=None,
            minted_token_expiry_days=None,
        )


# ── Dynamic client registration ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_public_client_has_no_secret(db_session):
    client, secret = await _register(db_session, method="none")
    assert secret is None
    assert client.client_secret_hash is None
    assert client.client_id.startswith("hearth_client_")


@pytest.mark.asyncio
async def test_register_confidential_client_returns_secret_stored_hashed(db_session):
    client, secret = await _register(db_session, method="client_secret_post")
    assert secret is not None and secret.startswith("hearth_secret_")
    # Only the hash is stored — the plaintext is unrecoverable from the row.
    assert client.client_secret_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in (client.client_secret_hash or "")


@pytest.mark.asyncio
async def test_register_rejects_non_https_redirect(db_session):
    with pytest.raises(OAuthError) as exc:
        await _register(db_session, redirect="http://evil.example/cb")
    assert exc.value.error == "invalid_redirect_uri"


@pytest.mark.asyncio
async def test_register_allows_localhost_http_for_dev(db_session):
    client, _ = await _register(db_session, redirect="http://localhost:9000/cb")
    assert client.client_id


@pytest.mark.asyncio
async def test_register_rejects_unsupported_grant_type(db_session):
    with pytest.raises(OAuthError, match="grant_types"):
        await service.register_client(
            db_session,
            client_name="X",
            redirect_uris=["https://c.example/cb"],
            token_endpoint_auth_method="none",
            grant_types=["client_credentials"],
            scope=None,
        )


# ── Authorization request validation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_authorization_request_happy(db_session):
    client, _ = await _register(db_session)
    _, challenge = _pkce_pair()
    got_client, scopes = await service.validate_authorization_request(
        db_session,
        response_type="code",
        client_id=client.client_id,
        redirect_uri="https://client.example/cb",
        scope="todos:write",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    assert got_client.client_id == client.client_id
    assert scopes == {"todos": "write"}


@pytest.mark.asyncio
async def test_validate_rejects_unknown_client(db_session):
    _, challenge = _pkce_pair()
    with pytest.raises(OAuthError, match="Unknown client_id"):
        await service.validate_authorization_request(
            db_session,
            response_type="code",
            client_id="hearth_client_nope",
            redirect_uri="https://client.example/cb",
            scope="todos:read",
            code_challenge=challenge,
            code_challenge_method="S256",
        )


@pytest.mark.asyncio
async def test_validate_rejects_unregistered_redirect(db_session):
    client, _ = await _register(db_session)
    _, challenge = _pkce_pair()
    with pytest.raises(OAuthError, match="redirect_uri"):
        await service.validate_authorization_request(
            db_session,
            response_type="code",
            client_id=client.client_id,
            redirect_uri="https://client.example/OTHER",
            scope="todos:read",
            code_challenge=challenge,
            code_challenge_method="S256",
        )


@pytest.mark.asyncio
async def test_validate_requires_pkce(db_session):
    client, _ = await _register(db_session)
    with pytest.raises(OAuthError, match="code_challenge is required"):
        await service.validate_authorization_request(
            db_session,
            response_type="code",
            client_id=client.client_id,
            redirect_uri="https://client.example/cb",
            scope="todos:read",
            code_challenge=None,
            code_challenge_method="S256",
        )


@pytest.mark.asyncio
async def test_validate_rejects_plain_pkce_method(db_session):
    client, _ = await _register(db_session)
    with pytest.raises(OAuthError, match="S256"):
        await service.validate_authorization_request(
            db_session,
            response_type="code",
            client_id=client.client_id,
            redirect_uri="https://client.example/cb",
            scope="todos:read",
            code_challenge="whatever",
            code_challenge_method="plain",
        )


# ── Full flow: issue code → exchange → scoped PAT ──────────────────────────────

async def _issue_code(db, client, user, scope, challenge, redirect="https://client.example/cb"):
    return await service.issue_authorization_code(
        db,
        client=client,
        user_id=user.id,
        redirect_uri=redirect,
        scope=scope,
        code_challenge=challenge,
        code_challenge_method="S256",
    )


@pytest.mark.asyncio
async def test_full_flow_mints_scoped_pat(db_session):
    """Step 1 + 2: the grant mints a PAT that authorizes like any other PAT."""
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:write", challenge)

    raw_pat, granted_scope, expires_in = await service.exchange_code(
        db_session,
        grant_type="authorization_code",
        code=raw_code,
        redirect_uri="https://client.example/cb",
        code_verifier=verifier,
        client_id=client.client_id,
        client_secret=None,
        minted_token_expiry_days=None,
    )
    assert raw_pat.startswith("hearth_pat_")
    assert granted_scope == "todos:write"
    assert expires_in is None  # None expiry → no expires_in

    # The minted PAT resolves through the ordinary PAT auth path…
    pat = await authenticate_token(db_session, raw_pat)
    assert pat is not None and pat.user_id == user.id
    assert pat.scopes == {"todos": "write"}
    # …and authorizes identically: in-scope write allowed, out-of-scope denied.
    await _enforce_pat_scope(db_session, _FakeRequest("/todos", "POST"), pat, user)
    with pytest.raises(HTTPException) as exc:
        await _enforce_pat_scope(db_session, _FakeRequest("/budget", "GET"), pat, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_oauth_minted_pat_capped_by_member_ceiling(db_session):
    """Step 2, Layer 2: an OAuth grant cannot exceed the consenting member's own
    permissions. A viewer who OAuth-grants todos:write is still refused the write
    when the household caps `create` at member — identical to a directly-created
    PAT (test_token_cannot_exceed_owning_members_permissions)."""
    viewer = await _make_user(db_session, role=MembershipRole.viewer)
    household = await db_session.get(Household, viewer.household_id)
    household.permissions_config = {"todos": {"create": "member"}}
    await db_session.commit()

    client, _ = await _register(db_session)
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, viewer, "todos:write", challenge)
    raw_pat, _scope, _exp = await service.exchange_code(
        db_session,
        grant_type="authorization_code",
        code=raw_code,
        redirect_uri="https://client.example/cb",
        code_verifier=verifier,
        client_id=client.client_id,
        client_secret=None,
        minted_token_expiry_days=None,
    )
    pat = await authenticate_token(db_session, raw_pat)

    # Reads are fine; the write is refused by the member ceiling, not the scope.
    await _enforce_pat_scope(db_session, _FakeRequest("/todos", "GET"), pat, viewer)
    with pytest.raises(HTTPException) as exc:
        await _enforce_pat_scope(db_session, _FakeRequest("/todos", "POST"), pat, viewer)
    assert exc.value.status_code == 403
    assert "cannot exceed" in exc.value.detail


@pytest.mark.asyncio
async def test_minted_pat_respects_expiry_setting(db_session):
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)
    _pat, _scope, expires_in = await service.exchange_code(
        db_session,
        grant_type="authorization_code",
        code=raw_code,
        redirect_uri="https://client.example/cb",
        code_verifier=verifier,
        client_id=client.client_id,
        client_secret=None,
        minted_token_expiry_days=30,
    )
    assert expires_in == 30 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_exchange_rejects_reused_code(db_session):
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)

    args = dict(
        grant_type="authorization_code",
        code=raw_code,
        redirect_uri="https://client.example/cb",
        code_verifier=verifier,
        client_id=client.client_id,
        client_secret=None,
        minted_token_expiry_days=None,
    )
    await service.exchange_code(db_session, **args)
    with pytest.raises(OAuthError, match="already been used"):
        await service.exchange_code(db_session, **args)


@pytest.mark.asyncio
async def test_code_stays_spent_after_mint_failure(db_session, monkeypatch):
    """If PAT minting fails after the code is consumed, the code is not
    resurrected — a replay must not succeed. Enforces single-use even on the
    error path."""
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)

    # Force create_token to fail as if the member were at their token limit.
    from life_dashboard.oauth import service as svc

    async def _boom(*a, **k):
        from life_dashboard.auth.pat_service import PATError
        raise PATError("Token limit reached")

    monkeypatch.setattr(svc, "create_token", _boom)
    args = dict(
        grant_type="authorization_code",
        code=raw_code,
        redirect_uri="https://client.example/cb",
        code_verifier=verifier,
        client_id=client.client_id,
        client_secret=None,
        minted_token_expiry_days=None,
    )
    with pytest.raises(OAuthError, match="limit"):
        await service.exchange_code(db_session, **args)

    # The code is spent — a retry (even with minting restored) is invalid_grant.
    monkeypatch.undo()
    with pytest.raises(OAuthError, match="already been used"):
        await service.exchange_code(db_session, **args)


@pytest.mark.asyncio
async def test_exchange_rejects_wrong_pkce_verifier(db_session):
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    _verifier, challenge = _pkce_pair()
    wrong_verifier, _ = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)

    with pytest.raises(OAuthError, match="PKCE"):
        await service.exchange_code(
            db_session,
            grant_type="authorization_code",
            code=raw_code,
            redirect_uri="https://client.example/cb",
            code_verifier=wrong_verifier,
            client_id=client.client_id,
            client_secret=None,
            minted_token_expiry_days=None,
        )


@pytest.mark.asyncio
async def test_exchange_rejects_expired_code(db_session):
    user = await _make_user(db_session)
    client, _ = await _register(db_session)
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)

    # Force the stored code to be expired.
    code_row = (
        await db_session.execute(
            OAuthAuthorizationCode.__table__.select()
        )
    ).first()
    await db_session.execute(
        OAuthAuthorizationCode.__table__.update()
        .where(OAuthAuthorizationCode.id == code_row.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    with pytest.raises(OAuthError, match="expired"):
        await service.exchange_code(
            db_session,
            grant_type="authorization_code",
            code=raw_code,
            redirect_uri="https://client.example/cb",
            code_verifier=verifier,
            client_id=client.client_id,
            client_secret=None,
            minted_token_expiry_days=None,
        )


@pytest.mark.asyncio
async def test_exchange_rejects_redirect_uri_mismatch(db_session):
    user = await _make_user(db_session)
    client, _ = await service.register_client(
        db_session,
        client_name="X",
        redirect_uris=["https://client.example/cb", "https://client.example/other"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code"],
        scope=None,
    )
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)
    with pytest.raises(OAuthError, match="redirect_uri"):
        await service.exchange_code(
            db_session,
            grant_type="authorization_code",
            code=raw_code,
            redirect_uri="https://client.example/other",  # registered, but not the one used
            code_verifier=verifier,
            client_id=client.client_id,
            client_secret=None,
            minted_token_expiry_days=None,
        )


@pytest.mark.asyncio
async def test_exchange_confidential_client_requires_secret(db_session):
    user = await _make_user(db_session)
    client, secret = await _register(db_session, method="client_secret_post")
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client, user, "todos:read", challenge)

    # Missing/wrong secret is invalid_client (401).
    with pytest.raises(OAuthError) as exc:
        await service.exchange_code(
            db_session,
            grant_type="authorization_code",
            code=raw_code,
            redirect_uri="https://client.example/cb",
            code_verifier=verifier,
            client_id=client.client_id,
            client_secret="hearth_secret_wrong",
            minted_token_expiry_days=None,
        )
    assert exc.value.error == "invalid_client" and exc.value.status_code == 401

    # Correct secret succeeds.
    raw_pat, _scope, _exp = await service.exchange_code(
        db_session,
        grant_type="authorization_code",
        code=raw_code,
        redirect_uri="https://client.example/cb",
        code_verifier=verifier,
        client_id=client.client_id,
        client_secret=secret,
        minted_token_expiry_days=None,
    )
    assert raw_pat.startswith("hearth_pat_")


@pytest.mark.asyncio
async def test_exchange_rejects_code_from_other_client(db_session):
    user = await _make_user(db_session)
    client_a, _ = await _register(db_session)
    client_b, _ = await _register(db_session, redirect="https://b.example/cb")
    verifier, challenge = _pkce_pair()
    raw_code = await _issue_code(db_session, client_a, user, "todos:read", challenge)

    with pytest.raises(OAuthError, match="another client"):
        await service.exchange_code(
            db_session,
            grant_type="authorization_code",
            code=raw_code,
            redirect_uri="https://client.example/cb",
            code_verifier=verifier,
            client_id=client_b.client_id,
            client_secret=None,
            minted_token_expiry_days=None,
        )


# ── Redirect building ──────────────────────────────────────────────────────────

def test_build_redirect_appends_code_and_drops_none():
    url = service.build_redirect(
        "https://client.example/cb", {"code": "abc", "state": None}
    )
    assert url == "https://client.example/cb?code=abc"


def test_build_redirect_uses_ampersand_when_query_present():
    url = service.build_redirect(
        "https://client.example/cb?foo=1", {"code": "abc", "state": "s"}
    )
    assert url == "https://client.example/cb?foo=1&code=abc&state=s"


# ── Per-token rate limiting (step 4) ───────────────────────────────────────────

def test_rate_limit_allows_within_budget():
    tid = uuid.uuid4()
    assert all(pat_rate_limit.check_rate_limit(tid, limit=5, now=1000.0) for _ in range(5))


def test_rate_limit_blocks_over_budget():
    tid = uuid.uuid4()
    for _ in range(3):
        assert pat_rate_limit.check_rate_limit(tid, limit=3, now=1000.0)
    assert not pat_rate_limit.check_rate_limit(tid, limit=3, now=1000.0)


def test_rate_limit_resets_next_window():
    tid = uuid.uuid4()
    for _ in range(3):
        pat_rate_limit.check_rate_limit(tid, limit=3, now=1000.0)
    assert not pat_rate_limit.check_rate_limit(tid, limit=3, now=1000.0)
    # 60s later a fresh window opens.
    assert pat_rate_limit.check_rate_limit(tid, limit=3, now=1060.0)


def test_rate_limit_disabled_when_non_positive():
    tid = uuid.uuid4()
    assert all(pat_rate_limit.check_rate_limit(tid, limit=0, now=1000.0) for _ in range(100))


def test_rate_limit_evicts_idle_tokens_when_window_advances():
    """Counters for tokens that stop calling are pruned at the next window so
    the table stays bounded (OAuth mints a fresh PAT per grant)."""
    idle = uuid.uuid4()
    pat_rate_limit.check_rate_limit(idle, limit=5, now=1000.0)
    assert idle in pat_rate_limit._counters
    # A different token in a later window triggers the sweep; the idle one goes.
    pat_rate_limit.check_rate_limit(uuid.uuid4(), limit=5, now=1120.0)
    assert idle not in pat_rate_limit._counters


@pytest.mark.asyncio
async def test_enforce_rate_limit_noop_off_cloud(db_session, monkeypatch):
    user = await _make_user(db_session)
    from life_dashboard.auth.pat_service import create_token
    pat, _ = await create_token(db_session, user.id, "t", {"todos": "read"}, None)
    monkeypatch.setattr(settings, "deployment_tier", "self_hosted")
    monkeypatch.setattr(settings, "pat_rate_limit_per_minute", 1)
    # Many calls, all fine — the throttle does not apply off the cloud tier.
    for _ in range(10):
        _enforce_pat_rate_limit(pat)


@pytest.mark.asyncio
async def test_enforce_rate_limit_429_on_cloud(db_session, monkeypatch):
    user = await _make_user(db_session)
    from life_dashboard.auth.pat_service import create_token
    pat, _ = await create_token(db_session, user.id, "t", {"todos": "read"}, None)
    monkeypatch.setattr(settings, "deployment_tier", "cloud")
    monkeypatch.setattr(settings, "pat_rate_limit_per_minute", 2)
    _enforce_pat_rate_limit(pat)
    _enforce_pat_rate_limit(pat)
    with pytest.raises(HTTPException) as exc:
        _enforce_pat_rate_limit(pat)
    assert exc.value.status_code == 429


# ── Tier gate (step 5) ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_require_cloud_tier_blocks_local(monkeypatch):
    monkeypatch.setattr(settings, "deployment_tier", "local")
    with pytest.raises(HTTPException) as exc:
        await require_cloud_tier()
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_cloud_tier_allows_cloud(monkeypatch):
    monkeypatch.setattr(settings, "deployment_tier", "cloud")
    assert await require_cloud_tier() is None


def test_metadata_document_shape():
    meta = authorization_server_metadata("https://hearth.example/")
    assert meta["issuer"] == "https://hearth.example"
    assert meta["authorization_endpoint"] == "https://hearth.example/oauth/authorize"
    assert meta["token_endpoint"] == "https://hearth.example/oauth/token"
    assert meta["registration_endpoint"] == "https://hearth.example/oauth/register"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert "todos:write" in meta["scopes_supported"]


# ── End-to-end HTTP: account linking (step 3) ──────────────────────────────────

@pytest_asyncio.fixture
async def cloud_client(monkeypatch):
    """An httpx client bound to the real app, backed by a shared in-memory DB,
    on the cloud tier — the environment a consumer account-linking flow sees."""
    import life_dashboard.main as main_module

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with maker() as session:
            yield session

    from life_dashboard.core.database import get_db

    main_module.app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(settings, "deployment_tier", "cloud")

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="https://hearth.test") as client:
        yield client, maker

    main_module.app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_account_linking_end_to_end(cloud_client):
    """Alexa/Google-style: register a confidential client, walk the browser
    redirect flow, exchange the code, and use the resulting token — proving the
    grant is bound to the consenting household account."""
    client, maker = cloud_client

    # Seed a member with a real session so /oauth/authorize can authenticate.
    async with maker() as db:
        user = await _make_user(db)
        user_id = user.id
    from life_dashboard.auth.tokens import create_access_token

    session_headers = {"Authorization": f"Bearer {create_access_token(str(user_id))}"}

    # 1. Dynamic client registration (public endpoint).
    reg = await client.post(
        "/oauth/register",
        json={
            "client_name": "Alexa Skill",
            "redirect_uris": ["https://layla.amazon.com/api/skill/link/CB"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert reg.status_code == 201, reg.text
    reg_body = reg.json()
    client_id = reg_body["client_id"]
    client_secret = reg_body["client_secret"]
    redirect_uri = "https://layla.amazon.com/api/skill/link/CB"

    verifier, challenge = _pkce_pair()

    # 2. Authorization request — the consent screen data.
    details = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "todos:write grocery:write",
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        headers=session_headers,
    )
    assert details.status_code == 200, details.text
    assert details.json()["client_name"] == "Alexa Skill"

    # 3. User approves → redirect carrying the code.
    decision = await client.post(
        "/oauth/authorize",
        json={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "todos:write grocery:write",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "approved": True,
        },
        headers=session_headers,
    )
    assert decision.status_code == 200, decision.text
    redirect_url = decision.json()["redirect_url"]
    assert redirect_url.startswith(redirect_uri + "?")
    assert "state=xyz" in redirect_url
    # Pull the code out of the redirect the way the platform would.
    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(redirect_url).query)["code"][0]

    # 4. Token exchange (form-encoded, confidential client).
    tok = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    assert tok.status_code == 200, tok.text
    access_token = tok.json()["access_token"]
    assert access_token.startswith("hearth_pat_")
    assert tok.json()["scope"] == "grocery:write todos:write"

    # 5. The token authorizes as a Hearth PAT tied to the seeded household.
    me = await client.get("/todos", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200, me.text
    # And it is scoped: recipes was never granted, so it is refused (deny-by-default).
    denied = await client.get("/recipes", headers={"Authorization": f"Bearer {access_token}"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_authorize_denial_redirects_with_error(cloud_client):
    """A denied consent (approved=False) redirects back with error=access_denied
    and no code — RFC 6749 §4.1.2.1."""
    client, maker = cloud_client
    async with maker() as db:
        user = await _make_user(db)
        user_id = user.id
    from life_dashboard.auth.tokens import create_access_token

    headers = {"Authorization": f"Bearer {create_access_token(str(user_id))}"}
    reg = await client.post(
        "/oauth/register",
        json={"client_name": "C", "redirect_uris": ["https://c.example/cb"]},
    )
    client_id = reg.json()["client_id"]
    _verifier, challenge = _pkce_pair()

    decision = await client.post(
        "/oauth/authorize",
        json={
            "client_id": client_id,
            "redirect_uri": "https://c.example/cb",
            "scope": "todos:read",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "abc",
            "approved": False,
        },
        headers=headers,
    )
    assert decision.status_code == 200, decision.text
    url = decision.json()["redirect_url"]
    assert "error=access_denied" in url
    assert "state=abc" in url
    assert "code=" not in url


@pytest.mark.asyncio
async def test_oauth_endpoints_404_off_cloud(cloud_client, monkeypatch):
    """Step 5: on local/self-hosted the OAuth surface is invisible."""
    client, _ = cloud_client
    monkeypatch.setattr(settings, "deployment_tier", "local")
    reg = await client.post(
        "/oauth/register",
        json={"client_name": "X", "redirect_uris": ["https://c.example/cb"]},
    )
    assert reg.status_code == 404
    meta = await client.get("/.well-known/oauth-authorization-server")
    assert meta.status_code == 404
