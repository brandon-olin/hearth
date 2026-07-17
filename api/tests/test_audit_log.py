"""Tests for the audit log (security-008).

Covers the two things security-008 owns end-to-end without depending on the
concurrently-built mcp-002 write tools:

  1. audit.service.record faithfully stores an attributed row, including the
     household-agent (actor_user_id NULL) and web-session (token_id NULL) cases.
  2. The @audited decorator records an attributed row for every successful MCP
     write-tool call, re-resolving attribution from the calling PAT.
"""
import types
import uuid

from sqlalchemy import select

from life_dashboard.audit import (
    HOUSEHOLD_AGENT_ROLE,
    AuditSource,
    audited,
    list_audit_log,
    record,
    resolve_actor_user_id,
)
from life_dashboard.audit.models import AuditLog
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_service import create_token

# ── Fixtures ──────────────────────────────────────────────────────────────────

async def _make_member(db):
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
    db.add(HouseholdMembership(
        household_id=household.id, user_id=user.id, role=MembershipRole.owner,
    ))
    await db.commit()
    return household, user


async def _make_pat(db, user, scopes=None):
    token, raw = await create_token(
        db, user_id=user.id, name="Test token",
        scopes=scopes or {"todos": "write"}, expires_in_days=None,
    )
    return token, raw


# ── audit.service.record ──────────────────────────────────────────────────────

async def test_record_writes_all_fields_with_payload_summary(db_session):
    household, user = await _make_member(db_session)
    token, _ = await _make_pat(db_session, user)
    entity_id = uuid.uuid4()

    row = await record(
        db_session,
        household_id=household.id,
        source=AuditSource.mcp,
        action="create",
        entity_type="todo",
        actor_user_id=user.id,
        token_id=token.id,
        entity_id=entity_id,
        payload={"title": "Milk"},
    )
    await db_session.commit()

    fetched = (await db_session.execute(
        select(AuditLog).where(AuditLog.id == row.id)
    )).scalar_one()
    assert fetched.household_id == household.id
    assert fetched.source == "mcp"
    assert fetched.action == "create"
    assert fetched.entity_type == "todo"
    assert fetched.actor_user_id == user.id
    assert fetched.token_id == token.id
    assert fetched.entity_id == str(entity_id)  # uuid coerced to string, no FK
    assert fetched.payload == {"title": "Milk"}
    assert fetched.created_at is not None


async def test_record_web_session_has_null_token(db_session):
    # A logged-in web write: source="web", no token.
    household, user = await _make_member(db_session)

    row = await record(
        db_session,
        household_id=household.id,
        source="web",
        action="update",
        entity_type="todo",
        actor_user_id=user.id,
        token_id=None,
    )
    await db_session.commit()

    assert row.source == "web"
    assert row.token_id is None
    assert row.actor_user_id == user.id


async def test_record_household_agent_has_null_actor(db_session):
    # A shared-device (household-agent pseudo-member) write: attributed to the
    # token alone, no human actor.
    household, user = await _make_member(db_session)
    token, _ = await _make_pat(db_session, user)

    row = await record(
        db_session,
        household_id=household.id,
        source=AuditSource.mcp,
        action="check_in",
        entity_type="habit_occurrence",
        actor_user_id=None,
        token_id=token.id,
    )
    await db_session.commit()

    assert row.actor_user_id is None
    assert row.token_id == token.id


async def test_list_audit_log_scoped_and_newest_first(db_session):
    h1, u1 = await _make_member(db_session)
    h2, u2 = await _make_member(db_session)
    await record(db_session, household_id=h1.id, source="web", action="a", entity_type="todo")
    await record(db_session, household_id=h1.id, source="web", action="b", entity_type="todo")
    await record(db_session, household_id=h2.id, source="web", action="c", entity_type="todo")
    await db_session.commit()

    result = await list_audit_log(db_session, h1.id)
    assert result.total == 2  # h2's row is not visible to h1
    assert {r.action for r in result.items} == {"a", "b"}


# ── resolve_actor_user_id (household-agent contract with mcp-002) ──────────────

def test_resolve_actor_normal_member_is_the_member():
    uid = uuid.uuid4()
    identity = types.SimpleNamespace(user_id=uid, role="member")
    assert resolve_actor_user_id(identity) == uid


def test_resolve_actor_household_agent_is_none():
    identity = types.SimpleNamespace(user_id=uuid.uuid4(), role=HOUSEHOLD_AGENT_ROLE)
    assert resolve_actor_user_id(identity) is None


# ── @audited decorator ────────────────────────────────────────────────────────

class _Ctx:
    """Minimal FastMCP Context stand-in — resolve_pat only reads the Bearer
    header off ctx.request_context.request.headers."""
    def __init__(self, raw_token):
        self.request_context = types.SimpleNamespace(
            request=types.SimpleNamespace(headers={"authorization": f"Bearer {raw_token}"})
        )


def _patch_session(monkeypatch, session):
    """Point the decorator's AsyncSessionLocal at the test session (which it
    imports lazily at call time) without closing the fixture-owned session."""
    class _Ctxmgr:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *exc):
            return False
    monkeypatch.setattr("life_dashboard.core.database.AsyncSessionLocal", lambda: _Ctxmgr())


async def test_audited_records_attributed_row(db_session, monkeypatch):
    household, user = await _make_member(db_session)
    token, raw = await _make_pat(db_session, user, scopes={"todos": "write"})
    _patch_session(monkeypatch, db_session)

    entity_id = uuid.uuid4()

    @audited(action="create", entity_type="todo")
    async def add_todo(ctx, **kwargs):
        # Stands in for an mcp-002 write tool; returns the created entity dict.
        return {"id": str(entity_id), "title": "Milk", "secret_field": "sensitive"}

    result = await add_todo(_Ctx(raw), title="Milk")
    assert result["title"] == "Milk"  # tool result passes through unchanged

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.source == "mcp"
    assert row.action == "create"
    assert row.entity_type == "todo"
    assert row.actor_user_id == user.id     # real member → attributed to member
    assert row.token_id == token.id         # attributed to the calling token
    assert row.entity_id == str(entity_id)  # extracted from result["id"]
    # Payload is a whitelisted summary — the sensitive field is not copied in.
    assert row.payload == {"id": str(entity_id), "title": "Milk"}
    assert "secret_field" not in (row.payload or {})


async def test_audited_failure_does_not_break_the_tool(db_session, monkeypatch):
    # If recording raises, the already-committed write must still return.
    household, user = await _make_member(db_session)
    _, raw = await _make_pat(db_session, user)

    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr("life_dashboard.core.database.AsyncSessionLocal", _boom)

    @audited(action="create", entity_type="todo")
    async def add_todo(ctx, **kwargs):
        return {"id": "abc", "title": "Milk"}

    result = await add_todo(_Ctx(raw))
    assert result == {"id": "abc", "title": "Milk"}  # tool unaffected by audit outage
