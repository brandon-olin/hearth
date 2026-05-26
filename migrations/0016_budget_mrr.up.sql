-- =============================================================================
-- Migration 0016 — budget MRR tracking (budget-013)
-- =============================================================================
-- Adds is_recurring_revenue flag to budget_categories for Business profiles.
-- When set, the analytics layer reports actual MRR, projected ARR, and
-- month-over-month growth for profit_tracking profiles.
-- =============================================================================

BEGIN;

ALTER TABLE public.budget_categories
    ADD COLUMN is_recurring_revenue boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.budget_categories.is_recurring_revenue IS
    'Profit-tracking profiles only. When true, income transactions in this '
    'category count toward MRR / ARR reporting.';

INSERT INTO public.schema_migrations (version)
    VALUES ('0016_budget_mrr');

COMMIT;

-- =============================================================================
-- End migration 0016
-- =============================================================================
