"""Tests for personal access tokens (security-006).

Covers the two things that make PATs safe to hand to an agent:
  1. The secret is never recoverable from the DB.
  2. A token authorizes strictly less than its owning member — scope ∩ ceiling,
    with deny-by-default for any path not explicitly mapped.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from life_dashboard.auth.dependencies import _enforce_pat_scope
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_scopes import (
    PAT_TOKEN_PREFIX,
    action_for_method,
    check_scope,
    is_pat,
    resolve_required_scope,
    validate_scopes,
)
from life_dashboard.auth.pat_service import (
    MAX_TOKENS_PER_USER,
    PATError,
    _hash_token,
    authenticate_token,
    create_token,
    list_tokens,
    revoke_token,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


class _FakeURL:
    def __init__(self, path):
        self.path = path


class _FakeRequest:
    """Minimal stand-in — _enforce_pat_scope only reads url.path and method."""
    def __init__(self, path, method):
        self.url = _FakeURL(path)
        self.method = method


# ── Scope vocabulary (pure) ───────────────────────────────────────────────────

def test_validate_scopes_rejects_unknown_domain():
    with pytest.raises(ValueError, match="Unknown scope domain"):
        validate_scopes({"nuclear_launch": "write"})


def test_validate_scopes_rejects_bad_access_level():
    with pytest.raises(ValueError, match="Invalid access level"):
        validate_scopes({"todos": "admin"})


def test_validate_scopes_rejects_empty():
    # A token granting nothing would authenticate but authorize nothing.
    with pytest.raises(ValueError):
        validate_scopes({})


def test_validate_scopes_accepts_valid():
    assert validate_scopes({"todos": "write", "calendar": "read"}) == {
        "todos": "write",
        "calendar": "read",
    }


def test_action_for_method():
    assert action_for_method("GET") == "read"
    assert action_for_method("HEAD") == "read"
    assert action_for_method("POST") == "write"
    assert action_for_method("PATCH") == "write"
    assert action_for_method("DELETE") == "write"


def test_write_scope_implies_read():
    assert check_scope({"todos": "write"}, "todos", "read")
    assert check_scope({"todos": "write"}, "todos", "write")


def test_read_scope_does_not_imply_write():
    assert check_scope({"todos": "read"}, "todos", "read")
    assert not check_scope({"todos": "read"}, "todos", "write")


def test_ungranted_domain_denied():
    assert not check_scope({"todos": "write"}, "budget", "read")
    assert not check_scope({}, "todos", "read")
    # JSONB may predate a vocabulary change — must not raise.
    assert not check_scope(None, "todos", "read")


def test_resolve_required_scope_maps_paths():
    assert resolve_required_scope("/todos", "GET") == ("todos", "read")
    assert resolve_required_scope("/todos/abc-123", "PATCH") == ("todos", "write")
    assert resolve_required_scope("/grocery-lists", "POST") == ("grocery", "write")
    assert resolve_required_scope("/events/1", "GET") == ("calendar", "read")


def test_resolve_required_scope_denies_unmapped_paths():
    """Deny-by-default is what keeps a PAT out of /auth — the escalation path."""
    assert resolve_required_scope("/auth/tokens", "POST") is None
    assert resolve_required_scope("/auth/me/password", "PATCH") is None
    assert resolve_required_scope("/ai/chat", "POST") is None
    assert resolve_required_scope("/setup", "POST") is None
    assert resolve_required_scope("/uploads", "POST") is None


def test_resolve_required_scope_does_not_prefix_match_loosely():
    """"/todos-archive" must not be authorized by the "/todos" scope."""
    assert resolve_required_scope("/todos-archive", "GET") is None


def test_is_pat_detects_prefix():
    assert is_pat(f"{PAT_TOKEN_PREFIX}abc")
    assert not is_pat("eyJhbGciOiJIUzI1NiJ9.abc.def")


# ── Creation and storage ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_token_returns_raw_once_and_stores_only_hash(db_session):
    user = await _make_user(db_session)
    token, raw = await create_token(
        db_session, user.id, "Kitchen speaker", {"todos": "write"}, expires_in_days=365
    )

    assert raw.startswith(PAT_TOKEN_PREFIX)
    # The plaintext must not be recoverable from the stored row.
    assert token.token_hash == _hash_token(raw)
    assert raw not in token.token_hash
    assert not hasattr(token, "token")
    # The display prefix is a fragment, not the secret.
    assert token.prefix.startswith(PAT_TOKEN_PREFIX)
    assert token.prefix != raw
    assert raw.startswith(token.prefix)
    assert len(token.prefix) < len(raw)


@pytest.mark.asyncio
async def test_create_token_rejects_invalid_scopes(db_session):
    user = await _make_user(db_session)
    with pytest.raises(PATError):
        await create_token(db_session, user.id, "Bad", {"nope": "write"}, None)


@pytest.mark.asyncio
async def test_tokens_are_unique_per_creation(db_session):
    user = await _make_user(db_session)
    _, raw1 = await create_token(db_session, user.id, "A", {"todos": "read"}, None)
    _, raw2 = await create_token(db_session, user.id, "B", {"todos": "read"}, None)
    assert raw1 != raw2


@pytest.mark.asyncio
async def test_token_limit_enforced(db_session):
    user = await _make_user(db_session)
    for i in range(MAX_TOKENS_PER_USER):
        await create_token(db_session, user.id, f"T{i}", {"todos": "read"}, None)
    with pytest.raises(PATError, match="limit reached"):
        await create_token(db_session, user.id, "one too many", {"todos": "read"}, None)


# ── Authentication ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticate_valid_token(db_session):
    user = await _make_user(db_session)
    token, raw = await create_token(db_session, user.id, "A", {"todos": "read"}, 365)

    found = await authenticate_token(db_session, raw)
    assert found is not None
    assert found.id == token.id
    assert found.user_id == user.id


@pytest.mark.asyncio
async def test_authenticate_updates_last_used_at(db_session):
    user = await _make_user(db_session)
    token, raw = await create_token(db_session, user.id, "A", {"todos": "read"}, 365)
    assert token.last_used_at is None

    found = await authenticate_token(db_session, raw)
    assert found.last_used_at is not None


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_token(db_session):
    await _make_user(db_session)
    assert await authenticate_token(db_session, f"{PAT_TOKEN_PREFIX}not-a-real-token") is None


@pytest.mark.asyncio
async def test_authenticate_rejects_revoked_token(db_session):
    user = await _make_user(db_session)
    token, raw = await create_token(db_session, user.id, "A", {"todos": "read"}, 365)

    assert await revoke_token(db_session, user.id, token.id) is True
    assert await authenticate_token(db_session, raw) is None


@pytest.mark.asyncio
async def test_authenticate_rejects_expired_token(db_session):
    user = await _make_user(db_session)
    token, raw = await create_token(db_session, user.id, "A", {"todos": "read"}, 1)

    token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    assert await authenticate_token(db_session, raw) is None


@pytest.mark.asyncio
async def test_never_expiring_token_authenticates(db_session):
    user = await _make_user(db_session)
    _, raw = await create_token(db_session, user.id, "A", {"todos": "read"}, expires_in_days=None)
    found = await authenticate_token(db_session, raw)
    assert found is not None
    assert found.expires_at is None


# ── Listing and revocation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tokens_excludes_revoked_and_other_users(db_session):
    user = await _make_user(db_session)
    other = await _make_user(db_session)

    keep, _ = await create_token(db_session, user.id, "Keep", {"todos": "read"}, None)
    gone, _ = await create_token(db_session, user.id, "Gone", {"todos": "read"}, None)
    await create_token(db_session, other.id, "Theirs", {"todos": "read"}, None)
    await revoke_token(db_session, user.id, gone.id)

    listed = await list_tokens(db_session, user.id)
    assert [t.id for t in listed] == [keep.id]


@pytest.mark.asyncio
async def test_cannot_revoke_another_users_token(db_session):
    user = await _make_user(db_session)
    attacker = await _make_user(db_session)
    token, raw = await create_token(db_session, user.id, "Victim", {"todos": "read"}, None)

    # IDOR: knowing the UUID must not be enough.
    assert await revoke_token(db_session, attacker.id, token.id) is False
    assert await authenticate_token(db_session, raw) is not None


@pytest.mark.asyncio
async def test_revoke_is_idempotent(db_session):
    user = await _make_user(db_session)
    token, _ = await create_token(db_session, user.id, "A", {"todos": "read"}, None)

    assert await revoke_token(db_session, user.id, token.id) is True
    first = (await db_session.get(type(token), token.id)).revoked_at
    # Second revoke reports False and must not move the timestamp.
    assert await revoke_token(db_session, user.id, token.id) is False
    assert (await db_session.get(type(token), token.id)).revoked_at == first


# ── Request authorization (scope ∩ member ceiling) ────────────────────────────

@pytest.mark.asyncio
async def test_in_scope_request_allowed(db_session):
    user = await _make_user(db_session)
    pat, _ = await create_token(db_session, user.id, "A", {"todos": "write"}, None)
    await _enforce_pat_scope(db_session, _FakeRequest("/todos", "POST"), pat, user)


@pytest.mark.asyncio
async def test_out_of_scope_domain_is_403(db_session):
    user = await _make_user(db_session)
    pat, _ = await create_token(db_session, user.id, "A", {"todos": "write"}, None)

    with pytest.raises(HTTPException) as exc:
        await _enforce_pat_scope(db_session, _FakeRequest("/budget", "GET"), pat, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_write_with_read_only_scope_is_403(db_session):
    user = await _make_user(db_session)
    pat, _ = await create_token(db_session, user.id, "A", {"todos": "read"}, None)

    await _enforce_pat_scope(db_session, _FakeRequest("/todos", "GET"), pat, user)
    with pytest.raises(HTTPException) as exc:
        await _enforce_pat_scope(db_session, _FakeRequest("/todos", "POST"), pat, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unmapped_path_is_403_even_with_broad_scopes(db_session):
    """The escalation case: a leaked token must not be able to mint tokens."""
    user = await _make_user(db_session)
    pat, _ = await create_token(
        db_session, user.id, "A", {"todos": "write", "household": "write"}, None
    )

    for path in ("/auth/tokens", "/ai/chat", "/uploads"):
        with pytest.raises(HTTPException) as exc:
            await _enforce_pat_scope(db_session, _FakeRequest(path, "POST"), pat, user)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_token_cannot_exceed_owning_members_permissions(db_session):
    """A viewer's token gets 403 on a write the viewer couldn't do themselves,
    even though the token itself was granted write."""
    viewer = await _make_user(db_session, role=MembershipRole.viewer)

    # Household config: only members and above may create todos.
    household = await db_session.get(Household, viewer.household_id)
    household.permissions_config = {"todos": {"create": "member"}}
    await db_session.commit()

    pat, _ = await create_token(db_session, viewer.id, "Kid speaker", {"todos": "write"}, None)

    # Reads are still fine — the ceiling only bites on the write.
    await _enforce_pat_scope(db_session, _FakeRequest("/todos", "GET"), pat, viewer)

    with pytest.raises(HTTPException) as exc:
        await _enforce_pat_scope(db_session, _FakeRequest("/todos", "POST"), pat, viewer)
    assert exc.value.status_code == 403
    assert "cannot exceed" in exc.value.detail


@pytest.mark.asyncio
async def test_member_ceiling_allows_what_member_can_do(db_session):
    """Same household config, but an owner's token — the write goes through."""
    owner = await _make_user(db_session, role=MembershipRole.owner)
    household = await db_session.get(Household, owner.household_id)
    household.permissions_config = {"todos": {"create": "member"}}
    await db_session.commit()

    pat, _ = await create_token(db_session, owner.id, "My laptop", {"todos": "write"}, None)
    await _enforce_pat_scope(db_session, _FakeRequest("/todos", "POST"), pat, owner)
