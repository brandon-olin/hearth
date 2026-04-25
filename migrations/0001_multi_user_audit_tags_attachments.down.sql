-- =============================================================================
-- Migration 0001 — ROLLBACK
-- =============================================================================
-- Reverses the Phase-0 migration. Drops all new tables and columns.
-- WARNING: This will destroy any data written to users, households,
-- household_memberships, refresh_tokens, audit_log, attachments, tags,
-- and taggings. Existing rows in goals/todos/etc. are preserved; only
-- the household_id and created_by_user_id columns are dropped from them.
-- =============================================================================

BEGIN;

-- Drop indexes on retrofitted tables
DROP INDEX IF EXISTS public.idx_goals_household_id;
DROP INDEX IF EXISTS public.idx_todos_household_id;
DROP INDEX IF EXISTS public.idx_notes_household_id;
DROP INDEX IF EXISTS public.idx_calendar_events_household_id;
DROP INDEX IF EXISTS public.idx_contacts_household_id;
DROP INDEX IF EXISTS public.idx_habits_household_id;
DROP INDEX IF EXISTS public.idx_recipes_household_id;
DROP INDEX IF EXISTS public.idx_grocery_lists_household_id;

-- Drop retrofitted columns (FKs drop automatically with the columns)
ALTER TABLE public.goals           DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.todos           DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.notes           DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.calendar_events DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.contacts        DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.habits          DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.recipes         DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.grocery_lists   DROP COLUMN IF EXISTS household_id, DROP COLUMN IF EXISTS created_by_user_id;

-- Drop the updated_at triggers we added (keep the pre-existing goals/todos ones)
DROP TRIGGER IF EXISTS households_updated_at        ON public.households;
DROP TRIGGER IF EXISTS users_updated_at             ON public.users;
DROP TRIGGER IF EXISTS notes_updated_at             ON public.notes;
DROP TRIGGER IF EXISTS calendar_events_updated_at   ON public.calendar_events;
DROP TRIGGER IF EXISTS contacts_updated_at          ON public.contacts;
DROP TRIGGER IF EXISTS habits_updated_at            ON public.habits;
DROP TRIGGER IF EXISTS habit_occurrences_updated_at ON public.habit_occurrences;
DROP TRIGGER IF EXISTS recipes_updated_at           ON public.recipes;
DROP TRIGGER IF EXISTS grocery_lists_updated_at     ON public.grocery_lists;
DROP TRIGGER IF EXISTS grocery_items_updated_at     ON public.grocery_items;

-- Drop new tables (order matters for FK dependencies)
DROP TABLE IF EXISTS public.taggings;
DROP TABLE IF EXISTS public.tags;
DROP TABLE IF EXISTS public.attachments;
DROP TABLE IF EXISTS public.audit_log;
DROP TABLE IF EXISTS public.refresh_tokens;
DROP TABLE IF EXISTS public.household_memberships;
DROP TABLE IF EXISTS public.users;
DROP TABLE IF EXISTS public.households;

-- Drop new enum types
DROP TYPE IF EXISTS public.membership_role;
DROP TYPE IF EXISTS public.actor_type;

-- Remove migration tracking row (keep the schema_migrations table itself —
-- it'll be useful for future migrations even if this one is rolled back)
DELETE FROM public.schema_migrations WHERE version = '0001_multi_user_audit_tags_attachments';

COMMIT;
