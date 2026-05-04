"""Drop legacy text[] tags column from notes

Revision ID: a3f2b8c1d4e5
Revises:
Create Date: 2026-04-28

The notes.tags column is a text[] holdover from before the normalised
tags + taggings tables were introduced in Phase 0. It contains no data.
The taggings table is the forward path (Zettelkasten-style tag graph).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f2b8c1d4e5"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("notes", "tags")


def downgrade() -> None:
    # Restores the column as nullable with no data — matches the pre-migration state.
    op.add_column(
        "notes",
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
    )
