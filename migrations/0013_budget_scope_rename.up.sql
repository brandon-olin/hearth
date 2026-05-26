-- =============================================================================
-- Migration 0013 — budget scope rename (budget-010)
-- =============================================================================
-- Cleanly decouples 'scope' (visibility within a profile) from 'profile'
-- (financial context/attribution).
--
-- Renames scope enum values:
--   budget_transactions.scope:    'personal'  → 'private'
--                                  'household' → 'shared'
--   budget_categories.default_scope: 'personal' → 'private'
--                                    'household' → 'shared'
--
-- budget_accounts.scope stays unchanged ('personal' / 'shared') since those
-- names were already correct — account scope expresses ownership visibility.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. budget_transactions.scope — drop old constraint, rename values, add new
-- -----------------------------------------------------------------------------

-- Drop the inline check constraint (Postgres auto-names it <table>_<col>_check)
ALTER TABLE public.budget_transactions
    DROP CONSTRAINT IF EXISTS budget_transactions_scope_check;

UPDATE public.budget_transactions SET scope = 'private' WHERE scope = 'personal';
UPDATE public.budget_transactions SET scope = 'shared'  WHERE scope = 'household';

ALTER TABLE public.budget_transactions
    ADD CONSTRAINT budget_transactions_scope_check
    CHECK (scope IN ('private', 'shared'));

-- -----------------------------------------------------------------------------
-- 2. budget_categories.default_scope — drop old constraint, rename values, add new
-- -----------------------------------------------------------------------------

ALTER TABLE public.budget_categories
    DROP CONSTRAINT IF EXISTS budget_categories_default_scope_check;

UPDATE public.budget_categories SET default_scope = 'private' WHERE default_scope = 'personal';
UPDATE public.budget_categories SET default_scope = 'shared'  WHERE default_scope = 'household';

ALTER TABLE public.budget_categories
    ADD CONSTRAINT budget_categories_default_scope_check
    CHECK (default_scope IN ('private', 'shared'));

-- -----------------------------------------------------------------------------
-- 3. Record migration
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version)
    VALUES ('0013_budget_scope_rename');

COMMIT;

-- =============================================================================
-- End migration 0013
-- =============================================================================
