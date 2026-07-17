"""Add personal_access_tokens — long-lived scoped API tokens per member.

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-17

security-006 / plans/open-hearth/mcp-server.md. Agents (MCP clients, Home
Assistant, iCal feeds) need a credential that outlives a session JWT and can be
revoked individually. Tokens are stored as SHA-256 only — there is deliberately
no plaintext column, so this table leaking yields no usable credentials.

Indexes: token_hash carries a UNIQUE index (every agent request is a lookup by
hash), and user_id is indexed for the management list endpoint.
"""

from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        # SHA-256 hex digest of the full raw token. No plaintext column exists.
        sa.Column("token_hash", sa.Text(), nullable=False),
        # Non-secret display fragment, e.g. "hearth_pat_a1b2c3d4".
        sa.Column("prefix", sa.String(40), nullable=False),
        # { "<domain>": "read" | "write" } — see api/src/life_dashboard/auth/pat_scopes.py.
        sa.Column("scopes", sa.JSON(), nullable=False),
        # NULL = never expires (Home Assistant-style long-lived token).
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_personal_access_tokens_token_hash",
        "personal_access_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_personal_access_tokens_user_id",
        "personal_access_tokens",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_personal_access_tokens_user_id", table_name="personal_access_tokens")
    op.drop_index("ix_personal_access_tokens_token_hash", table_name="personal_access_tokens")
    op.drop_table("personal_access_tokens")
