-- =============================================================================
-- Migration 0015 — budget profile member access control (budget-014)
-- =============================================================================
-- Adds explicit per-profile membership with roles, replacing the implicit
-- "all household members see everything" default.
--
-- Role semantics:
--   owner  — can edit profile settings, manage members, delete the profile
--   member — can add/edit transactions, categories, targets
--   viewer — read-only access to analytics and transactions
--
-- On creation, profiles default to including all household members as 'member'
-- (preserving existing behaviour). Only one 'owner' per profile is allowed
-- (enforced at the service layer, not by a DB constraint).
-- =============================================================================

BEGIN;

CREATE TABLE public.budget_profile_members (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id  uuid        NOT NULL REFERENCES public.budget_profiles(id) ON DELETE CASCADE,
    user_id     uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    role        varchar(10)  NOT NULL DEFAULT 'member'
                    CHECK (role IN ('owner', 'member', 'viewer')),

    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),

    UNIQUE (profile_id, user_id)
);

CREATE INDEX idx_budget_profile_members_profile_id ON public.budget_profile_members USING btree (profile_id);
CREATE INDEX idx_budget_profile_members_user_id    ON public.budget_profile_members USING btree (user_id);

CREATE TRIGGER budget_profile_members_updated_at
    BEFORE UPDATE ON public.budget_profile_members
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- Seed existing profile memberships:
--   For each existing profile, insert all household members as 'member'.
--   The household owner gets 'owner' role; others get 'member'.
-- -----------------------------------------------------------------------------

INSERT INTO public.budget_profile_members (profile_id, user_id, role)
SELECT
    bp.id      AS profile_id,
    u.id       AS user_id,
    CASE WHEN u.role = 'owner' THEN 'owner' ELSE 'member' END AS role
FROM public.budget_profiles bp
JOIN public.users u ON u.household_id = bp.household_id
ON CONFLICT (profile_id, user_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Record migration
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version)
    VALUES ('0015_budget_profile_members');

COMMIT;

-- =============================================================================
-- End migration 0015
-- =============================================================================
