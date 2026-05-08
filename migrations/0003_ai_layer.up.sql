-- =============================================================================
-- Migration 0003 — AI layer
-- =============================================================================
-- Adds four tables that underpin the AI assistant feature:
--
--   ai_conversations     — one row per chat session, scoped to a user
--   ai_messages          — individual turns within a conversation, with a
--                          generated tsvector column for full-text search
--   member_ai_memory     — one row per user; a small curated text document
--                          describing the user; updated lazily after chats
--   ai_settings          — per-user provider choice, optional BYOK key, and
--                          conversation retention policy
--
-- Design notes:
--   • ai_conversations is scoped to BOTH user_id and household_id so that the
--     service can efficiently query "all conversations in this household" for
--     admin/audit purposes without joining through users.
--   • ai_messages.search_vector is a STORED generated column — it is updated
--     automatically by Postgres on insert/update, requires no application code,
--     and is indexed via GIN for fast full-text search.
--   • ai_settings.api_key_encrypted is nullable; NULL means "use the system
--     key from environment". This is the BYOK hook — populate later without a
--     schema change.
--   • retention_days has a CHECK constraint limiting it to the values exposed
--     in the UI (30 / 60 / 90 / 180 / 365 days), plus NULL for "keep forever".
--     Default is 90 days.
--
-- Safe to run on a populated database. Runs in a single transaction.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. New enum types
-- -----------------------------------------------------------------------------

CREATE TYPE public.ai_message_role AS ENUM ('user', 'assistant', 'tool');
ALTER TYPE public.ai_message_role OWNER TO brandon;

CREATE TYPE public.ai_provider AS ENUM ('anthropic', 'openai', 'ollama');
ALTER TYPE public.ai_provider OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 2. ai_conversations
-- -----------------------------------------------------------------------------

CREATE TABLE public.ai_conversations (
    id               uuid                     DEFAULT gen_random_uuid() NOT NULL,
    user_id          uuid                     NOT NULL,
    household_id     uuid                     NOT NULL,
    -- Title is auto-generated from the first user message by the service layer;
    -- NULL until that first message is saved.
    title            text,
    created_at       timestamp with time zone DEFAULT now() NOT NULL,
    last_message_at  timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ai_conversations_pkey PRIMARY KEY (id),
    CONSTRAINT ai_conversations_user_id_fkey
        FOREIGN KEY (user_id)      REFERENCES public.users(id)      ON DELETE CASCADE,
    CONSTRAINT ai_conversations_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE
);
ALTER TABLE public.ai_conversations OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 3. ai_messages
-- -----------------------------------------------------------------------------

CREATE TABLE public.ai_messages (
    id               uuid                     DEFAULT gen_random_uuid() NOT NULL,
    conversation_id  uuid                     NOT NULL,
    role             public.ai_message_role   NOT NULL,
    -- Raw text content. For 'tool' role rows this is a JSON string (tool call
    -- input/output); the search vector indexes it as plain text regardless.
    content          text                     NOT NULL,
    -- Generated column: kept in sync by Postgres automatically.
    -- Used for full-text search across conversation history.
    search_vector    tsvector                 GENERATED ALWAYS AS (
                         to_tsvector('english', content)
                     ) STORED,
    created_at       timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ai_messages_pkey PRIMARY KEY (id),
    CONSTRAINT ai_messages_conversation_id_fkey
        FOREIGN KEY (conversation_id) REFERENCES public.ai_conversations(id) ON DELETE CASCADE
);
ALTER TABLE public.ai_messages OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 4. member_ai_memory
-- -----------------------------------------------------------------------------

CREATE TABLE public.member_ai_memory (
    user_id                          uuid                     NOT NULL,
    -- Curated natural-language profile of the user, ~500-800 tokens.
    -- Empty string until enough conversations exist to populate it.
    memory_text                      text                     NOT NULL DEFAULT '',
    last_updated_at                  timestamp with time zone DEFAULT now() NOT NULL,
    -- Tracks the total conversation count at the time memory was last written,
    -- used to decide lazily whether a refresh is due.
    conversation_count_at_last_update integer                 NOT NULL DEFAULT 0,
    CONSTRAINT member_ai_memory_pkey PRIMARY KEY (user_id),
    CONSTRAINT member_ai_memory_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE
);
ALTER TABLE public.member_ai_memory OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 5. ai_settings
-- -----------------------------------------------------------------------------

CREATE TABLE public.ai_settings (
    user_id             uuid                  NOT NULL,
    provider            public.ai_provider    NOT NULL DEFAULT 'anthropic'::public.ai_provider,
    -- NULL → use the system-level key from server environment (ANTHROPIC_API_KEY).
    -- Non-null → user-supplied BYOK key, encrypted at rest by the service layer.
    api_key_encrypted   text,
    -- NULL → keep conversations forever.
    -- Integers are the allowed UI options; enforced by CHECK below.
    retention_days      integer               DEFAULT 90,
    CONSTRAINT ai_settings_pkey PRIMARY KEY (user_id),
    CONSTRAINT ai_settings_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT ai_settings_retention_days_check
        CHECK (retention_days IS NULL OR retention_days IN (30, 60, 90, 180, 365))
);
ALTER TABLE public.ai_settings OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 6. Indexes
-- -----------------------------------------------------------------------------

-- Conversations: look up by user (primary access pattern) and by household
-- (admin/audit). Order by recency for sidebar display.
CREATE INDEX idx_ai_conversations_user_id
    ON public.ai_conversations USING btree (user_id, last_message_at DESC);

CREATE INDEX idx_ai_conversations_household_id
    ON public.ai_conversations USING btree (household_id);

-- Messages: FK traversal from conversation, and GIN for full-text search.
CREATE INDEX idx_ai_messages_conversation_id
    ON public.ai_messages USING btree (conversation_id, created_at ASC);

CREATE INDEX idx_ai_messages_search_vector
    ON public.ai_messages USING gin (search_vector);

-- -----------------------------------------------------------------------------
-- 7. Record migration
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version)
    VALUES ('0003_ai_layer');

COMMIT;

-- =============================================================================
-- End migration 0003
-- =============================================================================
