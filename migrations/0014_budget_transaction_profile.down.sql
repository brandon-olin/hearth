BEGIN;
ALTER TABLE public.budget_transactions DROP COLUMN IF EXISTS profile_id;
DELETE FROM public.schema_migrations WHERE version = '0014_budget_transaction_profile';
COMMIT;
