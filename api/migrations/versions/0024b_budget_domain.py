"""Budget domain — create all budget tables for Postgres deployments.

Revision ID: 0024b
Revises: 0024
Create Date: 2026-05-27

Budget tables were originally created via SQLAlchemy create_all() on SQLite
and were never tracked in the Alembic migration chain.  This migration
creates them for fresh Postgres deployments (Railway, Neon, Docker).

Tables created (with their full current schema, including columns that
subsequent migrations would have added incrementally):
  budget_profiles
  budget_profile_members
  budget_accounts          (incl. Teller columns — 0025 becomes a no-op)
  budget_category_groups   (incl. is_income — 0034_category_group_is_income becomes a no-op)
  budget_categories        (incl. notify_threshold_pct — 0029 becomes a no-op)
  budget_transactions      (incl. running_balance — 0027 becomes a no-op;
                             import_source already includes 'recurring' — 0026 becomes a no-op)
  budget_targets
  budget_rollover_amounts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024b"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_profiles (
            id              uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id    uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            name            varchar(100) NOT NULL,
            budgeting_style varchar(20) NOT NULL DEFAULT 'zero_based',
            currency        varchar(3) NOT NULL DEFAULT 'USD',
            sort_order      integer NOT NULL DEFAULT 0,
            created_at      timestamptz DEFAULT now() NOT NULL,
            updated_at      timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_profile_members (
            id          uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            profile_id  uuid NOT NULL REFERENCES budget_profiles(id) ON DELETE CASCADE,
            user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role        varchar(20) NOT NULL DEFAULT 'member',
            created_at  timestamptz DEFAULT now() NOT NULL,
            updated_at  timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_accounts (
            id                      uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id            uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            owner_user_id           uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            profile_id              uuid REFERENCES budget_profiles(id) ON DELETE SET NULL,
            name                    varchar(200) NOT NULL,
            account_type            varchar(20) NOT NULL DEFAULT 'checking',
            scope                   varchar(20) NOT NULL DEFAULT 'personal',
            currency                varchar(3) NOT NULL DEFAULT 'USD',
            current_balance         numeric(14, 2),
            balance_updated_at      timestamptz,
            teller_enrollment_id    varchar(200),
            teller_access_token     text,
            teller_account_id       varchar(200),
            teller_institution_name varchar(200),
            teller_last_synced_at   timestamptz,
            teller_cursor           varchar(200),
            archived_at             timestamptz,
            created_at              timestamptz DEFAULT now() NOT NULL,
            updated_at              timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_category_groups (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            profile_id   uuid REFERENCES budget_profiles(id) ON DELETE SET NULL,
            name         varchar(100) NOT NULL,
            sort_order   integer NOT NULL DEFAULT 0,
            is_income    boolean NOT NULL DEFAULT false,
            created_at   timestamptz DEFAULT now() NOT NULL,
            updated_at   timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_categories (
            id                    uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id          uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            profile_id            uuid REFERENCES budget_profiles(id) ON DELETE SET NULL,
            name                  varchar(100) NOT NULL,
            default_scope         varchar(20) NOT NULL DEFAULT 'private',
            split_config          jsonb,
            group_id              uuid REFERENCES budget_category_groups(id) ON DELETE SET NULL,
            default_monthly_amount numeric(12, 2),
            rollover_enabled      boolean NOT NULL DEFAULT false,
            notify_threshold_pct  integer,
            is_recurring_revenue  boolean NOT NULL DEFAULT false,
            color                 varchar(20),
            icon                  varchar(10),
            sort_order            integer NOT NULL DEFAULT 0,
            keywords              jsonb,
            archived_at           timestamptz,
            created_at            timestamptz DEFAULT now() NOT NULL,
            updated_at            timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_transactions (
            id                   uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id         uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            account_id           uuid NOT NULL REFERENCES budget_accounts(id) ON DELETE CASCADE,
            owner_user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category_id          uuid REFERENCES budget_categories(id) ON DELETE SET NULL,
            profile_id           uuid REFERENCES budget_profiles(id) ON DELETE SET NULL,
            date                 date NOT NULL,
            amount               numeric(12, 2) NOT NULL,
            currency             varchar(3) NOT NULL DEFAULT 'USD',
            description          text NOT NULL,
            merchant_name        text,
            notes                text,
            scope                varchar(20) NOT NULL DEFAULT 'private',
            split_override       jsonb,
            is_transfer          boolean NOT NULL DEFAULT false,
            import_source        varchar(20),
            external_id          varchar(200),
            dedup_hash           varchar(64),
            recurring            jsonb,
            recurring_template_id uuid REFERENCES budget_transactions(id) ON DELETE SET NULL,
            running_balance      numeric(14, 2),
            archived_at          timestamptz,
            created_at           timestamptz DEFAULT now() NOT NULL,
            updated_at           timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_targets (
            id           uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            profile_id   uuid NOT NULL REFERENCES budget_profiles(id) ON DELETE CASCADE,
            category_id  uuid NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
            year         integer NOT NULL,
            month        integer NOT NULL,
            amount       numeric(12, 2) NOT NULL,
            created_at   timestamptz DEFAULT now() NOT NULL,
            updated_at   timestamptz DEFAULT now() NOT NULL
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budget_rollover_amounts (
            id               uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            household_id     uuid NOT NULL REFERENCES households(id) ON DELETE CASCADE,
            category_id      uuid NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
            year             integer NOT NULL,
            month            integer NOT NULL,
            rollover_amount  numeric(12, 2) NOT NULL DEFAULT 0,
            computed_at      timestamptz DEFAULT now() NOT NULL
        )
    """))

    # Indexes for common query patterns
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_profiles_household ON budget_profiles(household_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_accounts_household ON budget_accounts(household_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_accounts_owner ON budget_accounts(owner_user_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_categories_household ON budget_categories(household_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_transactions_household ON budget_transactions(household_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_transactions_account ON budget_transactions(account_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_transactions_date ON budget_transactions(date)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_budget_transactions_category ON budget_transactions(category_id)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS budget_rollover_amounts"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_targets"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_transactions"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_categories"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_category_groups"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_accounts"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_profile_members"))
    op.execute(sa.text("DROP TABLE IF EXISTS budget_profiles"))
