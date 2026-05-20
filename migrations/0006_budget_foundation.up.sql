-- =============================================================================
-- Migration 0006 — budget foundation
-- =============================================================================
-- Creates the three core tables for the budgeting domain:
--
--   budget_accounts      — financial accounts (checking, savings, credit cards…)
--                          scoped to a household member; marked personal or shared
--
--   budget_categories    — spending categories at the household level; hold the
--                          household split_config (per-member ratio JSONB)
--
--   budget_transactions  — normalised transaction records imported from any
--                          source (CSV, OFX, manual entry); dedup via hash +
--                          external_id; scope mirrors the account at import time
--
-- Amount convention: negative = expense/payment, positive = income/refund.
-- Dedup hash: SHA-256(account_id | date | amount | description), hex-encoded.
--
-- Safe to run on a populated database. Runs in a single transaction.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. budget_accounts
-- -----------------------------------------------------------------------------

CREATE TABLE public.budget_accounts (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    uuid        NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,
    owner_user_id   uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    name            varchar(200) NOT NULL,
    account_type    varchar(20)  NOT NULL DEFAULT 'checking'
                        CHECK (account_type IN ('checking','savings','credit_card','loan','investment','other')),
    -- personal = only owner sees transactions; shared = visible to all household members
    scope           varchar(20)  NOT NULL DEFAULT 'personal'
                        CHECK (scope IN ('personal','shared')),
    currency        char(3)      NOT NULL DEFAULT 'USD',

    archived_at     timestamptz,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_accounts_household_id  ON public.budget_accounts USING btree (household_id);
CREATE INDEX idx_budget_accounts_owner_user_id ON public.budget_accounts USING btree (owner_user_id);

CREATE TRIGGER budget_accounts_updated_at
    BEFORE UPDATE ON public.budget_accounts
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 2. budget_categories
-- -----------------------------------------------------------------------------

CREATE TABLE public.budget_categories (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    uuid        NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,

    name            varchar(100) NOT NULL,
    -- Whether transactions auto-assigned here are personal or shared by default
    default_scope   varchar(20)  NOT NULL DEFAULT 'personal'
                        CHECK (default_scope IN ('personal','household')),
    -- Per-member split ratios. NULL = equal split.
    -- Shape: { "<user_id>": <ratio_float> }  — ratios must sum to 1.0.
    split_config    jsonb,

    color           varchar(20),   -- CSS colour token or hex value, for UI
    icon            varchar(10),   -- single emoji
    sort_order      integer        NOT NULL DEFAULT 0,

    archived_at     timestamptz,
    created_at      timestamptz    NOT NULL DEFAULT now(),
    updated_at      timestamptz    NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_categories_household_id ON public.budget_categories USING btree (household_id);

CREATE TRIGGER budget_categories_updated_at
    BEFORE UPDATE ON public.budget_categories
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 3. budget_transactions
-- -----------------------------------------------------------------------------

CREATE TABLE public.budget_transactions (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    uuid        NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,
    account_id      uuid        NOT NULL REFERENCES public.budget_accounts(id) ON DELETE CASCADE,
    -- Denormalised from account.owner_user_id for efficient personal-view queries
    owner_user_id   uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    category_id     uuid        REFERENCES public.budget_categories(id) ON DELETE SET NULL,

    date            date         NOT NULL,
    -- Negative = expense/payment; positive = income/refund/transfer received
    amount          numeric(12,2) NOT NULL,
    currency        char(3)       NOT NULL DEFAULT 'USD',

    description     text         NOT NULL,       -- raw bank description
    merchant_name   text,                        -- cleaned/AI-enriched name
    notes           text,                        -- user notes

    -- personal = only owner sees it; household = shared + split applies
    scope           varchar(20)  NOT NULL DEFAULT 'personal'
                        CHECK (scope IN ('personal','household')),
    -- Per-transaction override of category split_config.
    -- NULL = use category split_config (or equal split if also NULL).
    split_override  jsonb,

    import_source   varchar(20)
                        CHECK (import_source IN ('csv','ofx','manual','teller','plaid')),
    -- Bank-provided transaction ID (OFX FITID, Teller/Plaid id) — secondary dedup key
    external_id     varchar(200),
    -- SHA-256(account_id|date|amount|description) hex — primary dedup key for file imports
    dedup_hash      char(64),

    archived_at     timestamptz,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_transactions_household_id  ON public.budget_transactions USING btree (household_id);
CREATE INDEX idx_budget_transactions_account_id    ON public.budget_transactions USING btree (account_id);
CREATE INDEX idx_budget_transactions_owner_user_id ON public.budget_transactions USING btree (owner_user_id);
CREATE INDEX idx_budget_transactions_category_id   ON public.budget_transactions USING btree (category_id);
CREATE INDEX idx_budget_transactions_date          ON public.budget_transactions USING btree (date DESC);
-- Partial unique indexes for deduplication — only enforce when value is present
CREATE UNIQUE INDEX idx_budget_transactions_external_id_uniq
    ON public.budget_transactions (account_id, external_id)
    WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX idx_budget_transactions_dedup_hash_uniq
    ON public.budget_transactions (account_id, dedup_hash)
    WHERE dedup_hash IS NOT NULL;

CREATE TRIGGER budget_transactions_updated_at
    BEFORE UPDATE ON public.budget_transactions
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 4. Record migration
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version)
    VALUES ('0006_budget_foundation');

COMMIT;

-- =============================================================================
-- End migration 0006
-- =============================================================================
