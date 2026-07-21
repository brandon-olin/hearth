"""Add webhook_subscriptions + webhook_deliveries — outbound webhooks.

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-21

webhook-001. Two tables, both plain ``create_table`` — no ALTER-shaped work, so
no ``batch_alter_table`` is needed and this replays identically on Postgres and
SQLite.

Notable column choices, all load-bearing:

* ``webhook_subscriptions.created_by_user_id`` is NOT NULL and cascades on member
  deletion. A subscription delivers only what its OWNER may see, so an ownerless
  subscription has no defensible scope and must not be able to exist.
* ``secret`` is TEXT holding Fernet ciphertext (core/encryption.EncryptedText).
  It is encrypted rather than hashed because it is needed in cleartext to sign
  each delivery; the service refuses to create a subscription at all when
  FIELD_ENCRYPTION_KEY is unset, so this column never holds a plaintext secret.
* ``webhook_deliveries.entity_id`` is a plain string with no FK, like audit_log's
  — a delivery record outlives the entity it describes.
* Index ``(status, next_attempt_at)`` backs the worker's only hot query: pending
  rows that are due now.
"""

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Owner of the subscription — its scope ceiling. CASCADE, not SET NULL:
        # an ownerless subscription could not be scope-checked.
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        # Fernet ciphertext — see the module docstring.
        sa.Column("secret", sa.Text(), nullable=False),
        # e.g. ["todo.completed", "grocery.*"] — the entire filter surface in v1.
        sa.Column("event_patterns", sa.JSON(), nullable=False),
        # Unquoted `true` on purpose: server_default="true" renders DEFAULT 'true'
        # on SQLite, which stores TEXT and would not compare equal to 1.
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("disabled_reason", sa.String(200), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_webhook_subscriptions_household_active",
        "webhook_subscriptions",
        ["household_id", "active"],
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "subscription_id",
            sa.Uuid(),
            sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        # Plain string, no FK — outlives the entity it describes.
        sa.Column("entity_id", sa.String(64), nullable=False),
        # The exact body sent, already filtered through the central allowlist.
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_webhook_deliveries_subscription_created",
        "webhook_deliveries",
        ["subscription_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_subscription_created", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_due", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_subscriptions_household_active", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")
