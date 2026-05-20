-- =============================================================================
-- Migration 0006 — budget foundation (rollback)
-- =============================================================================
-- Drops all budget tables in reverse dependency order.
-- WARNING: this is destructive — all budget data will be lost.
-- =============================================================================

BEGIN;

DROP TABLE IF EXISTS public.budget_transactions CASCADE;
DROP TABLE IF EXISTS public.budget_categories    CASCADE;
DROP TABLE IF EXISTS public.budget_accounts      CASCADE;

DELETE FROM public.schema_migrations WHERE version = '0006_budget_foundation';

COMMIT;

-- =============================================================================
-- End rollback 0006
-- =============================================================================
