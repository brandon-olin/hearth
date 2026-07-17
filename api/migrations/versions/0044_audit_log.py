"""Add audit_log — attributed record of agent and script writes.

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-17

security-008. Bootstraps the audit track. Every MCP write tool (mcp-002) is
wrapped by the @audited decorator, which appends a row here attributed to the
calling PAT. Two nullable attribution columns encode the household-agent model:

  * token_id NULL       → a web-session write (no token).
  * actor_user_id NULL  → a household-agent pseudo-member token (a shared
                          device): attributed to the token, not a person.

Both FKs are ON DELETE SET NULL, and entity_id is a plain string with no FK, so
an audit row outlives the token, member, or entity it refers to. household_id
cascades — deleting a household discards its audit trail with it.

Index (household_id, created_at) backs the future settings "Activity" page,
which reads a household's rows newest-first.
"""

from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The 0001 baseline (imported from the pre-Alembic bootstrap SQL) already
    # created a legacy `audit_log` table (actor_type/actor_id schema) that no
    # code has ever written to — it exists, empty, in every database migrated
    # from baseline. Drop it so this migration can create the real audit_log
    # (actor_user_id/token_id schema). Guarded with IF EXISTS so databases
    # without the legacy table (e.g. SQLite created fresh from ORM metadata)
    # are unaffected.
    op.execute(sa.text("DROP TABLE IF EXISTS audit_log"))

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL for a household-agent pseudo-member token — no single human actor.
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # NULL for a web-session write. SET NULL on delete so revoking a token
        # never erases its audit trail.
        sa.Column(
            "token_id",
            sa.Uuid(),
            sa.ForeignKey("personal_access_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        # Plain string, no FK — the row survives the entity's deletion.
        sa.Column("entity_id", sa.String(64), nullable=True),
        # A small summary of the write, never the full row.
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_audit_log_household_created",
        "audit_log",
        ["household_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_household_created", table_name="audit_log")
    op.drop_table("audit_log")
