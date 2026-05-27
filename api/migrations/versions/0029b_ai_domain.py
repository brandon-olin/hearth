"""Catch-up migration: create AI-domain tables missing from formal migrations.

Revision ID: 0029b
Revises: 0029
Create Date: 2026-05-27

Background
----------
The ai_conversations, ai_messages, member_ai_memory, and ai_settings tables
grew organically on the SQLite dev path via create_all() / _patch_sqlite_schema()
but were never formally captured in an Alembic migration. Subsequent migrations
(0030, 0031, 0033, 0035, 0037) reference these tables with ADD COLUMN statements
that fail on a fresh Postgres deployment because the tables don't exist yet.

This migration creates all four tables at their *base* column set — the state
they were in before the ADD COLUMN migrations ran. Using CREATE TABLE IF NOT
EXISTS makes it a safe no-op on any deployment that somehow already has them.

Column coverage
---------------
ai_conversations:  id, user_id, household_id, title, created_at, last_message_at
                   (kind, note_id added by 0035; mode added by 0037)

ai_messages:       id, conversation_id, role, content, created_at

member_ai_memory:  user_id (PK), memory_text, last_updated_at,
                   conversation_count_at_last_update
                   (last_bootstrapped_at added by 0030;
                    notes_at_last_proposal added by 0031)

ai_settings:       user_id (PK), provider, api_key_encrypted, retention_days
                   (ai_journal_extraction_enabled added by 0033)

FK repair
---------
Migration 0014 creates ai_usage.conversation_id without a FK constraint because
ai_conversations didn't exist yet. After this migration creates ai_conversations,
we add that FK so cascading deletes work correctly.
"""

from alembic import op
import sqlalchemy as sa

revision = "0029b"
down_revision = "0029"
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


def _constraint_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_schema = 'public' AND constraint_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: all tables handled by create_all() + _patch_sqlite_schema()

    # ── ai_conversations ─────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id          UUID        NOT NULL PRIMARY KEY,
            user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            household_id UUID       NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            title       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_message_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    # ── ai_messages ──────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ai_messages (
            id              UUID        NOT NULL PRIMARY KEY,
            conversation_id UUID        NOT NULL
                REFERENCES ai_conversations(id) ON DELETE CASCADE,
            role            VARCHAR(20) NOT NULL,
            content         TEXT        NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    # ── member_ai_memory ─────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS member_ai_memory (
            user_id                         UUID        NOT NULL PRIMARY KEY
                REFERENCES users(id) ON DELETE CASCADE,
            memory_text                     TEXT        NOT NULL DEFAULT '',
            last_updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            conversation_count_at_last_update INTEGER   NOT NULL DEFAULT 0
        )
    """))

    # ── ai_settings ──────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ai_settings (
            user_id           UUID        NOT NULL PRIMARY KEY
                REFERENCES users(id) ON DELETE CASCADE,
            provider          VARCHAR(20) NOT NULL DEFAULT 'anthropic',
            api_key_encrypted TEXT,
            retention_days    INTEGER     DEFAULT 90
        )
    """))

    # ── FK repair: ai_usage.conversation_id → ai_conversations ───────────────
    # Migration 0014 skipped this FK because ai_conversations didn't exist yet.
    # Add it now if it's still missing.
    if not _constraint_exists(bind, "fk_ai_usage_conversation_id"):
        # Only add if the column exists (it always should after 0014, but guard anyway).
        col_check = bind.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'ai_usage' AND column_name = 'conversation_id'"
        )).fetchone()
        if col_check:
            op.execute(sa.text(
                "ALTER TABLE ai_usage "
                "ADD CONSTRAINT fk_ai_usage_conversation_id "
                "FOREIGN KEY (conversation_id) "
                "REFERENCES ai_conversations(id) ON DELETE SET NULL"
            ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    # Drop FK repair first.
    if _constraint_exists(bind, "fk_ai_usage_conversation_id"):
        op.execute(sa.text(
            "ALTER TABLE ai_usage "
            "DROP CONSTRAINT fk_ai_usage_conversation_id"
        ))

    op.drop_table("ai_settings")
    op.drop_table("member_ai_memory")
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
