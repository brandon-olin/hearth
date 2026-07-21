import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProposalStatus(str, Enum):
    """Lifecycle of a proposal.

    pending  — awaiting a human decision.
    approved — the write was replayed and executed.
    rejected — a human declined it; ``reject_reason`` says why.
    expired  — nobody decided before ``expires_at``, OR approval was refused
               because the proposing credential no longer exists. Both are
               "this will never execute now", and the reason distinguishes them.
    """

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


#: The four valid ``status`` filter values, in lifecycle order. Enumerated in
#: every error that rejects a status — a filter that silently matches nothing is
#: worse than a refusal, for a UI and an agent alike.
PROPOSAL_STATUS_VALUES: tuple[str, ...] = tuple(s.value for s in ProposalStatus)


class ProposalResponse(BaseModel):
    """One proposal. The agent-facing and queue-facing shape are the same.

    The three ``*_label`` fields are not columns — they are resolved from the
    attribution ids by ``proposals/labels.py`` on the way out, because an id is
    not a decidable question ("who asked for this?") and because a proposer may
    be a device with no person behind it at all.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    proposed_by_user_id: uuid.UUID | None
    token_id: uuid.UUID | None
    source: str
    domain: str
    tool: str
    args: dict
    summary: str
    status: str
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    reject_reason: str | None
    result_entity_id: str | None
    created_at: datetime
    expires_at: datetime

    #: The member who asked, or — for a household-agent proposal, which has no
    #: person behind it — the name of the device that did.
    proposed_by_label: str | None = None
    #: The device (token) name, when a token was involved at all. Present
    #: alongside a member label so the queue can read "Alice · Kitchen iPad".
    proposed_via_label: str | None = None
    #: The human who approved or rejected it. None while pending.
    decided_by_label: str | None = None


class ProposalListResponse(BaseModel):
    items: list[ProposalResponse]
    total: int
    limit: int
    offset: int


class ProposalRejectRequest(BaseModel):
    """Declining a proposal, with the reason the proposing agent will read.

    Optional, because forcing a reason produces "no" more often than it produces
    a reason — but the default text is honest about its absence rather than
    pretending one was given.
    """

    reason: str | None = Field(default=None, max_length=500)
