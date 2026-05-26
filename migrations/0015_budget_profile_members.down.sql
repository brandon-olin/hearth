BEGIN;
DROP TABLE IF EXISTS public.budget_profile_members;
DELETE FROM public.schema_migrations WHERE version = '0015_budget_profile_members';
COMMIT;
