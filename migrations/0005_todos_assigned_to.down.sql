-- =============================================================================
-- Migration 0005 — rollback
-- =============================================================================

BEGIN;

DROP TRIGGER IF EXISTS todos_updated_at ON public.todos;
DROP INDEX IF EXISTS idx_todos_assigned_to_user_id;
ALTER TABLE public.todos DROP COLUMN IF EXISTS assigned_to_user_id;

DELETE FROM public.schema_migrations WHERE version = '0005_todos_assigned_to';

COMMIT;
