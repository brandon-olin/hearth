BEGIN;

-- Teller bank sync (budget-teller): add connection state to budget_accounts.
--
-- teller_enrollment_id  — Teller enrollment ID returned by Teller Connect
-- teller_access_token   — per-enrollment access token; used as Basic-auth username
--                         on all Teller API calls for this account
-- teller_account_id     — Teller's internal account identifier (distinct from our UUID)
-- teller_institution_name — human-readable bank name ("Chase", "Wells Fargo", …)
-- teller_last_synced_at — timestamp of the last successful polling sync
-- teller_cursor         — most recent Teller transaction ID seen; passed as `from_id`
--                         on the next sync to fetch only new transactions

ALTER TABLE public.budget_accounts
    ADD COLUMN IF NOT EXISTS teller_enrollment_id   VARCHAR(200)  NULL,
    ADD COLUMN IF NOT EXISTS teller_access_token    TEXT          NULL,
    ADD COLUMN IF NOT EXISTS teller_account_id      VARCHAR(200)  NULL,
    ADD COLUMN IF NOT EXISTS teller_institution_name VARCHAR(200) NULL,
    ADD COLUMN IF NOT EXISTS teller_last_synced_at  TIMESTAMPTZ   NULL,
    ADD COLUMN IF NOT EXISTS teller_cursor          VARCHAR(200)  NULL;

INSERT INTO public.schema_migrations (version) VALUES ('0019_teller_bank_sync');

COMMIT;
