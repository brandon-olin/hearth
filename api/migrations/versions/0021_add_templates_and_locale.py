"""Add templates system, collection show_in_nav, and user locale settings

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-14

Changes:
  - New `templates` table (reusable content templates, household- or user-scoped)
  - New `collection_templates` join table (many-to-many; one entry per collection
    may be marked is_default=True for use by auto-create and the single-template
    fast-path on manual entry creation)
  - Drop `collections.default_template_id` (superseded by the join table)
  - Add `collections.show_in_nav` (Boolean, default false — explicit opt-in
    for sidebar visibility)
  - Data migration: convert existing `collections.auto_create_rule.title_template`
    values from strftime format (e.g. "%B %d, %Y") to {{variable}} syntax
    (e.g. "{{month}} {{day}}, {{year}}")
  - Add `users.timezone`, `users.date_format`, `users.week_start`
    (locale/display preferences, auto-detected from browser on first login)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0021"
down_revision = "0020"
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


def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
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

    # ── templates ─────────────────────────────────────────────────────────────
    if not _table_exists(conn, "templates"):
        op.create_table(
            "templates",
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
            # "household" = visible to all members; "user" = private to creator
            sa.Column(
                "scope",
                sa.String(16),
                nullable=False,
                server_default="household",
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            # Must match the domain of any collection using this template
            sa.Column("domain", sa.String(16), nullable=False),
            # Optional: pre-fills new entry title; supports {{variable}} syntax
            sa.Column("title_template", sa.Text(), nullable=True),
            # For domain="notes" — markdown body; supports {{variable}} syntax
            sa.Column("content_md", sa.Text(), nullable=True),
            # For domain="documents" — BlockNote block tree
            sa.Column("content_json", JSONB(), nullable=True),
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
        if not _index_exists(conn, "ix_templates_household_id"):
            op.create_index("ix_templates_household_id", "templates", ["household_id"])
        # Partial index: scoped to user — speeds up "my private templates" queries
        if not _index_exists(conn, "ix_templates_user_scoped"):
            op.execute(
                sa.text(
                    "CREATE INDEX ix_templates_user_scoped "
                    "ON templates (created_by_user_id) "
                    "WHERE scope = 'user'"
                )
            )

    # ── collection_templates ──────────────────────────────────────────────────
    if not _table_exists(conn, "collection_templates"):
        op.create_table(
            "collection_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "collection_id",
                UUID(as_uuid=True),
                sa.ForeignKey("collections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "template_id",
                UUID(as_uuid=True),
                sa.ForeignKey("templates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_unique_constraint(
            "collection_templates_pair_key",
            "collection_templates",
            ["collection_id", "template_id"],
        )
        if not _index_exists(conn, "ix_collection_templates_collection_id"):
            op.create_index(
                "ix_collection_templates_collection_id",
                "collection_templates",
                ["collection_id"],
            )

    # ── collections: drop default_template_id ─────────────────────────────────
    # The FK constraint must be dropped before the column.
    if _column_exists(conn, "collections", "default_template_id"):
        # Find and drop the FK constraint by name (autogenerated by SQLAlchemy)
        conn.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    cname TEXT;
                BEGIN
                    SELECT conname INTO cname
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                    WHERE t.relname = 'collections'
                      AND a.attname = 'default_template_id'
                      AND c.contype = 'f';

                    IF cname IS NOT NULL THEN
                        EXECUTE 'ALTER TABLE collections DROP CONSTRAINT ' || quote_ident(cname);
                    END IF;
                END $$;
                """
            )
        )
        op.drop_column("collections", "default_template_id")

    # ── collections: add show_in_nav ──────────────────────────────────────────
    if not _column_exists(conn, "collections", "show_in_nav"):
        op.add_column(
            "collections",
            sa.Column(
                "show_in_nav",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )

    # ── collections: migrate title_template from strftime to {{variable}} ─────
    # Map the known strftime patterns used by the old AutoCreateRule default.
    # Any unrecognised pattern falls back to "{{date}}" (renders the full date
    # per the user's date_format preference).
    conn.execute(
        sa.text(
            r"""
            UPDATE collections
            SET auto_create_rule = jsonb_set(
                auto_create_rule,
                '{title_template}',
                CASE auto_create_rule->>'title_template'
                    WHEN '%B %d, %Y'   THEN '"{{month}} {{day}}, {{year}}"'
                    WHEN '%d %B %Y'    THEN '"{{day}} {{month}} {{year}}"'
                    WHEN '%Y-%m-%d'    THEN '"{{year}}-{{month_num}}-{{day}}"'
                    WHEN '%d/%m/%Y'    THEN '"{{day}}/{{month_num}}/{{year}}"'
                    WHEN '%m/%d/%Y'    THEN '"{{month_num}}/{{day}}/{{year}}"'
                    ELSE               '"{{date}}"'
                END::jsonb
            )
            WHERE auto_create_rule IS NOT NULL
              AND auto_create_rule->>'title_template' LIKE '%' || chr(37) || '%'
            """
        )
    )

    # ── users: locale columns ─────────────────────────────────────────────────
    if not _column_exists(conn, "users", "timezone"):
        op.add_column(
            "users",
            sa.Column("timezone", sa.String(64), nullable=True),
        )
    if not _column_exists(conn, "users", "date_format"):
        op.add_column(
            "users",
            sa.Column("date_format", sa.String(20), nullable=True),
        )
    if not _column_exists(conn, "users", "week_start"):
        op.add_column(
            "users",
            sa.Column("week_start", sa.String(10), nullable=True),
        )


def downgrade() -> None:
    # ── users: remove locale columns ─────────────────────────────────────────
    op.drop_column("users", "week_start")
    op.drop_column("users", "date_format")
    op.drop_column("users", "timezone")

    # ── collections: revert show_in_nav ───────────────────────────────────────
    op.drop_column("collections", "show_in_nav")

    # ── collections: restore default_template_id ──────────────────────────────
    # NOTE: Data in the collection_templates join table is not back-migrated.
    # Restored column will be NULL for all rows.
    op.add_column(
        "collections",
        sa.Column(
            "default_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ── collection_templates ──────────────────────────────────────────────────
    op.drop_index("ix_collection_templates_collection_id", table_name="collection_templates")
    op.drop_constraint("collection_templates_pair_key", "collection_templates", type_="unique")
    op.drop_table("collection_templates")

    # ── templates ─────────────────────────────────────────────────────────────
    op.drop_index("ix_templates_household_id", table_name="templates")
    # Partial indexes must be dropped by name
    op.execute(sa.text("DROP INDEX IF EXISTS ix_templates_user_scoped"))
    op.drop_table("templates")
