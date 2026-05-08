-- =============================================================================
-- Migration 0003 — ROLLBACK
-- =============================================================================
-- Reverses the AI layer migration. Drops all four AI tables and their
-- associated enum types.
--
-- WARNING: This permanently deletes all conversation history, messages,
-- per-user memory, and AI settings. There is no recovery path.
-- =============================================================================

BEGIN;

-- Drop indexes first (some are dropped implicitly with tables, but explicit is
-- safer and makes the rollback intent clear).
DROP INDEX IF EXISTS public.idx_ai_messages_search_vector;
DROP INDEX IF EXISTS public.idx_ai_messages_conversation_id;
DROP INDEX IF EXISTS public.idx_ai_conversations_household_id;
DROP INDEX IF EXISTS public.idx_ai_conversations_user_id;

-- Drop tables in dependency order (messages → conversations, then independents).
DROP TABLE IF EXISTS public.ai_messages;
DROP TABLE IF EXISTS public.ai_conversations;
DROP TABLE IF EXISTS public.member_ai_memory;
DROP TABLE IF EXISTS public.ai_settings;

-- Drop enum types.
DROP TYPE IF EXISTS public.ai_provider;
DROP TYPE IF EXISTS public.ai_message_role;

-- Remove migration tracking row.
DELETE FROM public.schema_migrations WHERE version = '0003_ai_layer';

COMMIT;

-- =============================================================================
-- End migration 0003 rollback
-- =============================================================================
