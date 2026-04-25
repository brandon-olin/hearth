-- =============================================================================
-- Migration 0001 — Multi-user households, audit log, tags, attachments
-- =============================================================================
-- This is the Phase-0 migration. It does NOT remove or alter existing data
-- columns; it ONLY adds new tables, new columns, and backfills ownership
-- for existing rows to a default household + default user.
--
-- Safe to run on a populated database. Executed as a single transaction —
-- any failure rolls the whole thing back.
--
-- After this runs, the default user will have password_hash = '!' which
-- cannot be matched by argon2 verification, effectively meaning "account
-- exists but cannot log in until a password is set." The backend's first
-- run should detect this and prompt for an initial password setup.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. New enum types
-- -----------------------------------------------------------------------------

CREATE TYPE public.actor_type AS ENUM ('user', 'agent', 'system');
ALTER TYPE public.actor_type OWNER TO brandon;

CREATE TYPE public.membership_role AS ENUM ('owner', 'admin', 'member', 'viewer', 'agent');
ALTER TYPE public.membership_role OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 2. Core identity tables: households, users, memberships, refresh_tokens
-- -----------------------------------------------------------------------------

CREATE TABLE public.households (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT households_pkey PRIMARY KEY (id)
);
ALTER TABLE public.households OWNER TO brandon;

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(320) NOT NULL,
    password_hash text NOT NULL,
    display_name character varying(200),
    is_active boolean DEFAULT true NOT NULL,
    is_agent boolean DEFAULT false NOT NULL,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT users_pkey PRIMARY KEY (id),
    CONSTRAINT users_email_key UNIQUE (email)
);
ALTER TABLE public.users OWNER TO brandon;

CREATE TABLE public.household_memberships (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    household_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role public.membership_role DEFAULT 'member'::public.membership_role NOT NULL,
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT household_memberships_pkey PRIMARY KEY (id),
    CONSTRAINT household_memberships_household_user_key UNIQUE (household_id, user_id),
    CONSTRAINT household_memberships_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT household_memberships_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE
);
ALTER TABLE public.household_memberships OWNER TO brandon;

CREATE TABLE public.refresh_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash text NOT NULL,
    user_agent text,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id),
    CONSTRAINT refresh_tokens_token_hash_key UNIQUE (token_hash),
    CONSTRAINT refresh_tokens_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE
);
ALTER TABLE public.refresh_tokens OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 3. Audit log — every agent/user write operation gets a row here
-- -----------------------------------------------------------------------------

CREATE TABLE public.audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    household_id uuid,
    actor_type public.actor_type NOT NULL,
    actor_id uuid,
    actor_label character varying(200),
    entity_type character varying(100) NOT NULL,
    entity_id uuid,
    action character varying(50) NOT NULL,
    diff jsonb,
    metadata jsonb,
    approved_by_user_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT audit_log_pkey PRIMARY KEY (id),
    CONSTRAINT audit_log_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE SET NULL,
    CONSTRAINT audit_log_approved_by_user_id_fkey
        FOREIGN KEY (approved_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL
);
ALTER TABLE public.audit_log OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 4. Attachments — files associated with any entity (recipes, notes, etc.)
-- -----------------------------------------------------------------------------

CREATE TABLE public.attachments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    household_id uuid NOT NULL,
    owner_entity_type character varying(100) NOT NULL,
    owner_entity_id uuid NOT NULL,
    file_path text NOT NULL,
    original_filename character varying(500),
    content_type character varying(200),
    size_bytes bigint,
    uploaded_by_user_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT attachments_pkey PRIMARY KEY (id),
    CONSTRAINT attachments_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    CONSTRAINT attachments_uploaded_by_user_id_fkey
        FOREIGN KEY (uploaded_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL
);
ALTER TABLE public.attachments OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 5. Tags + taggings (cross-entity tagging, replaces text[] tags on notes/recipes
-- gradually — old tag columns remain in place for now for backward compat)
-- -----------------------------------------------------------------------------

CREATE TABLE public.tags (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    household_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(20),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tags_pkey PRIMARY KEY (id),
    CONSTRAINT tags_household_name_key UNIQUE (household_id, name),
    CONSTRAINT tags_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE
);
ALTER TABLE public.tags OWNER TO brandon;

CREATE TABLE public.taggings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tag_id uuid NOT NULL,
    entity_type character varying(100) NOT NULL,
    entity_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT taggings_pkey PRIMARY KEY (id),
    CONSTRAINT taggings_tag_entity_key UNIQUE (tag_id, entity_type, entity_id),
    CONSTRAINT taggings_tag_id_fkey
        FOREIGN KEY (tag_id) REFERENCES public.tags(id) ON DELETE CASCADE
);
ALTER TABLE public.taggings OWNER TO brandon;

-- -----------------------------------------------------------------------------
-- 6. Indexes for new tables
-- -----------------------------------------------------------------------------

CREATE INDEX idx_household_memberships_user_id ON public.household_memberships USING btree (user_id);
CREATE INDEX idx_household_memberships_household_id ON public.household_memberships USING btree (household_id);

CREATE INDEX idx_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);
CREATE INDEX idx_refresh_tokens_expires_at ON public.refresh_tokens USING btree (expires_at);

CREATE INDEX idx_audit_log_household_id ON public.audit_log USING btree (household_id);
CREATE INDEX idx_audit_log_entity ON public.audit_log USING btree (entity_type, entity_id);
CREATE INDEX idx_audit_log_actor ON public.audit_log USING btree (actor_type, actor_id);
CREATE INDEX idx_audit_log_created_at ON public.audit_log USING btree (created_at DESC);

CREATE INDEX idx_attachments_household_id ON public.attachments USING btree (household_id);
CREATE INDEX idx_attachments_owner ON public.attachments USING btree (owner_entity_type, owner_entity_id);

CREATE INDEX idx_tags_household_id ON public.tags USING btree (household_id);
CREATE INDEX idx_taggings_entity ON public.taggings USING btree (entity_type, entity_id);

-- -----------------------------------------------------------------------------
-- 7. updated_at triggers on new + existing mutable tables
-- The update_updated_at() function already exists from the initial schema.
-- -----------------------------------------------------------------------------

CREATE TRIGGER households_updated_at BEFORE UPDATE ON public.households
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER users_updated_at BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Extend the trigger to existing mutable tables that were missing it
CREATE TRIGGER notes_updated_at BEFORE UPDATE ON public.notes
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER calendar_events_updated_at BEFORE UPDATE ON public.calendar_events
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER contacts_updated_at BEFORE UPDATE ON public.contacts
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER habits_updated_at BEFORE UPDATE ON public.habits
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER habit_occurrences_updated_at BEFORE UPDATE ON public.habit_occurrences
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER recipes_updated_at BEFORE UPDATE ON public.recipes
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER grocery_lists_updated_at BEFORE UPDATE ON public.grocery_lists
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER grocery_items_updated_at BEFORE UPDATE ON public.grocery_items
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- -----------------------------------------------------------------------------
-- 8. Retrofit existing root entities with household_id + created_by_user_id
-- Root entities are those with independent lifecycles. Child tables
-- (contact_addresses, grocery_items, recipe_ingredients, recipe_steps,
-- habit_occurrences) inherit ownership via their parent's FK and do not
-- need their own household_id.
-- -----------------------------------------------------------------------------

ALTER TABLE public.goals           ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.todos           ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.notes           ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.calendar_events ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.contacts        ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.habits          ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.recipes         ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;
ALTER TABLE public.grocery_lists   ADD COLUMN household_id uuid, ADD COLUMN created_by_user_id uuid;

-- -----------------------------------------------------------------------------
-- 9. Backfill: create default household + default user, link them, and
-- assign all existing rows to that household.
-- -----------------------------------------------------------------------------

DO $migration$
DECLARE
    default_household_id uuid;
    default_user_id uuid;
BEGIN
    INSERT INTO public.households (name)
        VALUES ('Default Household')
        RETURNING id INTO default_household_id;

    -- Sentinel password_hash '!' cannot match any argon2 verification,
    -- so the account exists but cannot log in until a real password is set.
    INSERT INTO public.users (email, password_hash, display_name, is_active)
        VALUES ('brandon@life-dashboard.local', '!', 'Brandon', true)
        RETURNING id INTO default_user_id;

    INSERT INTO public.household_memberships (household_id, user_id, role)
        VALUES (default_household_id, default_user_id, 'owner');

    UPDATE public.goals           SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.todos           SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.notes           SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.calendar_events SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.contacts        SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.habits          SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.recipes         SET household_id = default_household_id, created_by_user_id = default_user_id;
    UPDATE public.grocery_lists   SET household_id = default_household_id, created_by_user_id = default_user_id;
END
$migration$;

-- -----------------------------------------------------------------------------
-- 10. Lock in NOT NULL on household_id and add FK constraints for all retrofitted tables
-- -----------------------------------------------------------------------------

ALTER TABLE public.goals
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT goals_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT goals_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.todos
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT todos_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT todos_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.notes
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT notes_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT notes_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.calendar_events
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT calendar_events_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT calendar_events_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.contacts
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT contacts_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT contacts_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.habits
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT habits_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT habits_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.recipes
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT recipes_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT recipes_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.grocery_lists
    ALTER COLUMN household_id SET NOT NULL,
    ADD CONSTRAINT grocery_lists_household_id_fkey
        FOREIGN KEY (household_id) REFERENCES public.households(id) ON DELETE CASCADE,
    ADD CONSTRAINT grocery_lists_created_by_user_id_fkey
        FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

-- -----------------------------------------------------------------------------
-- 11. Indexes on household_id for every retrofitted table
-- -----------------------------------------------------------------------------

CREATE INDEX idx_goals_household_id           ON public.goals           USING btree (household_id);
CREATE INDEX idx_todos_household_id           ON public.todos           USING btree (household_id);
CREATE INDEX idx_notes_household_id           ON public.notes           USING btree (household_id);
CREATE INDEX idx_calendar_events_household_id ON public.calendar_events USING btree (household_id);
CREATE INDEX idx_contacts_household_id        ON public.contacts        USING btree (household_id);
CREATE INDEX idx_habits_household_id          ON public.habits          USING btree (household_id);
CREATE INDEX idx_recipes_household_id         ON public.recipes         USING btree (household_id);
CREATE INDEX idx_grocery_lists_household_id   ON public.grocery_lists   USING btree (household_id);

-- -----------------------------------------------------------------------------
-- 12. Schema migrations tracking table (so future migrations know what's applied)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version text NOT NULL PRIMARY KEY,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE public.schema_migrations OWNER TO brandon;

INSERT INTO public.schema_migrations (version)
    VALUES ('0001_multi_user_audit_tags_attachments');

COMMIT;

-- =============================================================================
-- End migration 0001
-- =============================================================================
