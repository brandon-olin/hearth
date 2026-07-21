"""Agent proposals — the propose tier, the model, and audit double-attribution.

Covers proposal-001's verification steps. The shape mirrors test_mcp_server.py:
the tools resolve their own session from ``mcp.server.AsyncSessionLocal``, so the
suite points that name at a StaticPool in-memory engine and drives the real
tools through a fake MCP context.

The load-bearing assertions here are the ones about what did NOT happen — no
todo row when a write was proposed, no second proposal on a retry, no execution
when the proposing credential is dead.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.mcp.server as mcp_server_module
from life_dashboard.audit.models import AuditLog
from life_dashboard.auth.models import (
    Household,
    HouseholdMembership,
    MembershipRole,
    PersonalAccessToken,
    User,
)
from life_dashboard.auth.pat_scopes import check_scope, min_tier, scope_tier, validate_scopes
from life_dashboard.auth.pat_service import create_token, revoke_token
from life_dashboard.core.database import Base
from life_dashboard.core.permissions import (
    merge_with_defaults,
    resolve_permission_tier,
    validate_permissions_config,
)
from life_dashboard.domains.todos.models import Todo
from life_dashboard.mcp.auth import MCPAuthError
from life_dashboard.mcp.pseudo_member import get_or_create_household_agent
from life_dashboard.mcp.server import add_todo
from life_dashboard.proposals import service as proposals_service
from life_dashboard.proposals.models import Proposal
from life_dashboard.proposals.schemas import ProposalStatus

# Todos create is raised to member, but viewers may ASK. This is the household
# config proposal-001 exists to serve: the kid's agent can request a chore, a
# parent decides.
PROPOSE_CONFIG = {"todos": {"read": "viewer", "create": "member", "propose": "viewer"}}


class _FakeCtx:
    """Minimal stand-in for FastMCP's Context — the tool only reads the Bearer
    header off ctx.request_context.request.headers."""

    def __init__(self, raw_token: str | None):
        headers = {"authorization": f"Bearer {raw_token}"} if raw_token else {}
        request = type("Req", (), {"headers": headers})()
        self.request_context = type("RC", (), {"request": request})()


@pytest_asyncio.fixture
async def env(monkeypatch):
    """A household whose todos require approval below member rank.

    Members: Alice (owner, may approve), Kid (viewer, may only propose), and the
    household-agent pseudo-member (role "agent", the anonymous shared device).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mcp_server_module, "AsyncSessionLocal", maker)

    async with maker() as db:
        household = Household(name="The Olins", permissions_config=PROPOSE_CONFIG)
        db.add(household)
        await db.flush()

        alice = User(email="a@x.com", password_hash="x", display_name="Alice", is_active=True)
        kid = User(email="k@x.com", password_hash="x", display_name="Kid", is_active=True)
        db.add_all([alice, kid])
        await db.flush()
        db.add_all([
            HouseholdMembership(
                household_id=household.id, user_id=alice.id, role=MembershipRole.owner
            ),
            HouseholdMembership(
                household_id=household.id, user_id=kid.id, role=MembershipRole.viewer
            ),
        ])
        await db.commit()

        agent = await get_or_create_household_agent(db, household.id)

        # Kid's token asks for full write; the household ceiling is what routes
        # it to propose. This is the min(token, ceiling) case in its natural form.
        kid_token, raw_kid_write = await create_token(
            db, kid.id, "Kid speaker", {"todos": "write"}, None
        )
        # Alice may write outright; her token is scoped to propose. Same tier,
        # bound by the other layer.
        _, raw_alice_propose = await create_token(
            db, alice.id, "Alice propose-only", {"todos": "propose"}, None
        )
        _, raw_alice_write = await create_token(
            db, alice.id, "Alice write", {"todos": "write"}, None
        )
        _, raw_kid_read = await create_token(
            db, kid.id, "Kid read", {"todos": "read"}, None
        )
        agent_token, raw_agent = await create_token(
            db, agent.id, "Kitchen speaker", {"todos": "write"}, None
        )

        ids = {
            "household_id": household.id,
            "alice_id": alice.id,
            "kid_id": kid.id,
            "agent_id": agent.id,
            "kid_token_id": kid_token.id,
            "agent_token_id": agent_token.id,
        }

    yield {
        "maker": maker,
        "raw_kid_write": raw_kid_write,
        "raw_alice_propose": raw_alice_propose,
        "raw_alice_write": raw_alice_write,
        "raw_kid_read": raw_kid_read,
        "raw_agent": raw_agent,
        **ids,
    }
    await engine.dispose()


async def _count(maker, model, **filters) -> int:
    async with maker() as db:
        query = select(func.count()).select_from(model)
        for key, value in filters.items():
            query = query.where(getattr(model, key) == value)
        return (await db.execute(query)).scalar_one()


async def _only_proposal(maker) -> Proposal:
    async with maker() as db:
        rows = (await db.execute(select(Proposal))).scalars().all()
        assert len(rows) == 1, f"expected exactly one proposal, got {len(rows)}"
        return rows[0]


# ── The tier itself: scopes, ceilings, ordering ───────────────────────────────

def test_propose_is_a_valid_token_scope():
    assert validate_scopes({"todos": "propose"}) == {"todos": "propose"}


def test_check_scope_orders_read_propose_write():
    write = {"todos": "write"}
    propose = {"todos": "propose"}
    read = {"todos": "read"}

    # write implies propose implies read
    assert check_scope(write, "todos", "write")
    assert check_scope(write, "todos", "propose")
    assert check_scope(write, "todos", "read")

    assert check_scope(propose, "todos", "propose")
    assert check_scope(propose, "todos", "read")
    # …but propose is NOT write. A propose-scoped token hitting a REST write
    # path is refused — branching REST writes to the queue is proposal-003.
    assert not check_scope(propose, "todos", "write")

    assert check_scope(read, "todos", "read")
    assert not check_scope(read, "todos", "propose")
    assert not check_scope(read, "todos", "write")


def test_unknown_scope_value_grants_nothing():
    """Scopes are JSONB; an unrecognised value must read as no grant, never as a
    grant of unknown strength."""
    assert scope_tier({"todos": "superuser"}, "todos") == "none"
    assert not check_scope({"todos": "superuser"}, "todos", "read")


def test_min_tier_is_the_effective_permission():
    assert min_tier("write", "propose") == "propose"
    assert min_tier("propose", "write") == "propose"
    assert min_tier("read", "write") == "read"


def test_permissions_config_accepts_propose():
    validated = validate_permissions_config(PROPOSE_CONFIG)
    assert validated["todos"]["propose"] == "viewer"
    assert validated["todos"]["create"] == "member"


def test_existing_config_never_resolves_to_propose():
    """The backward-compatibility guarantee: a household that has not set
    `propose` resolves exactly as it did before this build."""
    merged = merge_with_defaults(None)
    for domain, actions in merged.items():
        assert "propose" not in actions, f"{domain} gained an unrequested propose tier"

    # A viewer under default config may create todos outright — still "write",
    # not the new middle tier.
    assert resolve_permission_tier(merged, "todos", "create", "viewer") == "write"

    # And a viewer denied create with no propose threshold gets nothing, not
    # a silently-upgraded ability to ask.
    strict = merge_with_defaults({"todos": {"create": "owner"}})
    assert resolve_permission_tier(strict, "todos", "create", "viewer") == "none"


def test_propose_threshold_resolves_the_middle_tier():
    merged = merge_with_defaults(PROPOSE_CONFIG)
    assert resolve_permission_tier(merged, "todos", "create", "viewer") == "propose"
    assert resolve_permission_tier(merged, "todos", "create", "member") == "write"


# ── Tool behaviour at each tier ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_tier_records_a_proposal_and_writes_nothing(env):
    result = await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")

    assert result["status"] == "proposed"
    assert uuid.UUID(result["proposal_id"])
    assert "not yet done" in result["message"]
    assert result["expires_at"] is not None

    # The whole point: nothing was written.
    assert await _count(env["maker"], Todo) == 0

    proposal = await _only_proposal(env["maker"])
    assert proposal.status == ProposalStatus.pending.value
    assert proposal.tool == "add_todo"
    assert proposal.domain == "todos"
    assert proposal.args["title"] == "Take out the bins"
    assert proposal.source == "mcp"
    assert proposal.proposed_by_user_id == env["kid_id"]
    assert proposal.token_id == env["kid_token_id"]


@pytest.mark.asyncio
async def test_write_tier_still_executes_immediately(env):
    """The propose tier must not intercept a genuine write — an existing
    write-scoped token behaves exactly as it did before this build."""
    result = await add_todo(_FakeCtx(env["raw_alice_write"]), title="Book the dentist")

    assert result.get("status") != "proposed"
    assert result["created"] is True
    assert result["title"] == "Book the dentist"
    assert await _count(env["maker"], Todo) == 1
    assert await _count(env["maker"], Proposal) == 0


@pytest.mark.asyncio
async def test_read_only_token_errors_and_does_not_become_a_proposal(env):
    """A read-scoped token was granted no right to ask. It must fail, not
    quietly acquire a new capability."""
    with pytest.raises(MCPAuthError):
        await add_todo(_FakeCtx(env["raw_kid_read"]), title="Sneaky write")

    assert await _count(env["maker"], Proposal) == 0
    assert await _count(env["maker"], Todo) == 0


@pytest.mark.asyncio
async def test_effective_permission_is_min_token_ceiling(env):
    """Both directions of min(token, ceiling) land on propose."""
    # token=write, ceiling=propose (the kid)
    kid_result = await add_todo(_FakeCtx(env["raw_kid_write"]), title="Kid asks")
    assert kid_result["status"] == "proposed"

    # token=propose, ceiling=write (Alice, an owner)
    alice_result = await add_todo(_FakeCtx(env["raw_alice_propose"]), title="Alice asks")
    assert alice_result["status"] == "proposed"

    assert await _count(env["maker"], Todo) == 0
    assert await _count(env["maker"], Proposal) == 2


# ── Idempotency ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_identical_args_return_the_same_proposal(env):
    ctx = _FakeCtx(env["raw_kid_write"])
    first = await add_todo(ctx, title="Take out the bins")
    second = await add_todo(ctx, title="Take out the bins")

    assert first["proposal_id"] == second["proposal_id"]
    assert await _count(env["maker"], Proposal) == 1


@pytest.mark.asyncio
async def test_different_args_are_different_proposals(env):
    ctx = _FakeCtx(env["raw_kid_write"])
    first = await add_todo(ctx, title="Take out the bins")
    second = await add_todo(ctx, title="Feed the cat")

    assert first["proposal_id"] != second["proposal_id"]
    assert await _count(env["maker"], Proposal) == 2


# ── Scope isolation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_proposal_is_invisible_to_another_proposer(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Kid's ask")
    proposal = await _only_proposal(env["maker"])

    async with env["maker"]() as db:
        # Alice's own view of "her" proposals excludes the kid's.
        assert await proposals_service.get_proposal(
            db, env["household_id"], proposal.id, proposed_by_user_id=env["alice_id"]
        ) is None
        mine = await proposals_service.list_proposals(
            db, env["household_id"], proposed_by_user_id=env["alice_id"]
        )
        assert mine.total == 0

        # The kid's own view finds it.
        assert await proposals_service.get_proposal(
            db, env["household_id"], proposal.id, token_id=env["kid_token_id"]
        ) is not None


@pytest.mark.asyncio
async def test_a_proposal_never_crosses_a_household_boundary(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Kid's ask")
    proposal = await _only_proposal(env["maker"])

    async with env["maker"]() as db:
        other_household = Household(name="Someone else")
        db.add(other_household)
        await db.commit()

        assert await proposals_service.get_proposal(
            db, other_household.id, proposal.id
        ) is None
        with pytest.raises(proposals_service.ProposalError):
            await proposals_service.approve_proposal(
                db,
                proposal_id=proposal.id,
                household_id=other_household.id,
                approver_user_id=env["alice_id"],
                approver_role="owner",
            )
    assert await _count(env["maker"], Todo) == 0


# ── Approval ──────────────────────────────────────────────────────────────────

async def _approve(env, proposal_id, *, user_id=None, role="owner"):
    async with env["maker"]() as db:
        return await proposals_service.approve_proposal(
            db,
            proposal_id=proposal_id,
            household_id=env["household_id"],
            approver_user_id=user_id or env["alice_id"],
            approver_role=role,
        )


@pytest.mark.asyncio
async def test_approval_executes_the_write_and_records_both_actors(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")
    proposal = await _only_proposal(env["maker"])

    approved = await _approve(env, proposal.id)

    assert approved.status == ProposalStatus.approved.value
    assert approved.decided_by_user_id == env["alice_id"]
    assert approved.decided_at is not None
    assert approved.result_entity_id is not None

    async with env["maker"]() as db:
        todo = (await db.execute(select(Todo))).scalar_one()
        assert todo.title == "Take out the bins"
        assert str(todo.id) == approved.result_entity_id

        rows = (await db.execute(select(AuditLog))).scalars().all()

    proposed_by = [r for r in rows if r.entity_type == "todo"]
    approved_by = [r for r in rows if r.action == "approve"]

    # TWO distinguishable facts, not one collapsed actor.
    assert len(proposed_by) == 1
    assert len(approved_by) == 1

    # Fact 1 — the agent/token that asked, linked to the proposal.
    assert proposed_by[0].actor_user_id == env["kid_id"]
    assert proposed_by[0].token_id == env["kid_token_id"]
    assert proposed_by[0].payload["via_proposal"] == str(proposal.id)

    # Fact 2 — the human who said yes. No token, and a different actor.
    assert approved_by[0].actor_user_id == env["alice_id"]
    assert approved_by[0].token_id is None
    assert approved_by[0].actor_user_id != proposed_by[0].actor_user_id
    assert approved_by[0].payload["proposed_by_token_id"] == str(env["kid_token_id"])


@pytest.mark.asyncio
async def test_household_agent_proposal_attributes_the_token_not_the_approver(env):
    """An anonymous shared device has no human actor, so the token IS the
    attribution. It must never collapse into "the approver did it"."""
    await add_todo(_FakeCtx(env["raw_agent"]), title="Speaker asked for milk run")
    proposal = await _only_proposal(env["maker"])

    # The household-agent pseudo-member is attributed to its token alone.
    assert proposal.proposed_by_user_id is None
    assert proposal.token_id == env["agent_token_id"]

    await _approve(env, proposal.id)

    async with env["maker"]() as db:
        rows = (await db.execute(select(AuditLog))).scalars().all()

    proposed_by = next(r for r in rows if r.entity_type == "todo")
    approved_by = next(r for r in rows if r.action == "approve")

    assert proposed_by.actor_user_id is None          # no human proposed it…
    assert proposed_by.token_id == env["agent_token_id"]  # …but the device is named
    assert approved_by.actor_user_id == env["alice_id"]


@pytest.mark.asyncio
async def test_approved_entity_is_identical_to_a_direct_write(env):
    """Approval must run the SAME service function as the direct path — so the
    row it produces is indistinguishable from one the tool created outright."""
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Proposed task")
    proposal = await _only_proposal(env["maker"])
    await _approve(env, proposal.id)

    await add_todo(_FakeCtx(env["raw_alice_write"]), title="Direct task")

    async with env["maker"]() as db:
        todos = {
            t.title: t for t in (await db.execute(select(Todo))).scalars().all()
        }

    proposed, direct = todos["Proposed task"], todos["Direct task"]
    for field in ("household_id", "visibility", "status", "priority", "due_date"):
        assert getattr(proposed, field) == getattr(direct, field), field
    # Attribution is the one honest difference: the proposer owns their request.
    assert proposed.created_by_user_id == env["kid_id"]
    assert direct.created_by_user_id == env["alice_id"]


@pytest.mark.asyncio
async def test_approval_is_revalidated_against_the_approver(env):
    """Approval is the approver's own act: it needs write on the domain,
    regardless of what the proposer's ceiling was."""
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")
    proposal = await _only_proposal(env["maker"])

    # The kid may propose but not create — so they may not approve either,
    # including their own request.
    with pytest.raises(proposals_service.ProposalError, match="do not have permission"):
        await _approve(env, proposal.id, user_id=env["kid_id"], role="viewer")

    assert await _count(env["maker"], Todo) == 0
    async with env["maker"]() as db:
        still_pending = await proposals_service.get_proposal(
            db, env["household_id"], proposal.id
        )
    assert still_pending.status == ProposalStatus.pending.value

    # An admin holding write approves successfully.
    approved = await _approve(env, proposal.id, role="admin")
    assert approved.status == ProposalStatus.approved.value
    assert await _count(env["maker"], Todo) == 1


@pytest.mark.asyncio
async def test_second_decision_loses_rather_than_executing_twice(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")
    proposal = await _only_proposal(env["maker"])

    await _approve(env, proposal.id)
    with pytest.raises(proposals_service.ProposalError, match="already approved"):
        await _approve(env, proposal.id)

    assert await _count(env["maker"], Todo) == 1


# ── Stale proposer guard ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_refuses_a_revoked_token(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")
    proposal = await _only_proposal(env["maker"])

    async with env["maker"]() as db:
        assert await revoke_token(db, env["kid_id"], env["kid_token_id"])

    with pytest.raises(proposals_service.ProposalError, match="has been revoked"):
        await _approve(env, proposal.id)

    # Nothing executed, and the proposal is retired with the reason.
    assert await _count(env["maker"], Todo) == 0
    async with env["maker"]() as db:
        refused = await proposals_service.get_proposal(db, env["household_id"], proposal.id)
    assert refused.status == ProposalStatus.expired.value
    assert "revoked" in refused.reject_reason


@pytest.mark.asyncio
async def test_a_null_token_id_is_not_mistaken_for_a_revoked_one(env):
    """The reason proposals.token_id must not cascade to NULL. A household-agent
    proposal legitimately has no *human* proposer, and a web-UI proposal
    (proposal-003) will legitimately have no token — neither may be read as
    "the credential was revoked", or the guard fails open in the other
    direction and blocks valid approvals."""
    await add_todo(_FakeCtx(env["raw_agent"]), title="Speaker asked for milk run")
    proposal = await _only_proposal(env["maker"])
    assert proposal.proposed_by_user_id is None
    assert proposal.token_id is not None

    approved = await _approve(env, proposal.id)
    assert approved.status == ProposalStatus.approved.value


@pytest.mark.asyncio
async def test_approval_refuses_a_proposer_who_left_the_household(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")
    proposal = await _only_proposal(env["maker"])

    async with env["maker"]() as db:
        membership = (
            await db.execute(
                select(HouseholdMembership).where(HouseholdMembership.user_id == env["kid_id"])
            )
        ).scalar_one()
        await db.delete(membership)
        await db.commit()

    with pytest.raises(proposals_service.ProposalError, match="no longer in this household"):
        await _approve(env, proposal.id)

    assert await _count(env["maker"], Todo) == 0
    async with env["maker"]() as db:
        refused = await proposals_service.get_proposal(db, env["household_id"], proposal.id)
    assert refused.status == ProposalStatus.expired.value


@pytest.mark.asyncio
async def test_token_id_survives_revocation_in_the_row(env):
    """Revocation is soft, so the FK target still exists and token_id keeps
    naming the credential. This is what makes the guard able to tell the two
    NULL-vs-revoked states apart at all."""
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Take out the bins")
    async with env["maker"]() as db:
        await revoke_token(db, env["kid_id"], env["kid_token_id"])
        proposal = (await db.execute(select(Proposal))).scalar_one()
        token = (
            await db.execute(
                select(PersonalAccessToken).where(
                    PersonalAccessToken.id == env["kid_token_id"]
                )
            )
        ).scalar_one()

    assert proposal.token_id == env["kid_token_id"]
    assert token.revoked_at is not None


# ── Rejection ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rejection_persists_a_reason_the_agent_can_read(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Buy a trampoline")
    proposal = await _only_proposal(env["maker"])

    async with env["maker"]() as db:
        rejected = await proposals_service.reject_proposal(
            db,
            proposal_id=proposal.id,
            household_id=env["household_id"],
            approver_user_id=env["alice_id"],
            approver_role="owner",
            reason="Not this month — ask again after the holiday.",
        )
    assert rejected.status == ProposalStatus.rejected.value
    assert await _count(env["maker"], Todo) == 0

    # Retrievable by the proposing agent, scoped to its own token.
    async with env["maker"]() as db:
        seen = await proposals_service.get_proposal(
            db, env["household_id"], proposal.id, token_id=env["kid_token_id"]
        )
    assert seen.reject_reason == "Not this month — ask again after the holiday."
    assert seen.decided_by_user_id == env["alice_id"]


@pytest.mark.asyncio
async def test_asking_again_after_a_rejection_is_a_new_proposal(env):
    """The pending-only uniqueness: a fresh ask after a "no" is a new request,
    not a duplicate of the decided one."""
    ctx = _FakeCtx(env["raw_kid_write"])
    first = await add_todo(ctx, title="Buy a trampoline")

    async with env["maker"]() as db:
        await proposals_service.reject_proposal(
            db,
            proposal_id=uuid.UUID(first["proposal_id"]),
            household_id=env["household_id"],
            approver_user_id=env["alice_id"],
            approver_role="owner",
            reason="No.",
        )

    second = await add_todo(ctx, title="Buy a trampoline")
    assert second["proposal_id"] != first["proposal_id"]
    assert await _count(env["maker"], Proposal) == 2


# ── Expiry sweep ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_expires_only_overdue_pending_proposals(env):
    ctx = _FakeCtx(env["raw_kid_write"])
    stale = await add_todo(ctx, title="Stale ask")
    fresh = await add_todo(ctx, title="Fresh ask")
    decided = await add_todo(ctx, title="Decided ask")

    async with env["maker"]() as db:
        await proposals_service.reject_proposal(
            db,
            proposal_id=uuid.UUID(decided["proposal_id"]),
            household_id=env["household_id"],
            approver_user_id=env["alice_id"],
            approver_role="owner",
            reason="No.",
        )
        # Backdate one past its deadline.
        row = (
            await db.execute(
                select(Proposal).where(Proposal.id == uuid.UUID(stale["proposal_id"]))
            )
        ).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        assert await proposals_service.sweep_expired_proposals(db) == 1

        statuses = {
            str(p.id): p.status for p in (await db.execute(select(Proposal))).scalars().all()
        }

    assert statuses[stale["proposal_id"]] == ProposalStatus.expired.value
    assert statuses[fresh["proposal_id"]] == ProposalStatus.pending.value
    # A decided proposal is never in scope — the sweep cannot resurrect or
    # overwrite a human's decision.
    assert statuses[decided["proposal_id"]] == ProposalStatus.rejected.value


@pytest.mark.asyncio
async def test_running_the_sweep_twice_changes_nothing(env):
    stale = await add_todo(_FakeCtx(env["raw_kid_write"]), title="Stale ask")

    async with env["maker"]() as db:
        row = (await db.execute(select(Proposal))).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        assert await proposals_service.sweep_expired_proposals(db) == 1
        first_reason = (
            await proposals_service.get_proposal(
                db, env["household_id"], uuid.UUID(stale["proposal_id"])
            )
        ).reject_reason

        # Second pass matches nothing: the rows it would touch are no longer
        # pending.
        assert await proposals_service.sweep_expired_proposals(db) == 0
        after = await proposals_service.get_proposal(
            db, env["household_id"], uuid.UUID(stale["proposal_id"])
        )

    assert after.status == ProposalStatus.expired.value
    assert after.reject_reason == first_reason


@pytest.mark.asyncio
async def test_expired_proposal_cannot_be_approved(env):
    await add_todo(_FakeCtx(env["raw_kid_write"]), title="Stale ask")
    async with env["maker"]() as db:
        row = (await db.execute(select(Proposal))).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        await proposals_service.sweep_expired_proposals(db)
        proposal_id = row.id

    with pytest.raises(proposals_service.ProposalError, match="already expired"):
        await _approve(env, proposal_id)
    assert await _count(env["maker"], Todo) == 0
