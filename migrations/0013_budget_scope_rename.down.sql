-- =============================================================================
-- Migration 0013 — budget scope rename (DOWN)
-- =============================================================================

BEGIN;

ALTER TABLE public.budget_transactions
    DROP CONSTRAINT IF EXISTS budget_transactions_scope_check;
UPDATE public.budget_transactions SET scope = 'personal'  WHERE scope = 'private';
UPDATE public.budget_transactions SET scope = 'household' WHERE scope = 'shared';
ALTER TABLE public.budget_transactions
    ADD CONSTRAINT budget_transactions_scope_check
    CHECK (scope IN ('personal', 'household'));

ALTER TABLE public.budget_categories
    DROP CONSTRAINT IF EXISTS budget_categories_default_scope_check;
UPDATE public.budget_categories SET default_scope = 'personal'  WHERE default_scope = 'private';
UPDATE public.budget_categories SET default_scope = 'household' WHERE default_scope = 'shared';
ALTER TABLE public.budget_categories
    ADD CONSTRAINT budget_categories_default_scope_check
    CHECK (default_scope IN ('personal', 'household'));

DELETE FROM public.schema_migrations WHERE version = '0013_budget_scope_rename';

COMMIT;
