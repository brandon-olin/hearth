-- =============================================================================
-- Migration 0012 — budget profiles foundation (DOWN)
-- =============================================================================

BEGIN;

ALTER TABLE public.budget_targets       DROP COLUMN IF EXISTS profile_id;
ALTER TABLE public.budget_category_groups DROP COLUMN IF EXISTS profile_id;
ALTER TABLE public.budget_categories    DROP COLUMN IF EXISTS profile_id;
ALTER TABLE public.budget_accounts      DROP COLUMN IF EXISTS profile_id;

DROP TABLE IF EXISTS public.budget_profiles;

DELETE FROM public.schema_migrations WHERE version = '0012_budget_profiles';

COMMIT;
