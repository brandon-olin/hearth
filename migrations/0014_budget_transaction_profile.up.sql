-- =============================================================================
-- Migration 0014 — budget transaction profile override (budget-011)
-- =============================================================================
-- Adds a nullable profile_id override column to budget_transactions.
--
-- When set, this overrides the account's profile for analytics, categorization,
-- and visibility. The transaction physically stays linked to its account (for
-- balance tracking) but analytically lives in the target profile.
--
-- Analytics resolution: COALESCE(txn.profile_id, account.profile_id)
-- =============================================================================

BEGIN;

ALTER TABLE public.budget_transactions
    ADD COLUMN profile_id uuid REFERENCES public.budget_profiles(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.budget_transactions.profile_id IS
    'Optional: overrides account.profile_id for analytics purposes only. '
    'When NULL, the transaction''s analytical profile is inherited from its account.';

CREATE INDEX idx_budget_transactions_profile_id
    ON public.budget_transactions (profile_id)
    WHERE profile_id IS NOT NULL;

INSERT INTO public.schema_migrations (version)
    VALUES ('0014_budget_transaction_profile');

COMMIT;

-- =============================================================================
-- End migration 0014
-- =============================================================================
