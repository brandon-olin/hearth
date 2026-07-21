"""Proposal lifecycle — record, approve, reject, expire (proposal-001).

Everything that mutates a proposal lives here; the MCP write tools and (from
proposal-002) the approval queue are both thin callers. Approval is the
interesting one: it re-validates against the **approver**, guards the proposing
credential, replays the original write through the same service function the
direct path uses, and leaves two distinguishable audit facts behind.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.audit import service as audit_service
from life_dashboard.audit.schemas import AuditSource
from life_dashboard.auth.models import HouseholdMembership, PersonalAccessToken
from life_dashboard.auth.pat_scopes import SCOPE_TO_PERMISSION_DOMAIN
from life_dashboard.core.permissions import load_household_permissions, resolve_permission_tier
from life_dashboard.core.settings import settings
from life_dashboard.proposals import events as proposal_events
from life_dashboard.proposals.executors import run_executor
from life_dashboard.proposals.labels import attach_labels
from life_dashboard.proposals.models import Proposal
from life_dashboard.proposals.schemas import ProposalListResponse, ProposalResponse, ProposalStatus

logger = logging.getLogger(__name__)


# ── Agent- and human-facing copy ──────────────────────────────────────────────
#
# Tool descriptions and error messages are agent UX (root CLAUDE.md). The
# failure mode this copy exists to prevent is an agent reading `status:
# proposed` as an error and apologising to its user for a failure that did not
# happen — so it states plainly that the action is pending, names who decides,
# and says what to do next.

PROPOSED_MESSAGE = (
    "Saved as a pending request — not yet done. This household requires "
    "approval for this action, and its admins have been notified. Tell the user "
    "their request is waiting on approval; do not retry or try another tool. "
    "Check back with get_proposal_status(proposal_id)."
)

REVOKED_TOKEN_REASON = (
    "Can't approve this — the token that requested it has been revoked. Ask for "
    "the action again from a current device."
)

DEPARTED_PROPOSER_REASON = (
    "Can't approve this — the member who requested it is no longer in this "
    "household. Ask for the action again from a current account."
)

NO_EXECUTOR_REASON = (
    "Can't approve this — the action it asks for no longer exists in this "
    "version of Hearth, so it cannot be carried out as requested."
)

#: proposal-002. Never a bare 404: an agent that gets one goes silent, which is
#: exactly the failure this whole track exists to prevent. Name the problem, give
#: the two plausible causes, and say which tool to call next.
UNKNOWN_PROPOSAL_MESSAGE = (
    "No proposal with that id belongs to this token. It may have been submitted "
    "by a different member or device, or it may have expired and been cleaned "
    "up. Call list_my_proposals to see the proposals you can check."
)

#: The valid ``status`` values, with what each one means, for every message that
#: has to enumerate them. Written once so the tool description, the filter error,
#: and the docs cannot drift apart.
STATUS_VOCABULARY = (
    "pending (awaiting a decision), approved (executed), rejected (declined, "
    "with a reason), expired (nobody decided before expires_at)"
)


def unknown_status_message(value: str) -> str:
    """Refusal copy for a status filter outside the vocabulary."""
    return (
        f"Unknown status {value!r}. Valid values: {STATUS_VOCABULARY}. "
        "Omit status to get all four."
    )


def status_message(item: ProposalResponse) -> str:
    """What happened to this proposal, written for the agent to relay.

    The contract is behavioural, not cosmetic. Each branch answers three
    questions an agent otherwise guesses at: has the action happened, what should
    it tell its user, and should it try again. "Do not resubmit" is stated
    explicitly on the two statuses where a retry is the tempting mistake —
    pending (because an identical ask returns this same proposal, so retrying
    looks like nothing happening) and rejected (because a "no" is an answer).
    """
    who = item.decided_by_label or "a household admin"
    if item.status == ProposalStatus.pending.value:
        return (
            "Still waiting on a human decision — the household's admins have it, "
            "and nothing has been done yet. Tell the user their request is "
            "pending. Do not resubmit it: an identical request returns this same "
            f"proposal rather than creating a second one. It expires on "
            f"{item.expires_at.date().isoformat()} if nobody decides by then."
        )
    if item.status == ProposalStatus.approved.value:
        return (
            f"Approved by {who} — the action has been carried out. Nothing "
            "further is needed from you; tell the user it is done."
        )
    if item.status == ProposalStatus.rejected.value:
        reason = item.reject_reason or "No reason given."
        return (
            f"Declined by {who}. The reason given was: “{reason}” — relay that to "
            "the user in your own words rather than quoting it verbatim, and do "
            "not resubmit the same request."
        )
    reason = item.reject_reason or "It expired before anyone decided it."
    return (
        f"No longer actionable: {reason} Nothing was done. Tell the user, and "
        "ask them whether they still want it before requesting it again."
    )


class ProposalError(Exception):
    """A proposal could not be recorded or decided. The message is written for
    the human approver (or the agent, for the record path) and is safe to
    surface verbatim."""


# ── Recording ─────────────────────────────────────────────────────────────────

def _jsonable(value: Any) -> Any:
    """Coerce a tool argument into something JSON (and therefore ``args``) can
    hold, without losing information the executor needs to replay it.

    Dates and datetimes become ISO-8601 strings; the Pydantic schemas on the
    replay side parse those back to the same objects, so a round trip is lossless.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def serialize_args(args: dict[str, Any]) -> dict[str, Any]:
    """The stored form of a would-be service call. Keys with a ``None`` value are
    kept — an explicitly-null argument is part of the call."""
    return {k: _jsonable(v) for k, v in args.items()}


def fingerprint(
    tool: str,
    args: dict[str, Any],
    proposed_by_user_id: uuid.UUID | None,
    token_id: uuid.UUID | None,
) -> str:
    """Stable digest identifying "this exact request from this exact proposer".

    The proposer columns are folded into the hash rather than added to the unique
    index because both are nullable, and SQL NULLs never compare equal — two
    household-agent proposals would both slip past a NULL-bearing unique index.
    Inside the digest they dedupe correctly.

    ``sort_keys`` makes keyword order irrelevant, so the same call written two
    ways is one proposal.
    """
    material = json.dumps(
        {
            "tool": tool,
            "args": args,
            "proposed_by_user_id": str(proposed_by_user_id) if proposed_by_user_id else None,
            "token_id": str(token_id) if token_id else None,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def record_proposal(
    db: AsyncSession,
    *,
    household_id: uuid.UUID,
    proposed_by_user_id: uuid.UUID | None,
    token_id: uuid.UUID | None,
    source: AuditSource | str,
    domain: str,
    tool: str,
    args: dict[str, Any],
    summary: str,
    expiry_days: int | None = None,
) -> tuple[Proposal, bool]:
    """Record a pending proposal, or return the identical one already pending.

    Returns ``(proposal, created)``. Idempotent the way every other write in this
    codebase is: a retried tool call, a double-tapped voice command, or an agent
    re-asking after a timeout all converge on one row. The uniqueness is enforced
    by a partial unique index and the ``IntegrityError`` re-read below, not by a
    check-then-insert — the gap between those two queries is a real race window
    (api/CLAUDE.md, Pattern C).

    The index is partial on ``status = 'pending'``, so asking again *after* a
    rejection or expiry creates a fresh proposal. That is intended: a new ask
    after a "no" is a new request, not a duplicate of the old one.
    """
    stored_args = serialize_args(args)
    digest = fingerprint(tool, stored_args, proposed_by_user_id, token_id)

    existing = await _find_pending_by_fingerprint(db, household_id, digest)
    if existing is not None:
        return existing, False

    days = expiry_days if expiry_days is not None else settings.proposal_expiry_days
    proposal = Proposal(
        household_id=household_id,
        proposed_by_user_id=proposed_by_user_id,
        token_id=token_id,
        source=source.value if isinstance(source, AuditSource) else source,
        domain=domain,
        tool=tool,
        args=stored_args,
        args_fingerprint=digest,
        summary=summary[:500],
        status=ProposalStatus.pending.value,
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    db.add(proposal)
    try:
        await db.flush()
    except IntegrityError:
        # Lost the race to a concurrent identical request. Roll back before
        # touching the session again — SQLAlchemy leaves it unusable otherwise.
        await db.rollback()
        winner = await _find_pending_by_fingerprint(db, household_id, digest)
        if winner is None:  # pragma: no cover — only if the constraint changes
            raise
        return winner, False

    # Only a genuinely new proposal announces itself. A deduped ask is the same
    # pending request the admins were already told about, and notifying them
    # again per retry would train them to ignore the queue.
    await proposal_events.record_proposal_event(
        db, proposal, event=proposal_events.PROPOSAL_CREATED
    )
    await db.commit()
    await db.refresh(proposal)
    return proposal, True


async def _find_pending_by_fingerprint(
    db: AsyncSession, household_id: uuid.UUID, digest: str
) -> Proposal | None:
    return (
        await db.execute(
            select(Proposal).where(
                Proposal.household_id == household_id,
                Proposal.args_fingerprint == digest,
                Proposal.status == ProposalStatus.pending.value,
            )
        )
    ).scalar_one_or_none()


def proposed_response(proposal: Proposal) -> dict[str, Any]:
    """The tool contract for a write that became a proposal.

    This is the *only* way a write tool's behaviour changes at the propose tier,
    and the message is part of the contract — not a placeholder — so agents
    relay it as a pending request rather than reporting a failure.
    """
    return {
        "status": "proposed",
        "proposal_id": str(proposal.id),
        "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
        "message": PROPOSED_MESSAGE,
    }


# ── Reading ───────────────────────────────────────────────────────────────────

async def get_proposal(
    db: AsyncSession,
    household_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    token_id: uuid.UUID | None = None,
    proposed_by_user_id: uuid.UUID | None = None,
) -> Proposal | None:
    """One proposal, always household-scoped.

    Pass ``token_id`` and/or ``proposed_by_user_id`` to additionally require that
    the proposal belongs to that proposer — how an agent is confined to its own
    proposals and can never read another member's. Omit both for the approver's
    view, which sees the whole household queue by design.
    """
    query = select(Proposal).where(
        Proposal.id == proposal_id,
        Proposal.household_id == household_id,
    )
    if token_id is not None:
        query = query.where(Proposal.token_id == token_id)
    if proposed_by_user_id is not None:
        query = query.where(Proposal.proposed_by_user_id == proposed_by_user_id)
    return (await db.execute(query)).scalar_one_or_none()


async def list_proposals(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    status: str | None = None,
    token_id: uuid.UUID | None = None,
    proposed_by_user_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ProposalListResponse:
    """Household-scoped proposals, newest first. Same proposer filters as
    :func:`get_proposal`."""
    filters = [Proposal.household_id == household_id]
    if status is not None:
        filters.append(Proposal.status == status)
    if token_id is not None:
        filters.append(Proposal.token_id == token_id)
    if proposed_by_user_id is not None:
        filters.append(Proposal.proposed_by_user_id == proposed_by_user_id)

    total = (
        await db.execute(select(func.count()).select_from(Proposal).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Proposal)
            .where(*filters)
            .order_by(Proposal.created_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
    ).scalars().all()

    items = [ProposalResponse.model_validate(r) for r in rows]
    await attach_labels(db, items)
    return ProposalListResponse(items=items, total=total, limit=limit, offset=offset)


# ── The approval queue (proposal-002) ─────────────────────────────────────────

#: Roles that see the whole household's queue and may decide it. Routing is "all
#: admins" and first-to-decide wins (decided 2026-07-20); per-domain approver
#: routing is v2 and lands in permissions_config, not in the schema.
APPROVER_ROLES = frozenset({"owner", "admin"})


def is_approver_role(role: str | None) -> bool:
    """True if this membership role sees the household's approval queue."""
    return (role or "") in APPROVER_ROLES


async def list_queue(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ProposalListResponse:
    """The proposals *this member* may see, which is not the same list for everyone.

    An owner/admin sees the household's whole queue — that is what makes
    first-to-decide-wins work. Anybody else sees only what they themselves asked
    for, because a restricted member is entitled to know what happened to their
    own request and to nothing else. Both cases stay household-scoped.

    This is the REST mirror of the event audience in proposals/events.py; the two
    must agree, or the UI would either render rows nobody was told about or
    receive events for rows it cannot open.
    """
    if is_approver_role(role):
        return await list_proposals(
            db, household_id, status=status, limit=limit, offset=offset
        )
    return await list_proposals(
        db,
        household_id,
        status=status,
        proposed_by_user_id=user_id,
        limit=limit,
        offset=offset,
    )


# ── Deciding ──────────────────────────────────────────────────────────────────

async def _load_pending_for_decision(
    db: AsyncSession, household_id: uuid.UUID, proposal_id: uuid.UUID
) -> Proposal:
    """Return a pending proposal, or explain why it cannot be decided.

    This read is for validation and for a good error message only. The decision
    itself is claimed atomically by :func:`_claim_pending` — the gap between this
    check and that claim is a race window, and the claim is what closes it.
    """
    proposal = (
        await db.execute(
            select(Proposal).where(
                Proposal.id == proposal_id, Proposal.household_id == household_id
            )
        )
    ).scalar_one_or_none()

    if proposal is None:
        raise ProposalError(
            "No proposal with that id in this household. It may have been "
            "decided and cleaned up, or it belongs to another household."
        )
    if proposal.status != ProposalStatus.pending.value:
        raise ProposalError(
            f"This proposal was already {proposal.status} — first decision wins. "
            "Refresh the queue to see who decided it."
        )
    return proposal


async def _require_approver_write(
    db: AsyncSession, proposal: Proposal, approver_role: str
) -> None:
    """Re-validate against the APPROVER's own ceiling, requiring ``write``.

    Approval is the approver's act, so it is their ceiling that governs. The
    proposer's ceiling already did its job — it is what routed the call to
    propose in the first place — and re-checking it here would let a proposer's
    later demotion silently void a decision an admin legitimately made.

    Domains with no configurable household permission are governed by the
    routers' own role gates, exactly as in ``mcp.auth._within_member_ceiling``;
    mirroring that here keeps one answer to "may this member write this domain".
    """
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(proposal.domain)
    if permission_domain is None:
        return

    permissions = await load_household_permissions(db, proposal.household_id)
    tier = resolve_permission_tier(permissions, permission_domain, "create", approver_role)
    if tier != "write":
        raise ProposalError(
            f"You do not have permission to create in {permission_domain}, so you "
            "cannot approve this request. Ask a household admin to decide it."
        )


async def _resolve_proposer(
    db: AsyncSession, proposal: Proposal
) -> tuple[uuid.UUID, str, PersonalAccessToken | None]:
    """The proposer's ``(user_id, role, token)``, or refuse on a dead credential.

    This is the stale-proposer guard, and it exists on audit-integrity grounds
    rather than permission grounds: executing a write attributed to a revoked
    token or a departed member would break the "Joey's speaker proposed it; Mom
    approved it" story that double-attribution exists to tell.

    It works only because ``proposals.token_id`` does not cascade to NULL. Under
    ``ON DELETE SET NULL`` a revoked token and a household-agent's legitimately
    absent token are the same value, and this check would wave both through.
    """
    token: PersonalAccessToken | None = None
    if proposal.token_id is not None:
        token = (
            await db.execute(
                select(PersonalAccessToken).where(PersonalAccessToken.id == proposal.token_id)
            )
        ).scalar_one_or_none()
        if token is None or token.revoked_at is not None:
            raise ProposalError(REVOKED_TOKEN_REASON)

    proposer_user_id = proposal.proposed_by_user_id or (token.user_id if token else None)
    if proposer_user_id is None:
        raise ProposalError(DEPARTED_PROPOSER_REASON)

    membership = (
        await db.execute(
            select(HouseholdMembership).where(
                HouseholdMembership.user_id == proposer_user_id,
                HouseholdMembership.household_id == proposal.household_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise ProposalError(DEPARTED_PROPOSER_REASON)

    return proposer_user_id, membership.role.value, token


_ALREADY_DECIDED = (
    "This proposal was decided by someone else a moment ago — first decision "
    "wins. Refresh the queue to see who decided it."
)


async def _claim_pending(
    db: AsyncSession,
    proposal: Proposal,
    *,
    new_status: str,
    approver_user_id: uuid.UUID,
) -> None:
    """Atomically move a proposal out of ``pending``, or raise if someone beat us.

    ``UPDATE … WHERE status = 'pending' RETURNING id`` (api/CLAUDE.md, Pattern B):
    exactly one of two concurrent approvals updates a row, and the loser is told
    so rather than executing the write a second time. A lock held across the
    executor would not survive it — the executor's own service call commits, and
    that releases the lock — so the claim, not a lock, is the guard.
    """
    claimed = (
        await db.execute(
            update(Proposal)
            .where(Proposal.id == proposal.id, Proposal.status == ProposalStatus.pending.value)
            .values(
                status=new_status,
                decided_by_user_id=approver_user_id,
                decided_at=datetime.now(UTC),
            )
            .returning(Proposal.id)
        )
    ).scalar_one_or_none()
    await db.commit()
    if claimed is None:
        raise ProposalError(_ALREADY_DECIDED)
    await db.refresh(proposal)


async def _release_claim(db: AsyncSession, proposal: Proposal) -> None:
    """Return a claimed proposal to ``pending`` after its write failed to land."""
    await db.rollback()
    await db.execute(
        update(Proposal)
        .where(Proposal.id == proposal.id, Proposal.status == ProposalStatus.approved.value)
        .values(status=ProposalStatus.pending.value, decided_by_user_id=None, decided_at=None)
    )
    await db.commit()


async def _refuse(
    db: AsyncSession, proposal: Proposal, approver_user_id: uuid.UUID, reason: str
) -> None:
    """Retire a proposal that can never legitimately execute.

    Refusals land in ``expired`` rather than ``rejected``: nobody declined the
    request on its merits, the credential behind it died. The reason names which.
    """
    proposal.status = ProposalStatus.expired.value
    proposal.reject_reason = reason
    proposal.decided_by_user_id = approver_user_id
    proposal.decided_at = datetime.now(UTC)
    await proposal_events.record_proposal_event(
        db, proposal, event=proposal_events.PROPOSAL_DECIDED
    )
    await db.commit()


async def approve_proposal(
    db: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    household_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    approver_role: str,
) -> Proposal:
    """Approve a pending proposal: execute its write and record who did what.

    Order matters. The approver's permission is checked before anything is
    executed; the proposing credential is checked before the write is attributed
    to it; and the proposal is only marked approved once the write has actually
    landed.

    Two audit facts are left behind, deliberately as two rows rather than one
    conflated actor:

    1. **proposed_by** — written by the executor itself, through the very same
       ``record_mcp_write`` the direct write path uses, attributed to the
       proposer (``actor_user_id`` NULL + ``token_id`` set for a household
       agent) and tagged with ``via_proposal``.
    2. **approved_by** — written here, attributed to the human, naming the tool
       and the entity their approval brought into existence.

    A proposal whose replay dedupes into an existing entity records only (2):
    no new entity came into being, so there is no new write to attribute. The
    proposal row itself remains the durable record of who asked.
    """
    from life_dashboard.mcp.auth import PatIdentity  # local: mcp imports this module

    proposal = await _load_pending_for_decision(db, household_id, proposal_id)

    await _require_approver_write(db, proposal, approver_role)

    try:
        proposer_user_id, proposer_role, _token = await _resolve_proposer(db, proposal)
    except ProposalError as exc:
        await _refuse(db, proposal, approver_user_id, str(exc))
        raise

    # Claim it before executing. Everything above is a pure check, so losing the
    # claim here costs nothing; executing before claiming could run the write
    # twice for two admins who both pressed approve.
    await _claim_pending(
        db, proposal, new_status=ProposalStatus.approved.value, approver_user_id=approver_user_id
    )

    proposer_identity = PatIdentity(
        user_id=proposer_user_id,
        household_id=proposal.household_id,
        household_name=None,
        role=proposer_role,
        pat_id=proposal.token_id,
        via_proposal_id=proposal.id,
    )

    try:
        result = await run_executor(
            db, proposal.tool, proposer_identity, dict(proposal.args or {})
        )
    except Exception:
        # The write did not land, so the claim must not stand — release it and
        # let the household try again rather than stranding an "approved"
        # proposal that never executed.
        await _release_claim(db, proposal)
        raise
    if result is None:
        await _refuse(db, proposal, approver_user_id, NO_EXECUTOR_REASON)
        raise ProposalError(NO_EXECUTOR_REASON)

    # Most tools return the created entity under "id"; finish_workout_session
    # returns a summary keyed by "session_id". Anything else records no id
    # rather than guessing at one.
    raw_id = result.get("id") or result.get("session_id")
    result_entity_id = str(raw_id) if raw_id is not None else None
    proposal.result_entity_id = result_entity_id

    # Fact 2 — the human's act. Distinct action, distinct entity_type, and no
    # token: nothing here can be confused with the proposer's row.
    await audit_service.record(
        db,
        household_id=proposal.household_id,
        actor_user_id=approver_user_id,
        token_id=None,
        source=AuditSource.web,
        action="approve",
        entity_type="proposal",
        entity_id=proposal.id,
        payload={
            "tool": proposal.tool,
            "domain": proposal.domain,
            "summary": proposal.summary,
            "proposed_by_user_id": (
                str(proposal.proposed_by_user_id) if proposal.proposed_by_user_id else None
            ),
            "proposed_by_token_id": str(proposal.token_id) if proposal.token_id else None,
            "result_entity_id": result_entity_id,
        },
    )
    await proposal_events.record_proposal_event(
        db, proposal, event=proposal_events.PROPOSAL_DECIDED
    )
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def reject_proposal(
    db: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    household_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    approver_role: str,
    reason: str | None = None,
) -> Proposal:
    """Decline a pending proposal, with a reason the proposing agent can read.

    Gated on the same ``write`` ceiling as approval — declining on the
    household's behalf is as much the approver's act as accepting.
    """
    proposal = await _load_pending_for_decision(db, household_id, proposal_id)
    await _require_approver_write(db, proposal, approver_role)
    await _claim_pending(
        db, proposal, new_status=ProposalStatus.rejected.value, approver_user_id=approver_user_id
    )

    proposal.reject_reason = (reason or "No reason given.")[:500]

    await audit_service.record(
        db,
        household_id=proposal.household_id,
        actor_user_id=approver_user_id,
        token_id=None,
        source=AuditSource.web,
        action="reject",
        entity_type="proposal",
        entity_id=proposal.id,
        payload={
            "tool": proposal.tool,
            "domain": proposal.domain,
            "summary": proposal.summary,
            "reject_reason": proposal.reject_reason,
        },
    )
    await proposal_events.record_proposal_event(
        db, proposal, event=proposal_events.PROPOSAL_DECIDED
    )
    await db.commit()
    await db.refresh(proposal)
    return proposal


# ── Expiry sweep ──────────────────────────────────────────────────────────────

async def sweep_expired_proposals(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Move pending proposals past ``expires_at`` to ``expired``. Returns the count.

    A single guarded UPDATE, so it is idempotent by construction: the second run
    matches nothing because the first already moved those rows out of
    ``pending``, and a decided proposal is never in scope to begin with. No
    approval, rejection, or refusal can be resurrected or double-processed by
    running this twice. ``RETURNING`` makes the *events* idempotent for free —
    the second run returns no ids, so it announces nothing.

    Timing out is a decision the queue has to hear about, the same as a rejection
    is: without an event, an open queue would keep offering an approve button for
    a proposal that can no longer be approved.
    """
    expired_ids = list((
        await db.execute(
            update(Proposal)
            .where(
                Proposal.status == ProposalStatus.pending.value,
                Proposal.expires_at <= (now or datetime.now(UTC)),
            )
            .values(
                status=ProposalStatus.expired.value,
                reject_reason=(
                    "Expired — nobody in the household decided this before it timed out."
                ),
            )
            .returning(Proposal.id)
        )
    ).scalars().all())

    if expired_ids:
        # populate_existing: the bulk UPDATE above bypasses the identity map, so
        # a row already loaded in this session would otherwise report its stale
        # pre-sweep status in the event payload.
        rows = (
            await db.execute(
                select(Proposal)
                .where(Proposal.id.in_(expired_ids))
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
        for row in rows:
            await proposal_events.record_proposal_event(
                db, row, event=proposal_events.PROPOSAL_DECIDED
            )

    await db.commit()
    return len(expired_ids)


async def run_proposal_expiry_sweep() -> int:
    """Scheduler entry point: sweep in a session of its own and log the result."""
    from life_dashboard.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        expired = await sweep_expired_proposals(db)
    if expired:
        logger.info("Proposal expiry sweep: %d pending proposal(s) expired", expired)
    return expired
