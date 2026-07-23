"""Record prompt-cache token counts on ai_usage.

Revision ID: 0054
Revises: 0053
Create Date: 2026-07-22

Prompt caching (plans/020-implement-prompt-caching.md) splits what used to be
a single `input_tokens` figure into three buckets:

    total prompt = input_tokens
                 + cache_creation_input_tokens   (written to cache, ~1.25x)
                 + cache_read_input_tokens       (served from cache, ~0.1x)

Without these two columns, `input_tokens` alone *appears* to collapse after
caching is enabled — because it now counts only the tokens after the last
breakpoint — which reads as a win whether or not anything was cached. These
columns are what makes the difference observable.

Both are nullable-free with a server default of 0 so existing rows backfill
without a data migration, and they go through `batch_alter_table` so SQLite
rebuilds the table rather than choking on the ALTER (ADR-014).
"""
import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_usage") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cache_creation_input_tokens",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cache_read_input_tokens",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_usage") as batch_op:
        batch_op.drop_column("cache_read_input_tokens")
        batch_op.drop_column("cache_creation_input_tokens")
