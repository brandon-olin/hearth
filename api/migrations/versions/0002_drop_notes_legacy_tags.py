"""Drop legacy text[] tags column from notes

Revision ID: a3f2b8c1d4e5
Revises:
Create Date: 2026-04-28

The notes.tags column is a text[] holdover from before the normalised
tags + taggings tables were introduced in Phase 0. It contains no data.
The taggings table is the forward path (Zettelkasten-style tag graph).

NOTE: Made defensive for clean-install compatibility — the notes table
did not exist in Alembic-managed history so on a fresh DB this is a no-op.
Migration 0010 creates the canonical notes schema.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f2b8c1d4e5"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
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
    if _has_column(conn, "notes", "tags"):
        op.drop_column("notes", "tags")


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "notes", "tags"):
        op.add_column(
            "notes",
            sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        )
