BEGIN;

-- budget-017: Add current_balance to budget_accounts.
-- Manually maintained — users enter the balance from their bank statement.
-- NULL means unknown / not set. Displayed alongside account name in the UI.

ALTER TABLE public.budget_accounts
    ADD COLUMN IF NOT EXISTS current_balance NUMERIC(14, 2) NULL,
    ADD COLUMN IF NOT EXISTS balance_updated_at TIMESTAMPTZ NULL;

INSERT INTO public.schema_migrations (version) VALUES ('0018_budget_account_balance');

COMMIT;
