"""Add proposals — the propose permission tier's storage.

Revision ID: 0051
Revises: 0050
Create Date: 2026-07-21

proposal-001. Exactly ONE new table. The `read < propose < write` tier itself
needs no DDL: `personal_access_tokens.scopes` and `households.permissions_config`
are both JSON columns, so admitting "propose" as a value is a vocabulary change
in `auth/pat_scopes.py` and `core/permissions.py`, not a schema change.

Plain `create_table` + `create_index` with no ALTER-shaped work, so no
`batch_alter_table` is required and this replays identically on Postgres and
SQLite. Nothing here is Postgres-only:

* `status` is VARCHAR + CHECK rather than a native enum (ADR-015) — native enum
  types are exactly the drift that broke 0046.
* The partial unique index is expressed through both `postgresql_where` and
  `sqlite_where`, which SQLAlchemy renders as the same standards `WHERE` clause
  on each. SQLite has supported partial indexes since 3.8.

The FK behaviours are load-bearing, not defaults:

* `token_id` is **CASCADE, not SET NULL** — the opposite of `audit_log.token_id`.
  The stale-proposer guard must distinguish a legitimately-null household-agent
  `token_id` from a token revoked after proposing. Under SET NULL those two
  states are identical and the guard fails open, executing a write attributed to
  a credential that no longer exists. Revocation is soft (`revoked_at`), so the
  row survives and stays detectable; a hard delete takes its pending proposals
  with it, which is the safe direction.
* `proposed_by_user_id` cascades for the same reason: NULL there must keep
  meaning "household agent", never "member deleted".
* `decided_by_user_id` DOES use SET NULL — nothing infers meaning from its
  nullness, and `decided_at` records that a decision happened regardless.
"""

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL = a household-agent pseudo-member proposed it. CASCADE, never
        # SET NULL — see the module docstring.
        sa.Column(
            "proposed_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # NULL = no token was involved (proposal-003's web-UI path). CASCADE.
        sa.Column(
            "token_id",
            sa.Uuid(),
            sa.ForeignKey("personal_access_tokens.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # AuditSource vocabulary: "web" | "mcp" | "script". Deliberately the SAME
        # vocabulary as audit_log.source — two columns named `source` with
        # divergent values would be a trap for whoever joins them.
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        # The exact would-be service call — not a summary. Approval replays it.
        sa.Column("args", sa.JSON(), nullable=False),
        # SHA-256 hex over (tool, args, proposer, token): the idempotency key.
        sa.Column("args_fingerprint", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column(
            "decided_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(500), nullable=True),
        # Plain text, no FK, like audit_log.entity_id — outlives the entity.
        sa.Column("result_entity_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_proposals_status",
        ),
    )

    # The approval queue: one household's proposals, newest first, usually
    # filtered to pending.
    op.create_index(
        "ix_proposals_household_status_created",
        "proposals",
        ["household_id", "status", "created_at"],
    )
    # The expiry sweep's only query.
    op.create_index("ix_proposals_status_expires", "proposals", ["status", "expires_at"])
    # Idempotency enforced by the database rather than a check-then-insert race.
    # Partial, so a fingerprint may recur once the earlier proposal is decided —
    # asking again after a "no" is a new request, not a duplicate.
    op.create_index(
        "uq_proposals_pending_fingerprint",
        "proposals",
        ["household_id", "args_fingerprint"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_proposals_pending_fingerprint", table_name="proposals")
    op.drop_index("ix_proposals_status_expires", table_name="proposals")
    op.drop_index("ix_proposals_household_status_created", table_name="proposals")
    op.drop_table("proposals")
