-- =============================================================================
-- Migration 0012 — budget profiles foundation (budget-009)
-- =============================================================================
-- Introduces budget_profiles as a named financial context sitting above the
-- personal/household scope distinction. Each household gets two default
-- profiles seeded on creation: 'Personal' and 'Household'.
--
-- Adds profile_id FK to:
--   budget_accounts, budget_categories, budget_category_groups, budget_targets
--
-- Backfill rules:
--   accounts with scope='personal'   → Personal profile
--   accounts with scope='shared'     → Household profile
--   categories with default_scope='personal'  → Personal profile
--   categories with default_scope='household' → Household profile
--   category_groups → Household profile (groups are a household-level concept)
--   budget_targets  → inherit from their category's profile
--
-- The budgeting_style column ('zero_based' | 'profit_tracking') is included
-- here so that Business profiles (budget-012) can be created by just setting
-- budgeting_style='profit_tracking' on a new profile — no further migration needed.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. budget_profiles table
-- -----------------------------------------------------------------------------

CREATE TABLE public.budget_profiles (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id    uuid        NOT NULL REFERENCES public.households(id) ON DELETE CASCADE,

    name            varchar(100) NOT NULL,
    -- zero_based  = YNAB-style envelope budgeting (Personal / Household profiles)
    -- profit_tracking = P&L view; revenue vs expenses; no envelopes (Business profile)
    budgeting_style varchar(20)  NOT NULL DEFAULT 'zero_based'
                        CHECK (budgeting_style IN ('zero_based', 'profit_tracking')),
    currency        char(3)      NOT NULL DEFAULT 'USD',
    sort_order      integer      NOT NULL DEFAULT 0,

    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_profiles_household_id ON public.budget_profiles USING btree (household_id);

CREATE TRIGGER budget_profiles_updated_at
    BEFORE UPDATE ON public.budget_profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 2. Seed default profiles for every existing household
-- -----------------------------------------------------------------------------

INSERT INTO public.budget_profiles (household_id, name, budgeting_style, sort_order)
SELECT id, 'Personal', 'zero_based', 1
FROM public.households;

INSERT INTO public.budget_profiles (household_id, name, budgeting_style, sort_order)
SELECT id, 'Household', 'zero_based', 2
FROM public.households;

-- -----------------------------------------------------------------------------
-- 3. Add profile_id to budget_accounts (nullable initially, set NOT NULL after backfill)
-- -----------------------------------------------------------------------------

ALTER TABLE public.budget_accounts
    ADD COLUMN profile_id uuid REFERENCES public.budget_profiles(id) ON DELETE SET NULL;

-- Backfill: personal accounts → Personal profile; shared accounts → Household profile
UPDATE public.budget_accounts ba
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE ba.household_id = bp.household_id
  AND bp.name = 'Personal'
  AND ba.scope = 'personal';

UPDATE public.budget_accounts ba
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE ba.household_id = bp.household_id
  AND bp.name = 'Household'
  AND ba.scope = 'shared';

-- Any accounts that fell through (shouldn't happen) → Personal as fallback
UPDATE public.budget_accounts ba
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE ba.profile_id IS NULL
  AND ba.household_id = bp.household_id
  AND bp.name = 'Personal';

ALTER TABLE public.budget_accounts
    ALTER COLUMN profile_id SET NOT NULL;

CREATE INDEX idx_budget_accounts_profile_id ON public.budget_accounts USING btree (profile_id);

-- -----------------------------------------------------------------------------
-- 4. Add profile_id to budget_categories
-- -----------------------------------------------------------------------------

ALTER TABLE public.budget_categories
    ADD COLUMN profile_id uuid REFERENCES public.budget_profiles(id) ON DELETE SET NULL;

-- Backfill: personal-default categories → Personal; household-default → Household
UPDATE public.budget_categories bc
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE bc.household_id = bp.household_id
  AND bp.name = 'Personal'
  AND bc.default_scope = 'personal';

UPDATE public.budget_categories bc
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE bc.household_id = bp.household_id
  AND bp.name = 'Household'
  AND bc.default_scope = 'household';

-- Fallback for any remaining (NULL default_scope rows, shouldn't exist)
UPDATE public.budget_categories bc
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE bc.profile_id IS NULL
  AND bc.household_id = bp.household_id
  AND bp.name = 'Personal';

ALTER TABLE public.budget_categories
    ALTER COLUMN profile_id SET NOT NULL;

CREATE INDEX idx_budget_categories_profile_id ON public.budget_categories USING btree (profile_id);

-- -----------------------------------------------------------------------------
-- 5. Add profile_id to budget_category_groups
-- -----------------------------------------------------------------------------

ALTER TABLE public.budget_category_groups
    ADD COLUMN profile_id uuid REFERENCES public.budget_profiles(id) ON DELETE SET NULL;

-- Groups are a household-level concept → assign to Household profile
UPDATE public.budget_category_groups bcg
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE bcg.household_id = bp.household_id
  AND bp.name = 'Household';

-- Fallback
UPDATE public.budget_category_groups bcg
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE bcg.profile_id IS NULL
  AND bcg.household_id = bp.household_id
  AND bp.name = 'Personal';

ALTER TABLE public.budget_category_groups
    ALTER COLUMN profile_id SET NOT NULL;

CREATE INDEX idx_budget_category_groups_profile_id ON public.budget_category_groups USING btree (profile_id);

-- -----------------------------------------------------------------------------
-- 6. Add profile_id to budget_targets (inherit from their category)
-- -----------------------------------------------------------------------------

ALTER TABLE public.budget_targets
    ADD COLUMN profile_id uuid REFERENCES public.budget_profiles(id) ON DELETE SET NULL;

UPDATE public.budget_targets bt
SET profile_id = bc.profile_id
FROM public.budget_categories bc
WHERE bt.category_id = bc.id;

-- Fallback for orphaned targets
UPDATE public.budget_targets bt
SET profile_id = bp.id
FROM public.budget_profiles bp
WHERE bt.profile_id IS NULL
  AND bt.household_id = bp.household_id
  AND bp.name = 'Personal';

ALTER TABLE public.budget_targets
    ALTER COLUMN profile_id SET NOT NULL;

CREATE INDEX idx_budget_targets_profile_id ON public.budget_targets USING btree (profile_id);

-- -----------------------------------------------------------------------------
-- 7. Record migration
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version)
    VALUES ('0012_budget_profiles');

COMMIT;

-- =============================================================================
-- End migration 0012
-- =============================================================================
