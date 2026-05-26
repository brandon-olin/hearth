BEGIN;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS balance_updated_at;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS current_balance;
DELETE FROM public.schema_migrations WHERE version = '0018_budget_account_balance';
COMMIT;
