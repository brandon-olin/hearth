BEGIN;
DROP INDEX IF EXISTS public.idx_budget_txn_recurring_template;
DROP INDEX IF EXISTS public.idx_budget_txn_recurring;
ALTER TABLE public.budget_transactions DROP COLUMN IF EXISTS recurring_template_id;
ALTER TABLE public.budget_transactions DROP COLUMN IF EXISTS recurring;
DELETE FROM public.schema_migrations WHERE version = '0017_budget_recurring';
COMMIT;
