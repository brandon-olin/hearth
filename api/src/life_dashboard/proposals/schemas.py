import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


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


class ProposalResponse(BaseModel):
    """One proposal. The agent-facing and queue-facing shape are the same."""

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


class ProposalListResponse(BaseModel):
    items: list[ProposalResponse]
    total: int
    limit: int
    offset: int
