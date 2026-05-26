BEGIN;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS teller_cursor;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS teller_last_synced_at;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS teller_institution_name;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS teller_account_id;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS teller_access_token;
ALTER TABLE public.budget_accounts DROP COLUMN IF EXISTS teller_enrollment_id;
DELETE FROM public.schema_migrations WHERE version = '0019_teller_bank_sync';
COMMIT;
