"""Add parent_note_id and note_links table

Revision ID: b7c4d2e1f8a9
Revises: a3f2b8c1d4e5
Create Date: 2026-04-28

Two additions that enable Obsidian-style note organisation:

  parent_note_id  — self-referential FK for hierarchical nesting (the
                    page-inside-a-page model). SET NULL on parent delete
                    so orphaned children become root notes rather than
                    disappearing.

  note_links      — polymorphic adjacency table for explicit cross-links
                    between a note and any other entity (note, goal, todo,
                    contact, recipe, …). Drives backlinks and the knowledge
                    graph. Cascades on source note delete so stale outbound
                    links don't accumulate.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b7c4d2e1f8a9"
down_revision: Union[str, None] = "a3f2b8c1d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── parent_note_id on notes ───────────────────────────────────────────────
    op.add_column(
        "notes",
        sa.Column("parent_note_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "notes_parent_note_id_fkey",
        "notes", "notes",
        ["parent_note_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_notes_parent_note_id", "notes", ["parent_note_id"])

    # ── note_links ────────────────────────────────────────────────────────────
    op.create_table(
        "note_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_note_id", UUID(as_uuid=True),
                  sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_type", sa.String(100), nullable=False),
        sa.Column("target_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "source_note_id", "target_entity_type", "target_entity_id",
            name="note_links_source_target_key",
        ),
    )
    op.create_index("idx_note_links_source", "note_links", ["source_note_id"])
    # Target index supports efficient backlink queries ("what links to this entity?")
    op.create_index(
        "idx_note_links_target", "note_links", ["target_entity_type", "target_entity_id"]
    )


def downgrade() -> None:
    op.drop_table("note_links")
    op.drop_index("idx_notes_parent_note_id", table_name="notes")
    op.drop_constraint("notes_parent_note_id_fkey", "notes", type_="foreignkey")
    op.drop_column("notes", "parent_note_id")
