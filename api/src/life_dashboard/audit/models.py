import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class AuditLog(Base):
    """An attributed record of a write performed against household data (security-008).

    Bootstraps the audit track. Every MCP write tool is wrapped by the
    ``@audited`` decorator (see ``audit/decorator.py``) so a tool author cannot
    forget to record; web routes can adopt ``audit.service.record`` later. The
    eventual surface is a settings "Activity" page — until then rows are queried
    directly.

    Attribution comes from the auth context. A PAT-authenticated write carries
    both an ``actor_user_id`` (the token's owning member) and a ``token_id``. The
    two nullable columns encode the honest-attribution cases the household-agent
    model needs:

    * ``token_id`` NULL  → the write came from a logged-in web session, not a token.
    * ``actor_user_id`` NULL → the write came from a *household-agent pseudo-member*
      token (a shared device, e.g. the kitchen speaker): there is no single human
      actor, so the row is attributed to the token alone. Such tokens still carry
      a ``token_id`` — that is how a shared-device action stays auditable and
      survives the deactivation of any individual member.

    The row is a summary, not a copy of the mutated entity: ``payload`` holds a
    small JSONB digest, and ``entity_id`` is stored as a plain string with no FK,
    so an audit row outlives the entity, token, or member it refers to.
    """
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    # NULL for a household-agent pseudo-member token — no single human actor.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # NULL for a web-session write; set for any token-authenticated write. SET
    # NULL on delete so revoking/deleting a token never erases its audit trail.
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("personal_access_tokens.id", ondelete="SET NULL"), nullable=True
    )
    # Where the write originated: "web" | "mcp" | "script". See audit.service.AuditSource.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Domain verb, e.g. "create", "update", "check_in".
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # Entity kind, e.g. "todo", "grocery_item", "habit_occurrence".
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Stored as a string (no FK) so the row survives the entity's deletion. NULL
    # for actions that don't map to a single entity.
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A small summary of the write (e.g. {"title": "Milk"}), never the full row.
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The Activity page and any household audit query filter by household and
        # read newest-first.
        Index("ix_audit_log_household_created", "household_id", "created_at"),
    )
