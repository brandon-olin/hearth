"""Add notifications table

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-13

In-app notification feed. One row per recipient per triggering action.
Supports todo assignment and calendar event creation today; designed to
extend to @mentions and direct messages without schema changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The member who receives this notification.
        sa.Column(
            "recipient_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The member whose action triggered the notification. NULL = system-generated.
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # String type — extensible without migrations.
        # Current: "todo_assigned", "event_created"
        # Planned: "mentioned", "message_received"
        sa.Column("type", sa.String(50), nullable=False),
        # Which domain object triggered this notification.
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        # Snapshot payload so we don't need a join to render the notification.
        # Always contains at least {"title": str}.
        sa.Column("payload", sa.JSON(), nullable=True),
        # NULL = unread; timestamp = when the user dismissed it.
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Primary access pattern: "all notifications for user X in household Y"
    op.create_index(
        "ix_notifications_recipient_household",
        "notifications",
        ["recipient_id", "household_id"],
    )
    # Secondary access pattern: fast unread-count query
    op.create_index(
        "ix_notifications_recipient_read_at",
        "notifications",
        ["recipient_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_recipient_read_at", table_name="notifications")
    op.drop_index("ix_notifications_recipient_household", table_name="notifications")
    op.drop_table("notifications")
