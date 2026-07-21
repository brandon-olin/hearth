"""The approval queue — Hearth's answer to "an agent wants to do this" (proposal-002).

Mounted at ``/proposals``. Deliberately mapped to NO PAT scope domain (see
auth/pat_scopes.py): the deny-by-default path rule means a personal access token
cannot reach these routes at all, which is how "approving stays human/UI-only"
is enforced structurally rather than by a check somebody has to remember. An
agent approving its own proposals would defeat the entire mechanism, and a voice
device — whose identity proves where a request came from, never who spoke — must
never be an approval surface either. Both fall out of the same one line.

Agents still get a read surface: ``list_my_proposals`` and ``get_proposal_status``
over MCP, confined to the proposals the calling token itself submitted.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.proposals import events as proposal_events
from life_dashboard.proposals import service
from life_dashboard.proposals.labels import label_one
from life_dashboard.proposals.schemas import (
    PROPOSAL_STATUS_VALUES,
    ProposalListResponse,
    ProposalRejectRequest,
    ProposalResponse,
)

router = APIRouter(prefix="/proposals", tags=["proposals"])

#: Returned when a member asks for a proposal they may not see. Identical for
#: "does not exist" and "not yours" on purpose — the difference is itself
#: information about another member's activity.
_NOT_FOUND = "Proposal not found."


def _bad_status(value: str) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Unknown status {value!r}. Valid values: "
            f"{', '.join(PROPOSAL_STATUS_VALUES)}. Omit it for all four."
        ),
    )


@router.get("", response_model=ProposalListResponse)
async def list_proposals(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalListResponse:
    """The approval queue as this member sees it.

    An owner/admin gets the household's whole queue — that is what makes
    first-to-decide-wins meaningful. Anyone else gets only the proposals they
    submitted themselves.
    """
    if status is not None and status not in PROPOSAL_STATUS_VALUES:
        raise _bad_status(status)
    return await service.list_queue(
        db,
        current_user.household_id,
        current_user.id,
        current_user.role,
        status=status,
        limit=limit,
        offset=offset,
    )


async def _visible_or_404(
    db: AsyncSession, proposal_id: uuid.UUID, current_user: User
):
    """Load a proposal this member is entitled to see, or 404.

    Runs the same ``can_see`` the SSE and webhook paths run, against the same
    audience descriptor — so "was told about it" and "may open it" cannot drift
    apart.
    """
    proposal = await service.get_proposal(db, current_user.household_id, proposal_id)
    if proposal is None or not await proposal_events.can_see_proposal(
        db, proposal, current_user.id
    ):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
        )
    return proposal


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """One proposal, including its decision if it has one.

    A second admin opening an already-decided proposal reads the decision and who
    made it here — the UI has everything it needs to show that instead of an
    approve button that would fail.
    """
    proposal = await _visible_or_404(db, proposal_id, current_user)
    return await label_one(db, ProposalResponse.model_validate(proposal))


@router.post("/{proposal_id}/approve", response_model=ProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """Approve a pending proposal: execute its write, attributed to both parties.

    409 rather than 404 when someone already decided it — the proposal exists and
    the caller may see it; what failed is that they were second. The message says
    so, because "first decision wins" is only fair if the loser is told.
    """
    await _visible_or_404(db, proposal_id, current_user)
    try:
        decided = await service.approve_proposal(
            db,
            proposal_id=proposal_id,
            household_id=current_user.household_id,
            approver_user_id=current_user.id,
            approver_role=current_user.role,
        )
    except service.ProposalError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return await label_one(db, ProposalResponse.model_validate(decided))


@router.post("/{proposal_id}/reject", response_model=ProposalResponse)
async def reject_proposal(
    proposal_id: uuid.UUID,
    data: ProposalRejectRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """Decline a pending proposal, with a reason the proposing agent can read.

    The reason is the product feature, not a formality: it is what lets an agent
    tell its user *why* rather than going silent.
    """
    await _visible_or_404(db, proposal_id, current_user)
    try:
        decided = await service.reject_proposal(
            db,
            proposal_id=proposal_id,
            household_id=current_user.household_id,
            approver_user_id=current_user.id,
            approver_role=current_user.role,
            reason=data.reason if data else None,
        )
    except service.ProposalError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return await label_one(db, ProposalResponse.model_validate(decided))
