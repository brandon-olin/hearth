"""Phase 2 of AI coach redesign — collection.kind + default Journal collection.

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-25

Adds a nullable `kind` column to `collections` and seeds a Journal collection
for every household. The redesign uses kind='journal' to flag collections
whose notes should feed into the journal_signals extractor (Phase 2) and
the CBT-aware coach prompts (Phase 3). Future kinds (recipes, routines, …)
slot into the same column.

Idempotent backfill:
- Adds kind=NULL by default.
- One-time heuristic backfill: any existing collection that is in the notes
  domain AND named 'Journal' (case-insensitive) OR has an auto_create_rule
  with frequency='daily' is marked kind='journal'.
- For every household, ensures a Journal collection exists. If the household
  already has a notes-domain collection that ended up with kind='journal'
  via the heuristic, that one is preserved. Otherwise a fresh Journal
  collection is inserted with sensible defaults.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


# Default Journal collection — the canonical journaling surface users get
# out of the box. The notes themselves still live in the notes domain;
# this Collection just gives them a sidebar entry and feeds the signal
# extractor.
_DEFAULT_JOURNAL_NAME = "Journal"
_DEFAULT_JOURNAL_ICON = "book-open"
_DEFAULT_JOURNAL_AUTO_CREATE = {
    "frequency": "daily",
    "title_template": "{{day_of_week}}, {{month}} {{day}}, {{year}}",
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema + per-request seed.

    # 1) Add the kind column.
    op.add_column(
        "collections",
        sa.Column("kind", sa.String(32), nullable=True),
    )

    # 2) Heuristic backfill — flag any existing notes-domain collection that
    #    looks like a journal as kind='journal'. The auto_create_rule->>'frequency'
    #    cast works on Postgres; for SQLite we rely on app-layer logic.
    op.execute(
        """
        UPDATE collections
        SET kind = 'journal'
        WHERE kind IS NULL
          AND domain = 'notes'
          AND (
              LOWER(name) = 'journal'
              OR (auto_create_rule IS NOT NULL
                  AND auto_create_rule::jsonb->>'frequency' = 'daily')
          )
        """
    )

    # 3) Seed a Journal collection for any household that doesn't yet have one
    #    with kind='journal'. We pick the household's first owner as the
    #    created_by_user_id so the row is well-formed; falls back to NULL if
    #    no membership rows exist (edge case for malformed test data).
    op.execute(
        """
        INSERT INTO collections (
            id, household_id, created_by_user_id, name, icon, domain,
            kind, default_tags, auto_create_rule, show_in_nav, sort_order,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            h.id AS household_id,
            (
                SELECT hm.user_id
                FROM household_memberships hm
                WHERE hm.household_id = h.id
                ORDER BY hm.joined_at ASC
                LIMIT 1
            ) AS created_by_user_id,
            'Journal',
            'book-open',
            'notes',
            'journal',
            NULL,
            '{"frequency": "daily", "title_template": "{{day_of_week}}, {{month}} {{day}}, {{year}}"}'::json,
            FALSE,
            0,
            NOW(),
            NOW()
        FROM households h
        WHERE NOT EXISTS (
            SELECT 1 FROM collections c
            WHERE c.household_id = h.id AND c.kind = 'journal'
        )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("collections", "kind")
