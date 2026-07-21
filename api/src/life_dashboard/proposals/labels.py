"""Display labels for the approval queue (proposal-002).

An approval decision is only as good as the question it answers, and the question
is "who asked for this?". A row that says *someone* wants to add a chore for Lisa
is not decidable; "Joey's agent, from the kitchen speaker" is.

Two facts make that label, and both may be absent:

* the **member** who proposed it — NULL for a household-agent pseudo-member,
  which is not a person and must never be rendered as one;
* the **device**, i.e. the name on the personal access token that submitted it.
  This is the only identity a shared speaker has.

Resolution is batched: one query per identifier kind for a whole page of
proposals, never one per row (.claude/rules/performance.md).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import PersonalAccessToken, User
from life_dashboard.proposals.schemas import ProposalResponse

#: Shown when a proposal came from a household-agent token that has since been
#: hard-deleted. Deliberately vague rather than wrong — the proposal itself
#: cannot be approved in that state (the stale-proposer guard refuses it), so the
#: label only has to be honest about not knowing.
UNKNOWN_DEVICE = "A household device"

#: Shown when the proposing member's account is gone. Same reasoning.
UNKNOWN_MEMBER = "A former member"


def _display(user: User) -> str:
    """A member's human name, falling back to the local part of their email."""
    return user.display_name or user.email.split("@")[0]


async def _users_by_id(
    db: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(wanted)))).scalars().all()
    return {u.id: _display(u) for u in rows}


async def _tokens_by_id(
    db: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(PersonalAccessToken).where(PersonalAccessToken.id.in_(wanted))
        )
    ).scalars().all()
    return {t.id: t.name for t in rows}


async def attach_labels(db: AsyncSession, items: Sequence[ProposalResponse]) -> None:
    """Fill in ``proposed_by_label`` / ``proposed_via_label`` / ``decided_by_label``.

    Mutates in place, because the alternative — rebuilding every response object
    — buys nothing. Two queries total regardless of page size.
    """
    if not items:
        return

    users = await _users_by_id(
        db,
        [i.proposed_by_user_id for i in items] + [i.decided_by_user_id for i in items],
    )
    tokens = await _tokens_by_id(db, [i.token_id for i in items])

    for item in items:
        device = tokens.get(item.token_id) if item.token_id else None
        if item.proposed_by_user_id is not None:
            item.proposed_by_label = users.get(item.proposed_by_user_id, UNKNOWN_MEMBER)
        else:
            # No member behind it: the device IS the proposer's whole identity.
            item.proposed_by_label = device or UNKNOWN_DEVICE
        item.proposed_via_label = device
        if item.decided_by_user_id is not None:
            item.decided_by_label = users.get(item.decided_by_user_id, UNKNOWN_MEMBER)


async def label_one(db: AsyncSession, item: ProposalResponse) -> ProposalResponse:
    """:func:`attach_labels` for a single proposal, returned for convenience."""
    await attach_labels(db, [item])
    return item
