-- =============================================================================
-- Migration 0000 — Bootstrap (fresh install squash)
-- =============================================================================
-- Creates the full schema from scratch. Use this instead of running migrations
-- 0001–0005 sequentially on a new database. On a database that was set up
-- with the NAS/production Docker stack, skip this file and run 0001–0005 as
-- normal — they are idempotent-safe on an existing schema.
--
-- After this runs, start the API: it will detect the sentinel password hash
-- and prompt you to set an initial password via /auth/bootstrap.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Enum types
-- -----------------------------------------------------------------------------

CREATE TYPE public.actor_type       AS ENUM ('user', 'agent', 'system');
CREATE TYPE public.membership_role  AS ENUM ('owner', 'admin', 'member', 'viewer', 'agent');
CREATE TYPE public.priority_level   AS ENUM ('low', 'medium', 'high');
CREATE TYPE public.collection_domain AS ENUM ('notes', 'documents');
CREATE TYPE public.document_kind    AS ENUM ('page', 'template');
CREATE TYPE public.ai_message_role  AS ENUM ('user', 'assistant', 'tool');
CREATE TYPE public.ai_provider      AS ENUM ('anthropic', 'openai', 'ollama');
CREATE TYPE public.exercise_type    AS ENUM ('strength', 'cardio', 'hiit', 'flexibility', 'other');

-- -----------------------------------------------------------------------------
-- 2. updated_at trigger function
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- 3. Core identity tables
-- -----------------------------------------------------------------------------

CREATE TABLE public.households (
    id         uuid                     DEFAULT gen_random_uuid() NOT NULL,
    name       character varying(200)   NOT NULL,
    created_at timestamp with time zone DEFAULT now()             NOT NULL,
    updated_at timestamp with time zone DEFAULT now()             NOT NULL,
    CONSTRAINT households_pkey PRIMARY KEY (id)
);

CREATE TABLE public.users (
    id            uuid                     DEFAULT gen_random_uuid() NOT NULL,
    email         character varying(320)   NOT NULL,
    password_hash text                     NOT NULL,
    display_name  character varying(200),
    is_active     boolean                  DEFAULT true              NOT NULL,
    is_agent      boolean                  DEFAULT false             NOT NULL,
    last_login_at timestamp with time zone,
    preferences   jsonb,
    created_at    timestamp with time zone DEFAULT now()             NOT NULL,
    updated_at    timestamp with time zone DEFAULT now()             NOT NULL,
    CONSTRAINT users_pkey       PRIMARY KEY (id),
    CONSTRAINT users_email_key  UNIQUE (email)
);

CREATE TABLE public.household_memberships (
    id           uuid                        DEFAULT gen_random_uuid()                  NOT NULL,
    household_id uuid                        NOT NULL,
    user_id      uuid                        NOT NULL,
    role         public.membership_role      DEFAULT 'member'::public.membership_role   NOT NULL,
    joined_at    timestamp with time zone    DEFAULT now()                              NOT NULL,
    CONSTRAINT household_memberships_pkey               PRIMARY KEY (id),
    CONSTRAINT household_memberships_household_user_key UNIQUE (household_id, user_id),
    CONSTRAINT household_memberships_household_id_fkey  FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT household_memberships_user_id_fkey       FOREIGN KEY (user_id)      REFERENCES public.users(id)      ON DELETE CASCADE
);

CREATE TABLE public.refresh_tokens (
    id         uuid                     DEFAULT gen_random_uuid() NOT NULL,
    user_id    uuid                     NOT NULL,
    token_hash text                     NOT NULL,
    user_agent text,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT refresh_tokens_pkey           PRIMARY KEY (id),
    CONSTRAINT refresh_tokens_token_hash_key UNIQUE (token_hash),
    CONSTRAINT refresh_tokens_user_id_fkey   FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 4. Audit log
-- -----------------------------------------------------------------------------

CREATE TABLE public.audit_log (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid,
    actor_type          public.actor_type         NOT NULL,
    actor_id            uuid,
    actor_label         character varying(200),
    entity_type         character varying(100)   NOT NULL,
    entity_id           uuid,
    action              character varying(50)    NOT NULL,
    diff                jsonb,
    metadata            jsonb,
    approved_by_user_id uuid,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT audit_log_pkey                    PRIMARY KEY (id),
    CONSTRAINT audit_log_household_id_fkey       FOREIGN KEY (household_id)        REFERENCES public.households(id) ON DELETE SET NULL,
    CONSTRAINT audit_log_approved_by_user_id_fkey FOREIGN KEY (approved_by_user_id) REFERENCES public.users(id)      ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 5. Goals
-- -----------------------------------------------------------------------------

CREATE TABLE public.goals (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    parent_id           uuid,
    title               text                     NOT NULL,
    description         text,
    status              character varying(50)    DEFAULT 'active' NOT NULL,
    priority            public.priority_level,
    target_value        numeric,
    current_value       numeric                  DEFAULT 0,
    unit                character varying(100),
    due_date            date,
    completed_at        timestamp with time zone,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT goals_pkey                  PRIMARY KEY (id),
    CONSTRAINT goals_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT goals_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)  ON DELETE SET NULL,
    CONSTRAINT goals_parent_id_fkey        FOREIGN KEY (parent_id)          REFERENCES public.goals(id)     ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 6. Todos
-- -----------------------------------------------------------------------------

CREATE TABLE public.todos (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    assigned_to_user_id uuid,
    parent_id           uuid,
    goal_id             uuid,
    title               text                     NOT NULL,
    description         text,
    status              character varying(50)    DEFAULT 'pending' NOT NULL,
    priority            public.priority_level,
    due_date            date,
    completed_at        timestamp with time zone,
    recurring           jsonb,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT todos_pkey                      PRIMARY KEY (id),
    CONSTRAINT todos_household_id_fkey         FOREIGN KEY (household_id)        REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT todos_created_by_user_id_fkey   FOREIGN KEY (created_by_user_id)  REFERENCES public.users(id)     ON DELETE SET NULL,
    CONSTRAINT todos_assigned_to_user_id_fkey  FOREIGN KEY (assigned_to_user_id) REFERENCES public.users(id)     ON DELETE SET NULL,
    CONSTRAINT todos_parent_id_fkey            FOREIGN KEY (parent_id)           REFERENCES public.todos(id)     ON DELETE SET NULL,
    CONSTRAINT todos_goal_id_fkey              FOREIGN KEY (goal_id)             REFERENCES public.goals(id)     ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 7. Recipes
-- -----------------------------------------------------------------------------

CREATE TABLE public.recipes (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    goal_id             uuid,
    name                character varying(500)   NOT NULL,
    description         text,
    cover_image_url     text,
    source_url          text,
    prep_time_minutes   integer,
    cook_time_minutes   integer,
    servings            integer,
    notes               text,
    body                jsonb,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT recipes_pkey                  PRIMARY KEY (id),
    CONSTRAINT recipes_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT recipes_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL,
    CONSTRAINT recipes_goal_id_fkey          FOREIGN KEY (goal_id)            REFERENCES public.goals(id)      ON DELETE SET NULL
);

CREATE TABLE public.recipe_ingredients (
    id         uuid    DEFAULT gen_random_uuid() NOT NULL,
    recipe_id  uuid    NOT NULL,
    name       text    NOT NULL,
    quantity   numeric,
    unit       character varying(100),
    notes      text,
    sort_order integer DEFAULT 0 NOT NULL,
    CONSTRAINT recipe_ingredients_pkey      PRIMARY KEY (id),
    CONSTRAINT recipe_ingredients_recipe_id_fkey FOREIGN KEY (recipe_id) REFERENCES public.recipes(id) ON DELETE CASCADE
);

CREATE TABLE public.recipe_steps (
    id          uuid    DEFAULT gen_random_uuid() NOT NULL,
    recipe_id   uuid    NOT NULL,
    step_number integer NOT NULL,
    instruction text    NOT NULL,
    notes       text,
    CONSTRAINT recipe_steps_pkey         PRIMARY KEY (id),
    CONSTRAINT recipe_steps_recipe_id_fkey FOREIGN KEY (recipe_id) REFERENCES public.recipes(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 8. Grocery lists
-- -----------------------------------------------------------------------------

CREATE TABLE public.grocery_lists (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    todo_id             uuid,
    name                character varying(500)   NOT NULL,
    store               character varying(200),
    status              character varying(50)    DEFAULT 'active' NOT NULL,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT grocery_lists_pkey                  PRIMARY KEY (id),
    CONSTRAINT grocery_lists_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT grocery_lists_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL,
    CONSTRAINT grocery_lists_todo_id_fkey          FOREIGN KEY (todo_id)            REFERENCES public.todos(id)      ON DELETE SET NULL
);

CREATE TABLE public.grocery_items (
    id                    uuid    DEFAULT gen_random_uuid() NOT NULL,
    list_id               uuid    NOT NULL,
    recipe_id             uuid,
    recipe_ingredient_id  uuid,
    name                  text    NOT NULL,
    quantity              numeric,
    unit                  character varying(100),
    category              character varying(200),
    is_checked            boolean DEFAULT false NOT NULL,
    notes                 text,
    created_at            timestamp with time zone DEFAULT now() NOT NULL,
    updated_at            timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT grocery_items_pkey                     PRIMARY KEY (id),
    CONSTRAINT grocery_items_list_id_fkey             FOREIGN KEY (list_id)              REFERENCES public.grocery_lists(id)    ON DELETE CASCADE,
    CONSTRAINT grocery_items_recipe_id_fkey           FOREIGN KEY (recipe_id)            REFERENCES public.recipes(id)          ON DELETE SET NULL,
    CONSTRAINT grocery_items_recipe_ingredient_id_fkey FOREIGN KEY (recipe_ingredient_id) REFERENCES public.recipe_ingredients(id) ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 9. Habits
-- -----------------------------------------------------------------------------

CREATE TABLE public.habits (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    goal_id             uuid,
    name                character varying(500)   NOT NULL,
    description         text,
    frequency           character varying(50)    DEFAULT 'daily' NOT NULL,
    cadence             jsonb,
    status              character varying(50)    DEFAULT 'active' NOT NULL,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT habits_pkey                  PRIMARY KEY (id),
    CONSTRAINT habits_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT habits_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL,
    CONSTRAINT habits_goal_id_fkey          FOREIGN KEY (goal_id)            REFERENCES public.goals(id)      ON DELETE SET NULL
);

CREATE TABLE public.habit_occurrences (
    id             uuid                     DEFAULT gen_random_uuid() NOT NULL,
    habit_id       uuid                     NOT NULL,
    todo_id        uuid,
    scheduled_date date                     NOT NULL,
    status         character varying(50)    DEFAULT 'pending' NOT NULL,
    completed_at   timestamp with time zone,
    notes          text,
    created_at     timestamp with time zone DEFAULT now() NOT NULL,
    updated_at     timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT habit_occurrences_pkey          PRIMARY KEY (id),
    CONSTRAINT habit_occurrences_habit_id_fkey FOREIGN KEY (habit_id) REFERENCES public.habits(id) ON DELETE CASCADE,
    CONSTRAINT habit_occurrences_todo_id_fkey  FOREIGN KEY (todo_id)  REFERENCES public.todos(id)  ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 10. Calendar events
-- -----------------------------------------------------------------------------

CREATE TABLE public.calendar_events (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    ical_uid            text                     NOT NULL,
    title               character varying(500)   NOT NULL,
    description         text,
    location            character varying(500),
    starts_at           timestamp with time zone NOT NULL,
    ends_at             timestamp with time zone,
    all_day             boolean                  DEFAULT false NOT NULL,
    rrule               text,
    exrule              text,
    rdate               text,
    exdate              text,
    status              character varying(20)    DEFAULT 'confirmed' NOT NULL,
    transparency        character varying(20)    DEFAULT 'opaque'   NOT NULL,
    source              character varying(100),
    external_id         text,
    calendar_name       character varying(200),
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT calendar_events_pkey                  PRIMARY KEY (id),
    CONSTRAINT calendar_events_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT calendar_events_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 11. Contacts
-- -----------------------------------------------------------------------------

CREATE TABLE public.contacts (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    vcard_uid           text,
    given_name          character varying(200),
    family_name         character varying(200),
    middle_name         character varying(200),
    prefix              character varying(50),
    suffix              character varying(50),
    display_name        character varying(500),
    organization        character varying(500),
    job_title           character varying(500),
    birthday            date,
    anniversary         date,
    notes               text,
    website             character varying(500),
    source              character varying(100),
    external_id         text,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT contacts_pkey                  PRIMARY KEY (id),
    CONSTRAINT contacts_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT contacts_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL
);

CREATE TABLE public.contact_addresses (
    id          uuid                   DEFAULT gen_random_uuid() NOT NULL,
    contact_id  uuid                   NOT NULL,
    label       character varying(100),
    street      character varying(500),
    city        character varying(200),
    region      character varying(200),
    postal_code character varying(20),
    country     character varying(200),
    CONSTRAINT contact_addresses_pkey           PRIMARY KEY (id),
    CONSTRAINT contact_addresses_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id) ON DELETE CASCADE
);

CREATE TABLE public.contact_emails (
    id         uuid                   DEFAULT gen_random_uuid() NOT NULL,
    contact_id uuid                   NOT NULL,
    email      character varying(500) NOT NULL,
    label      character varying(100),
    is_primary boolean                DEFAULT false NOT NULL,
    CONSTRAINT contact_emails_pkey           PRIMARY KEY (id),
    CONSTRAINT contact_emails_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id) ON DELETE CASCADE
);

CREATE TABLE public.contact_phones (
    id           uuid                  DEFAULT gen_random_uuid() NOT NULL,
    contact_id   uuid                  NOT NULL,
    phone_number character varying(50) NOT NULL,
    label        character varying(100),
    is_primary   boolean               DEFAULT false NOT NULL,
    CONSTRAINT contact_phones_pkey           PRIMARY KEY (id),
    CONSTRAINT contact_phones_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 12. Workouts
-- -----------------------------------------------------------------------------

CREATE TABLE public.workouts (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    name                text,
    workout_date        date                     NOT NULL,
    notes               text,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workouts_pkey                  PRIMARY KEY (id),
    CONSTRAINT workouts_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT workouts_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL
);

CREATE TABLE public.exercise_entries (
    id         uuid                  DEFAULT gen_random_uuid() NOT NULL,
    workout_id uuid                  NOT NULL,
    name       text                  NOT NULL,
    type       public.exercise_type  NOT NULL,
    sort_order integer               DEFAULT 0 NOT NULL,
    metrics    jsonb,
    notes      text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT exercise_entries_pkey            PRIMARY KEY (id),
    CONSTRAINT exercise_entries_workout_id_fkey FOREIGN KEY (workout_id) REFERENCES public.workouts(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 13. Collections (no FK to documents yet — added after documents is created)
-- -----------------------------------------------------------------------------

CREATE TABLE public.collections (
    id                  uuid                       DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                       NOT NULL,
    created_by_user_id  uuid,
    name                text                       NOT NULL,
    icon                text,
    domain              public.collection_domain   NOT NULL,
    default_tags        jsonb,
    default_template_id uuid,                      -- FK to documents added below
    auto_create_rule    jsonb,
    sort_order          integer                    DEFAULT 0 NOT NULL,
    created_at          timestamp with time zone   DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone   DEFAULT now() NOT NULL,
    CONSTRAINT collections_pkey                  PRIMARY KEY (id),
    CONSTRAINT collections_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT collections_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)   ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 14. Documents
-- -----------------------------------------------------------------------------

CREATE TABLE public.documents (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    parent_id           uuid,
    collection_id       uuid,
    title               text                     NOT NULL,
    slug                text                     NOT NULL,
    description         text,
    icon                text,
    kind                public.document_kind     DEFAULT 'page'::public.document_kind NOT NULL,
    source_markdown     text,
    editor_json         jsonb,
    archived_at         timestamp with time zone,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT documents_pkey                       PRIMARY KEY (id),
    CONSTRAINT documents_household_slug_key         UNIQUE (household_id, slug),
    CONSTRAINT documents_household_id_fkey          FOREIGN KEY (household_id)       REFERENCES public.households(id)  ON DELETE CASCADE,
    CONSTRAINT documents_created_by_user_id_fkey    FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)       ON DELETE SET NULL,
    CONSTRAINT documents_parent_id_fkey             FOREIGN KEY (parent_id)          REFERENCES public.documents(id)   ON DELETE SET NULL,
    CONSTRAINT documents_collection_id_fkey         FOREIGN KEY (collection_id)      REFERENCES public.collections(id) ON DELETE SET NULL
);

-- Now add the FK from collections → documents
ALTER TABLE public.collections
    ADD CONSTRAINT collections_default_template_id_fkey
        FOREIGN KEY (default_template_id) REFERENCES public.documents(id) ON DELETE SET NULL;

-- -----------------------------------------------------------------------------
-- 15. Tags + taggings
-- -----------------------------------------------------------------------------

CREATE TABLE public.tags (
    id           uuid                   DEFAULT gen_random_uuid() NOT NULL,
    household_id uuid                   NOT NULL,
    name         character varying(100) NOT NULL,
    color        character varying(20),
    created_at   timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tags_pkey              PRIMARY KEY (id),
    CONSTRAINT tags_household_name_key UNIQUE (household_id, name),
    CONSTRAINT tags_household_id_fkey  FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE
);

CREATE TABLE public.taggings (
    id          uuid                   DEFAULT gen_random_uuid() NOT NULL,
    tag_id      uuid                   NOT NULL,
    entity_type character varying(100) NOT NULL,
    entity_id   uuid                   NOT NULL,
    created_at  timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT taggings_pkey            PRIMARY KEY (id),
    CONSTRAINT taggings_tag_entity_key  UNIQUE (tag_id, entity_type, entity_id),
    CONSTRAINT taggings_tag_id_fkey     FOREIGN KEY (tag_id) REFERENCES public.tags(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 16. Attachments
-- -----------------------------------------------------------------------------

CREATE TABLE public.attachments (
    id                 uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id       uuid                     NOT NULL,
    owner_entity_type  character varying(100)   NOT NULL,
    owner_entity_id    uuid                     NOT NULL,
    file_path          text                     NOT NULL,
    original_filename  character varying(500),
    content_type       character varying(200),
    size_bytes         bigint,
    uploaded_by_user_id uuid,
    created_at         timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT attachments_pkey                     PRIMARY KEY (id),
    CONSTRAINT attachments_household_id_fkey        FOREIGN KEY (household_id)        REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT attachments_uploaded_by_user_id_fkey FOREIGN KEY (uploaded_by_user_id) REFERENCES public.users(id)     ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 17. Notes
-- -----------------------------------------------------------------------------

CREATE TABLE public.notes (
    id                  uuid                     DEFAULT gen_random_uuid() NOT NULL,
    household_id        uuid                     NOT NULL,
    created_by_user_id  uuid,
    collection_id       uuid,
    title               text                     NOT NULL,
    content_md          text,
    content_json        jsonb,
    archived_at         timestamp with time zone,
    created_at          timestamp with time zone DEFAULT now() NOT NULL,
    updated_at          timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT notes_pkey                  PRIMARY KEY (id),
    CONSTRAINT notes_household_id_fkey     FOREIGN KEY (household_id)       REFERENCES public.households(id)  ON DELETE CASCADE,
    CONSTRAINT notes_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id)    ON DELETE SET NULL,
    CONSTRAINT notes_collection_id_fkey    FOREIGN KEY (collection_id)      REFERENCES public.collections(id) ON DELETE SET NULL
);

CREATE TABLE public.note_tags (
    id         uuid                     DEFAULT gen_random_uuid() NOT NULL,
    note_id    uuid                     NOT NULL,
    tag_id     uuid                     NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT note_tags_pkey          PRIMARY KEY (id),
    CONSTRAINT note_tags_note_tag_key  UNIQUE (note_id, tag_id),
    CONSTRAINT note_tags_note_id_fkey  FOREIGN KEY (note_id) REFERENCES public.notes(id) ON DELETE CASCADE,
    CONSTRAINT note_tags_tag_id_fkey   FOREIGN KEY (tag_id)  REFERENCES public.tags(id)  ON DELETE CASCADE
);

CREATE TABLE public.note_backlinks (
    id               uuid DEFAULT gen_random_uuid() NOT NULL,
    source_note_id   uuid NOT NULL,
    target_note_id   uuid NOT NULL,
    alias            text,
    created_at       timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT note_backlinks_pkey      PRIMARY KEY (id),
    CONSTRAINT note_backlinks_pair_key  UNIQUE (source_note_id, target_note_id),
    CONSTRAINT note_backlinks_source_fkey FOREIGN KEY (source_note_id) REFERENCES public.notes(id) ON DELETE CASCADE,
    CONSTRAINT note_backlinks_target_fkey FOREIGN KEY (target_note_id) REFERENCES public.notes(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- 18. AI tables
-- -----------------------------------------------------------------------------

CREATE TABLE public.ai_conversations (
    id              uuid                     DEFAULT gen_random_uuid() NOT NULL,
    user_id         uuid                     NOT NULL,
    household_id    uuid                     NOT NULL,
    title           text,
    created_at      timestamp with time zone DEFAULT now() NOT NULL,
    last_message_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ai_conversations_pkey              PRIMARY KEY (id),
    CONSTRAINT ai_conversations_user_id_fkey      FOREIGN KEY (user_id)      REFERENCES public.users(id)      ON DELETE CASCADE,
    CONSTRAINT ai_conversations_household_id_fkey FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE
);

CREATE TABLE public.ai_messages (
    id              uuid                   DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid                   NOT NULL,
    role            public.ai_message_role NOT NULL,
    content         text                   NOT NULL,
    search_vector   tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at      timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ai_messages_pkey                PRIMARY KEY (id),
    CONSTRAINT ai_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.ai_conversations(id) ON DELETE CASCADE
);

CREATE TABLE public.member_ai_memory (
    user_id                           uuid    NOT NULL,
    memory_text                       text    NOT NULL DEFAULT '',
    last_updated_at                   timestamp with time zone DEFAULT now() NOT NULL,
    conversation_count_at_last_update integer NOT NULL DEFAULT 0,
    CONSTRAINT member_ai_memory_pkey         PRIMARY KEY (user_id),
    CONSTRAINT member_ai_memory_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE
);

CREATE TABLE public.ai_settings (
    user_id           uuid                 NOT NULL,
    provider          public.ai_provider   NOT NULL DEFAULT 'anthropic'::public.ai_provider,
    api_key_encrypted text,
    retention_days    integer              DEFAULT 90,
    CONSTRAINT ai_settings_pkey              PRIMARY KEY (user_id),
    CONSTRAINT ai_settings_user_id_fkey      FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT ai_settings_retention_days_check CHECK (retention_days IS NULL OR retention_days IN (30, 60, 90, 180, 365))
);

CREATE TABLE public.ai_usage (
    id              uuid    DEFAULT gen_random_uuid() NOT NULL,
    user_id         uuid    NOT NULL,
    conversation_id uuid,
    input_tokens    integer DEFAULT 0 NOT NULL,
    output_tokens   integer DEFAULT 0 NOT NULL,
    model           text    NOT NULL,
    turn_kind       text    DEFAULT 'chat' NOT NULL,
    created_at      timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ai_usage_pkey                PRIMARY KEY (id),
    CONSTRAINT ai_usage_user_id_fkey        FOREIGN KEY (user_id)         REFERENCES public.users(id)            ON DELETE CASCADE,
    CONSTRAINT ai_usage_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.ai_conversations(id) ON DELETE SET NULL
);

-- -----------------------------------------------------------------------------
-- 19. Schema migrations tracker
-- -----------------------------------------------------------------------------

CREATE TABLE public.schema_migrations (
    version    text                     NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT schema_migrations_pkey PRIMARY KEY (version)
);

-- -----------------------------------------------------------------------------
-- 20. Indexes
-- -----------------------------------------------------------------------------

-- Identity
CREATE INDEX idx_household_memberships_user_id      ON public.household_memberships USING btree (user_id);
CREATE INDEX idx_household_memberships_household_id ON public.household_memberships USING btree (household_id);
CREATE INDEX idx_refresh_tokens_user_id             ON public.refresh_tokens        USING btree (user_id);
CREATE INDEX idx_refresh_tokens_expires_at          ON public.refresh_tokens        USING btree (expires_at);

-- Audit
CREATE INDEX idx_audit_log_household_id ON public.audit_log USING btree (household_id);
CREATE INDEX idx_audit_log_entity       ON public.audit_log USING btree (entity_type, entity_id);
CREATE INDEX idx_audit_log_actor        ON public.audit_log USING btree (actor_type, actor_id);
CREATE INDEX idx_audit_log_created_at   ON public.audit_log USING btree (created_at DESC);

-- Attachments / tags
CREATE INDEX idx_attachments_household_id ON public.attachments USING btree (household_id);
CREATE INDEX idx_attachments_owner        ON public.attachments USING btree (owner_entity_type, owner_entity_id);
CREATE INDEX idx_tags_household_id        ON public.tags        USING btree (household_id);
CREATE INDEX idx_taggings_entity          ON public.taggings    USING btree (entity_type, entity_id);

-- Domain tables
CREATE INDEX idx_goals_household_id           ON public.goals           USING btree (household_id);
CREATE INDEX idx_todos_household_id           ON public.todos           USING btree (household_id);
CREATE INDEX idx_todos_assigned_to_user_id    ON public.todos           USING btree (assigned_to_user_id);
CREATE INDEX idx_notes_household_id           ON public.notes           USING btree (household_id);
CREATE INDEX idx_calendar_events_household_id ON public.calendar_events USING btree (household_id);
CREATE INDEX idx_contacts_household_id        ON public.contacts        USING btree (household_id);
CREATE INDEX idx_habits_household_id          ON public.habits          USING btree (household_id);
CREATE INDEX idx_recipes_household_id         ON public.recipes         USING btree (household_id);
CREATE INDEX idx_grocery_lists_household_id   ON public.grocery_lists   USING btree (household_id);
CREATE INDEX idx_workouts_household_id        ON public.workouts        USING btree (household_id);
CREATE INDEX idx_collections_household_id     ON public.collections     USING btree (household_id);
CREATE INDEX idx_documents_household_id       ON public.documents       USING btree (household_id);

-- AI
CREATE INDEX idx_ai_conversations_user_id      ON public.ai_conversations USING btree (user_id, last_message_at DESC);
CREATE INDEX idx_ai_conversations_household_id ON public.ai_conversations USING btree (household_id);
CREATE INDEX idx_ai_messages_conversation_id   ON public.ai_messages      USING btree (conversation_id, created_at ASC);
CREATE INDEX idx_ai_messages_search_vector     ON public.ai_messages      USING gin  (search_vector);
CREATE INDEX ix_ai_usage_user_created          ON public.ai_usage         USING btree (user_id, created_at);

-- -----------------------------------------------------------------------------
-- 21. updated_at triggers
-- -----------------------------------------------------------------------------

CREATE TRIGGER households_updated_at       BEFORE UPDATE ON public.households       FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER users_updated_at            BEFORE UPDATE ON public.users            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER goals_updated_at            BEFORE UPDATE ON public.goals            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER todos_updated_at            BEFORE UPDATE ON public.todos            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER notes_updated_at            BEFORE UPDATE ON public.notes            FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER calendar_events_updated_at  BEFORE UPDATE ON public.calendar_events  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER contacts_updated_at         BEFORE UPDATE ON public.contacts         FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER habits_updated_at           BEFORE UPDATE ON public.habits           FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER habit_occurrences_updated_at BEFORE UPDATE ON public.habit_occurrences FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER recipes_updated_at          BEFORE UPDATE ON public.recipes          FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER grocery_lists_updated_at    BEFORE UPDATE ON public.grocery_lists    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER grocery_items_updated_at    BEFORE UPDATE ON public.grocery_items    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER workouts_updated_at         BEFORE UPDATE ON public.workouts         FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER exercise_entries_updated_at BEFORE UPDATE ON public.exercise_entries FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER collections_updated_at      BEFORE UPDATE ON public.collections      FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER documents_updated_at        BEFORE UPDATE ON public.documents        FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 22. Bootstrap: default household + owner account
-- -----------------------------------------------------------------------------

DO $bootstrap$
DECLARE
    hh_id   uuid;
    user_id uuid;
BEGIN
    INSERT INTO public.households (name)
        VALUES ('Default Household')
        RETURNING id INTO hh_id;

    -- Sentinel password_hash '!' cannot match any argon2 verification.
    -- The API's first run detects this and prompts for an initial password.
    INSERT INTO public.users (email, password_hash, display_name, is_active)
        VALUES ('brandon@life-dashboard.local', '!', 'Brandon', true)
        RETURNING id INTO user_id;

    INSERT INTO public.household_memberships (household_id, user_id, role)
        VALUES (hh_id, user_id, 'owner');
END
$bootstrap$;

-- -----------------------------------------------------------------------------
-- 23. Mark all migrations as applied
-- -----------------------------------------------------------------------------

INSERT INTO public.schema_migrations (version) VALUES
    ('0001_multi_user_audit_tags_attachments'),
    ('0002_document_icon'),
    ('0003_ai_layer'),
    ('0004_recipe_cover_image'),
    ('0005_todos_assigned_to');

COMMIT;

-- =============================================================================
-- End migration 0000
-- =============================================================================
