"""Show journal collection in nav by default for all existing households.

Revision ID: 0040
Revises: 0039
Create Date: 2026-05-28

The seed function originally created the Journal collection with show_in_nav=False,
so existing households have it hidden. This data migration flips all kind='journal'
collections to show_in_nav=True so they appear in the sidebar, matching the
behaviour of the To-dos system project.

New households get show_in_nav=True from the seed function directly (also fixed
in this commit).
"""

from alembic import op
import sqlalchemy as sa

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE collections SET show_in_nav = TRUE WHERE kind = 'journal'"
        )
    )


def downgrade() -> None:
    # Reversing this would hide every journal collection again, which is the
    # wrong default. Leave show_in_nav untouched on downgrade.
    pass
