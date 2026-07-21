"""Realtime + outbound events for the approval queue (proposal-002).

Two consumers, one descriptor. ``proposal.created`` and ``proposal.decided``
reach the SSE stream (so an open queue updates without a refresh) and the
outbound-webhook worker (so a household can push them to a phone), and both go
through the single scope function every other event goes through —
``events/scope.py can_see``. There is deliberately no second filter here.

**The audience is the interesting part.** A proposal is not household-visible: it
is visible to the household's owners and admins, who decide it, plus the member
who asked for it, who is entitled to know what happened to their own request.
That is exactly the ``members`` visibility rule — creator, plus an explicit share
list — so it is expressed as a visibility descriptor rather than as a bespoke
check:

    visibility            = "members"
    created_by_user_id    = the proposing member (NULL for a household agent)
    shared_with_user_ids  = every owner/admin in the household

Routing is therefore "all admins" (decided 2026-07-20) as a *value*, not as
branching logic. When per-domain approver routing arrives it changes which ids
go in that tuple and nothing else — no consumer, and no scope code, has to move.

A household-agent proposal has no creator, so only admins are told about it. That
is correct: there is no person waiting on the answer, only a device that will
poll ``get_proposal_status``.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import HouseholdMembership, MembershipRole
from life_dashboard.core.visibility import VISIBILITY_MEMBERS
from life_dashboard.events import semantic
from life_dashboard.events.bus import InvalidationEvent
from life_dashboard.events.emit import record_invalidation
from life_dashboard.proposals.labels import label_one
from life_dashboard.proposals.models import Proposal
from life_dashboard.proposals.schemas import ProposalResponse

#: Catalog names. Both are in webhooks/summaries.py — an event absent from that
#: allowlist is published but delivered to nobody.
PROPOSAL_CREATED = "proposal.created"
PROPOSAL_DECIDED = "proposal.decided"

#: The table name the SSE stream sends as the invalidation's ``type``; the web
#: client maps it to the /proposals query prefix.
ENTITY_TYPE = "proposals"

#: Roles that see the household's approval queue. The same set the households
#: router gates admin actions on.
_ADMIN_ROLES = (MembershipRole.owner, MembershipRole.admin)


class _Audience:
    """A visibility descriptor built from a query rather than from a row.

    Structurally identical to what an ORM row offers ``can_see`` — the three
    attribute names are the whole contract (events/scope.py) — so no event
    consumer can tell the difference, and none of them needs to.
    """

    __slots__ = ("visibility", "created_by_user_id", "shared_with_user_ids")

    def __init__(
        self, created_by_user_id: uuid.UUID | None, admin_ids: tuple[str, ...]
    ) -> None:
        self.visibility = VISIBILITY_MEMBERS
        self.created_by_user_id = created_by_user_id
        self.shared_with_user_ids = admin_ids


async def admin_user_ids(db: AsyncSession, household_id: uuid.UUID) -> tuple[str, ...]:
    """Every owner/admin in the household, as strings (how ``can_see`` compares)."""
    rows = (
        await db.execute(
            select(HouseholdMembership.user_id).where(
                HouseholdMembership.household_id == household_id,
                HouseholdMembership.role.in_(_ADMIN_ROLES),
            )
        )
    ).scalars().all()
    return tuple(str(u) for u in rows)


async def can_see_proposal(
    db: AsyncSession, proposal: Proposal, user_id: uuid.UUID
) -> bool:
    """Whether ``user_id`` may see this proposal at all — the REST queue's gate.

    Runs the same ``can_see`` the event path runs, against the same descriptor,
    so "delivered a proposal.created event" and "can open the proposal" can never
    disagree. That equivalence is the point: an event the UI cannot act on is a
    leak, and a proposal the UI can open but was never told about is a bug.
    """
    from life_dashboard.events.scope import can_see

    audience = _Audience(
        proposal.proposed_by_user_id, await admin_user_ids(db, proposal.household_id)
    )
    return can_see(audience, user_id)


def _created_summary(item: ProposalResponse) -> dict:
    return {
        "summary": item.summary,
        "domain": item.domain,
        "tool": item.tool,
        "status": item.status,
        "source": item.source,
        "proposed_by": item.proposed_by_label,
        "expires_at": item.expires_at,
    }


def _decided_summary(item: ProposalResponse) -> dict:
    return {
        "summary": item.summary,
        "domain": item.domain,
        "tool": item.tool,
        "status": item.status,
        "proposed_by": item.proposed_by_label,
        "decided_by": item.decided_by_label,
        "decided_at": item.decided_at,
        "reject_reason": item.reject_reason,
    }


async def record_proposal_event(
    db: AsyncSession, proposal: Proposal, *, event: str
) -> None:
    """Queue the SSE invalidation and the semantic event for one proposal.

    Both ride the existing commit-time plumbing, so a proposal whose transaction
    rolls back announces nothing, and a bus failure never breaks a decision that
    already landed. Call after ``flush()`` and before the commit that makes the
    change durable.
    """
    item = await label_one(db, ProposalResponse.model_validate(proposal))
    audience = _Audience(
        proposal.proposed_by_user_id, await admin_user_ids(db, proposal.household_id)
    )

    semantic.record(
        db,
        event=event,
        entity_type="proposal",
        entity_id=proposal.id,
        household_id=proposal.household_id,
        summary=(
            _created_summary(item) if event == PROPOSAL_CREATED else _decided_summary(item)
        ),
        descriptor_from=audience,
    )

    record_invalidation(
        db,
        InvalidationEvent(
            household_id=proposal.household_id,
            entity_type=ENTITY_TYPE,
            entity_id=proposal.id,
            action="created" if event == PROPOSAL_CREATED else "updated",
            visibility=audience.visibility,
            created_by_user_id=audience.created_by_user_id,
            shared_with_user_ids=audience.shared_with_user_ids,
        ),
    )
