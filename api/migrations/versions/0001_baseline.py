"""Baseline schema — infrastructure tables for fresh installs

Revision ID: 0001
Revises:
Create Date: 2026-05-07

This migration is the root of the Alembic chain.  On NAS installs the
equivalent schema was created by the raw-SQL file
migrations/0001_multi_user_audit_tags_attachments.up.sql, which was never
tracked by Alembic.  All statements here use IF NOT EXISTS / CREATE OR
REPLACE so they are safe no-ops on a database that already has these objects.

Tables created:
  households, users, household_memberships, refresh_tokens
  audit_log, attachments, tags, taggings
  contacts, contact_addresses, contact_emails, contact_phones
  calendar_events

The update_updated_at() trigger function is also created here because many
later migrations register triggers against it.

Tables NOT created here (created by later migrations):
  goals, todos, habits, habit_occurrences, recipes, recipe_ingredients,
  recipe_steps, grocery_lists, grocery_items  (→ 0006)
  documents, workouts, exercise_entries        (→ 0007)
  notes, note_tags, note_backlinks             (→ 0010)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Trigger helper function ───────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))

    # ── Enum types ────────────────────────────────────────────────────────────
    # CREATE TYPE has no IF NOT EXISTS before PG 9.x, so guard manually.
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE actor_type AS ENUM ('user', 'agent', 'system');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE membership_role AS ENUM ('owner', 'admin', 'member', 'viewer', 'agent');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # ── Core identity tables ──────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS households (
            id          uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            name        varchar(200) NOT NULL,
            created_at  timestamptz DEFAULT now() NOT NULL,
            updated_at  timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS users (
            id              uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            email           varchar(320) NOT NULL UNIQUE,
            password_hash   text NOT NULL,
            display_name    varchar(200),
            is_active       boolean DEFAULT true NOT NULL,
            is_agent        boolean DEFAULT false NOT NULL,
            last_login_at   timestamptz,
            created_at      timestamptz DEFAULT now() NOT NULL,
            updated_at      timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS household_memberships (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role         membership_role DEFAULT 'member' NOT NULL,
            joined_at    timestamptz DEFAULT now() NOT NULL,
            UNIQUE (household_id, user_id)
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id          uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  text NOT NULL UNIQUE,
            user_agent  text,
            expires_at  timestamptz NOT NULL,
            revoked_at  timestamptz,
            created_at  timestamptz DEFAULT now() NOT NULL
        )
    """))

    # ── Audit log ─────────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id                   uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id         uuid REFERENCES households(id) ON DELETE SET NULL,
            actor_type           actor_type NOT NULL,
            actor_id             uuid,
            actor_label          varchar(200),
            entity_type          varchar(100) NOT NULL,
            entity_id            uuid,
            action               varchar(50) NOT NULL,
            diff                 jsonb,
            metadata             jsonb,
            approved_by_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at           timestamptz DEFAULT now() NOT NULL
        )
    """))

    # ── Attachments ───────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS attachments (
            id                   uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id         uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            owner_entity_type    varchar(100) NOT NULL,
            owner_entity_id      uuid NOT NULL,
            file_path            text NOT NULL,
            original_filename    varchar(500),
            content_type         varchar(200),
            size_bytes           bigint,
            uploaded_by_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at           timestamptz DEFAULT now() NOT NULL
        )
    """))

    # ── Tags + taggings ───────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS tags (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            name         varchar(100) NOT NULL,
            color        varchar(20),
            created_at   timestamptz DEFAULT now() NOT NULL,
            UNIQUE (household_id, name)
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS taggings (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            tag_id       uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            entity_type  varchar(100) NOT NULL,
            entity_id    uuid NOT NULL,
            created_at   timestamptz DEFAULT now() NOT NULL,
            UNIQUE (tag_id, entity_type, entity_id)
        )
    """))

    # ── Contacts ──────────────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS contacts (
            id                   uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id         uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            created_by_user_id   uuid REFERENCES users(id) ON DELETE SET NULL,
            vcard_uid            text,
            given_name           varchar(200),
            family_name          varchar(200),
            middle_name          varchar(200),
            prefix               varchar(50),
            suffix               varchar(50),
            display_name         varchar(500),
            organization         varchar(500),
            job_title            varchar(500),
            birthday             date,
            anniversary          date,
            notes                text,
            website              varchar(500),
            source               varchar(100),
            external_id          text,
            created_at           timestamptz DEFAULT now() NOT NULL,
            updated_at           timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS contact_addresses (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            contact_id   uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            label        varchar(100),
            street       varchar(500),
            city         varchar(200),
            region       varchar(200),
            postal_code  varchar(20),
            country      varchar(200)
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS contact_emails (
            id          uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            contact_id  uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            email       varchar(500) NOT NULL,
            label       varchar(100),
            is_primary  boolean DEFAULT false NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS contact_phones (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            contact_id   uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            phone_number varchar(50) NOT NULL,
            label        varchar(100),
            is_primary   boolean DEFAULT false NOT NULL
        )
    """))

    # ── Calendar events ───────────────────────────────────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id                   uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id         uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            created_by_user_id   uuid REFERENCES users(id) ON DELETE SET NULL,
            ical_uid             text NOT NULL,
            title                varchar(500) NOT NULL,
            description          text,
            location             varchar(500),
            starts_at            timestamptz NOT NULL,
            ends_at              timestamptz,
            all_day              boolean DEFAULT false NOT NULL,
            rrule                text,
            exrule               text,
            rdate                text,
            exdate               text,
            status               varchar(20) DEFAULT 'confirmed' NOT NULL,
            transparency         varchar(20) DEFAULT 'opaque' NOT NULL,
            source               varchar(100),
            external_id          text,
            calendar_name        varchar(200),
            created_at           timestamptz DEFAULT now() NOT NULL,
            updated_at           timestamptz DEFAULT now() NOT NULL
        )
    """))

    # ── Indexes (all IF NOT EXISTS via DO block) ───────────────────────────────
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_household_memberships_user_id
                ON household_memberships (user_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_household_memberships_household_id
                ON household_memberships (household_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens (user_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens (expires_at);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_audit_log_household_id ON audit_log (household_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_audit_log_entity ON audit_log (entity_type, entity_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_audit_log_actor ON audit_log (actor_type, actor_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_attachments_household_id ON attachments (household_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_attachments_owner
                ON attachments (owner_entity_type, owner_entity_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_tags_household_id ON tags (household_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_taggings_entity ON taggings (entity_type, entity_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_contacts_household_id ON contacts (household_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_calendar_events_household_id
                ON calendar_events (household_id);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX idx_calendar_events_starts_at ON calendar_events (starts_at);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END $$;
    """))

    # ── updated_at triggers (CREATE OR REPLACE not available for triggers;
    #    use DROP IF EXISTS + CREATE pattern) ──────────────────────────────────
    for tbl in ("households", "users", "contacts", "calendar_events"):
        op.execute(sa.text(
            f"DROP TRIGGER IF EXISTS {tbl}_updated_at ON {tbl}"
        ))
        op.execute(sa.text(
            f"CREATE TRIGGER {tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
        ))


def downgrade() -> None:
    # The baseline is the root of the chain; downgrading past it would
    # destroy all data.  This is intentionally a no-op.
    pass
