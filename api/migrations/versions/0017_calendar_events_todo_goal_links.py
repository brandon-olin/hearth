"""Add todo_id and goal_id to calendar_events

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-12

The CalendarEvent model and service already reference todo_id and goal_id
(to link events to a related todo or goal), but the columns were never added
to the database. This migration closes that gap so INSERT/SELECT stop failing
with UndefinedColumnError on those columns.

Safe to run on a populated database — both columns are nullable.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "calendar_events", "todo_id"):
        op.add_column(
            "calendar_events",
            sa.Column(
                "todo_id",
                UUID(as_uuid=True),
                sa.ForeignKey("todos.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_calendar_events_todo_id", "calendar_events", ["todo_id"])

    if not _column_exists(conn, "calendar_events", "goal_id"):
        op.add_column(
            "calendar_events",
            sa.Column(
                "goal_id",
                UUID(as_uuid=True),
                sa.ForeignKey("goals.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_calendar_events_goal_id", "calendar_events", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_events_goal_id", table_name="calendar_events")
    op.drop_column("calendar_events", "goal_id")
    op.drop_index("ix_calendar_events_todo_id", table_name="calendar_events")
    op.drop_column("calendar_events", "todo_id")
