"""add collections table and collection_id to notes/documents

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-11

Introduces the Collection concept: a user-defined named view over a domain
(notes or documents) with optional default tags, a default template, and an
auto-create rule for scheduled entry generation (e.g. daily journal entries).

Changes:
  - New `collections` table
  - `collection_id` nullable FK added to `notes`
  - `collection_id` nullable FK added to `documents`
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def _index_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # Pre-create the enum idempotently (PostgreSQL has no CREATE TYPE IF NOT EXISTS)
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE collection_domain AS ENUM ('notes', 'documents');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ── collections ───────────────────────────────────────────────────────────
    if not _table_exists(conn, "collections"):
        op.create_table(
            "collections",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "household_id",
                UUID(as_uuid=True),
                sa.ForeignKey("households.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_by_user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("icon", sa.Text(), nullable=True),
            sa.Column(
                "domain",
                PgEnum("notes", "documents", name="collection_domain", create_type=False),
                nullable=False,
            ),
            sa.Column("default_tags", JSONB(), nullable=True),
            sa.Column(
                "default_template_id",
                UUID(as_uuid=True),
                sa.ForeignKey("documents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("auto_create_rule", JSONB(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        if not _index_exists(conn, "ix_collections_household_id"):
            op.create_index("ix_collections_household_id", "collections", ["household_id"])

    # ── collection_id on notes ────────────────────────────────────────────────
    if not _column_exists(conn, "notes", "collection_id"):
        op.add_column(
            "notes",
            sa.Column(
                "collection_id",
                UUID(as_uuid=True),
                sa.ForeignKey("collections.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        if not _index_exists(conn, "ix_notes_collection_id"):
            op.create_index("ix_notes_collection_id", "notes", ["collection_id"])

    # ── collection_id on documents ────────────────────────────────────────────
    if not _column_exists(conn, "documents", "collection_id"):
        op.add_column(
            "documents",
            sa.Column(
                "collection_id",
                UUID(as_uuid=True),
                sa.ForeignKey("collections.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        if not _index_exists(conn, "ix_documents_collection_id"):
            op.create_index("ix_documents_collection_id", "documents", ["collection_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_collection_id", table_name="documents")
    op.drop_column("documents", "collection_id")

    op.drop_index("ix_notes_collection_id", table_name="notes")
    op.drop_column("notes", "collection_id")

    op.drop_table("collections")
    op.execute(sa.text("DROP TYPE IF EXISTS collection_domain"))
