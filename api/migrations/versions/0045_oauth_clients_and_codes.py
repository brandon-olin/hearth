"""Add oauth_clients + oauth_authorization_codes — OAuth 2.1 in front of PATs.

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-17

security-007 / plans/open-hearth/mcp-server.md. Cloud-tier OAuth 2.1
authorization-code + PKCE flow with dynamic client registration. A completed
grant mints a scoped Personal Access Token (0043) and returns it as the OAuth
access token, so there is deliberately no oauth access-token table — the two
tables here only cover registered clients and short-lived authorization codes.

Both secret-bearing columns store a SHA-256 hash only (client_secret_hash,
code_hash), matching the PAT table: a leak of these rows yields no usable
credentials. Unique indexes back the two hot lookups — client_id at every
authorize/token call, code_hash at every token exchange.
"""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.String(80), nullable=False),
        # SHA-256 of the client secret; NULL for public (PKCE-only) clients.
        sa.Column("client_secret_hash", sa.Text(), nullable=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        # Exact-match redirect URI allow-list (list[str]).
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column(
            "token_endpoint_auth_method",
            sa.String(40),
            nullable=False,
            server_default="none",
        ),
        sa.Column("grant_types", sa.JSON(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True
    )

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # SHA-256 of the raw code. No plaintext column.
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(80), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        # PKCE (RFC 7636) — S256 challenge the token exchange must satisfy.
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column(
            "code_challenge_method", sa.String(10), nullable=False, server_default="S256"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_oauth_authorization_codes_code_hash",
        "oauth_authorization_codes",
        ["code_hash"],
        unique=True,
    )
    op.create_index(
        "ix_oauth_authorization_codes_client_id",
        "oauth_authorization_codes",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oauth_authorization_codes_client_id",
        table_name="oauth_authorization_codes",
    )
    op.drop_index(
        "ix_oauth_authorization_codes_code_hash",
        table_name="oauth_authorization_codes",
    )
    op.drop_table("oauth_authorization_codes")
    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")
