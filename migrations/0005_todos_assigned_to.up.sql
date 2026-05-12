-- =============================================================================
-- Migration 0005 — todos: assigned_to_user_id + updated_at trigger
-- =============================================================================
-- Adds an optional assignment column so a todo can be assigned to any
-- household member. Also retrofits the updated_at DB trigger onto todos
-- (it was missed in migration 0001; the service layer currently writes it
-- explicitly — the trigger makes it authoritative and removes that burden).
--
-- Safe to run on a populated database. Existing todos get NULL assignment.
-- Runs in a single transaction.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Add assigned_to_user_id column
-- -----------------------------------------------------------------------------

ALTER TABLE public.todos
    ADD COLUMN assigned_to_user_id uuid
        REFERENCES public.users(id) ON DELETE SET NULL;

CREATE INDEX idx_todos_assigned_to_user_id
    ON public.todos USING btree (assigned_to_user_id);

-- -----------------------------------------------------------------------------
-- 2. Add the updated_at trigger (missed in migration 0001)
-- update_updated_at() already exists from the initial schema.
-- -----------------------------------------------------------------------------

CREATE TRIGGER todos_updated_at BEFORE UPDATE ON public.todos
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 3. Record migration
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version)
    VALUES ('0005_todos_assigned_to');

COMMIT;

-- =============================================================================
-- End migration 0005
-- =============================================================================
