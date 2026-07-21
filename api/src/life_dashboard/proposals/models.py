import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base

#: The four states a proposal can hold. Stored as VARCHAR + CHECK rather than a
#: native enum, per ADR-015 — native enum types drift between the create_all()
#: and migration-replayed schemas.
PROPOSAL_STATUSES = ("pending", "approved", "rejected", "expired")


class Proposal(Base):
    """A write that was *asked for* rather than performed (proposal-001).

    When ``authorize`` resolves an agent's write to the ``propose`` tier — the
    middle rung of read < propose < write — the tool records one of these
    instead of executing, and a human with ``write`` on the domain later
    approves or rejects it. Approval replays ``args`` through the same service
    function the direct write would have called.

    **Why this is not an ``audit_log`` row**, despite sharing ~9 columns:

    * ``audit_log`` is append-only by design; a proposal mutates through
      ``pending → approved | rejected | expired``.
    * ``audit_log.payload`` is contractually a small summary. ``args`` is the
      opposite: the exact, complete service call, because approval replays it.
    * Retention is inverted — audit rows are permanent, proposals expire and
      are swept.

    **Attribution columns are surface-agnostic from day one** so proposal-003
    (web-UI propose for restricted members) reuses this table with no migration:

    * ``proposed_by_user_id`` NULL → a household-agent pseudo-member proposed it;
      there is no single human actor, exactly as in ``audit_log.actor_user_id``.
    * ``token_id`` NULL → no token was involved (a future web-UI proposal).
    * ``source`` reuses the ``AuditSource`` vocabulary (web | mcp | script)
      rather than inventing a second, divergent ``source`` vocabulary.

    **``token_id`` deliberately does NOT cascade to NULL**, unlike
    ``audit_log.token_id``. The stale-proposer guard must tell "no token" apart
    from "token revoked after proposing"; under ``ON DELETE SET NULL`` those two
    states are byte-identical and the guard fails open, executing a write
    attributed to a dead credential. Revocation here is soft
    (``personal_access_tokens.revoked_at``), so the row survives and stays
    detectable; a hard token delete cascades the pending proposal away, which is
    the safe direction. ``proposed_by_user_id`` cascades for the same reason.
    """

    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # NULL for a household-agent pseudo-member. CASCADE, never SET NULL — see
    # the class docstring: a NULL here must keep meaning "agent", not "gone".
    proposed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # NULL only when no token was involved at all. CASCADE, never SET NULL.
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("personal_access_tokens.id", ondelete="CASCADE"), nullable=True
    )
    # AuditSource vocabulary: "web" | "mcp" | "script" (see audit/schemas.py).
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # PAT scope domain the write needed, e.g. "todos" — what the approver's own
    # ceiling is re-checked against.
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    # The MCP tool that would have run, e.g. "add_todo". Keys the executor
    # registry that replays it on approval.
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    # The exact would-be service call, JSON-serialised. Not a summary.
    args: Mapped[dict] = mapped_column(JSON, nullable=False)
    # SHA-256 over (tool, args, proposer, token) — the idempotency key. A hash
    # rather than a JSON comparison because JSON equality is not portable across
    # Postgres and SQLite, and because folding the nullable proposer columns into
    # the digest makes them dedupe correctly (SQL NULLs never compare equal).
    args_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Human-readable one-liner for the approval queue, e.g. 'Add to-do "Milk"'.
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    # The human who approved/rejected. SET NULL is correct *here* — unlike
    # token_id, nothing infers meaning from its nullness; decided_at says whether
    # a decision happened.
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Why it was rejected, or which credential died — readable by the proposing
    # agent so it can close the loop with its user.
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Id of the entity the approved write produced. A plain string with no FK,
    # like audit_log.entity_id, so the row outlives the entity.
    result_entity_id: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_proposals_status",
        ),
        # The approval queue: one household's proposals, newest first, usually
        # filtered to pending.
        Index("ix_proposals_household_status_created", "household_id", "status", "created_at"),
        # The expiry sweep's only query: pending rows now past expires_at.
        Index("ix_proposals_status_expires", "status", "expires_at"),
        # Idempotency, enforced by the database rather than by a check-then-insert
        # race. Partial so a fingerprint may recur once the earlier proposal has
        # been decided — asking again after a rejection is a new request, not a
        # duplicate. Partial indexes exist on both Postgres and SQLite.
        Index(
            "uq_proposals_pending_fingerprint",
            "household_id",
            "args_fingerprint",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )
