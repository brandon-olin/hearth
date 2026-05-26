BEGIN;

-- Add recurring JSONB rule to transactions (NULL = not recurring)
-- Shape: { "frequency": "monthly"|"weekly", "interval": int, "end_date": str|null }
ALTER TABLE public.budget_transactions
    ADD COLUMN IF NOT EXISTS recurring JSONB NULL;

-- Self-referential FK: generated instances point back to their template
ALTER TABLE public.budget_transactions
    ADD COLUMN IF NOT EXISTS recurring_template_id UUID NULL
        REFERENCES public.budget_transactions(id) ON DELETE SET NULL;

-- Index for efficient "find all instances of template X" queries
CREATE INDEX IF NOT EXISTS idx_budget_txn_recurring_template
    ON public.budget_transactions(recurring_template_id)
    WHERE recurring_template_id IS NOT NULL;

-- Index for efficient "find all recurring templates" queries
CREATE INDEX IF NOT EXISTS idx_budget_txn_recurring
    ON public.budget_transactions(household_id)
    WHERE recurring IS NOT NULL;

INSERT INTO public.schema_migrations (version) VALUES ('0017_budget_recurring');

COMMIT;
