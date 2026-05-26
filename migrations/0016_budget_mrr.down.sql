BEGIN;
ALTER TABLE public.budget_categories DROP COLUMN IF EXISTS is_recurring_revenue;
DELETE FROM public.schema_migrations WHERE version = '0016_budget_mrr';
COMMIT;
