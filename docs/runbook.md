# life_dashboard — Runbook

Operational procedures for deploying, upgrading, and troubleshooting the
life_dashboard system. Written for Brandon's NAS (Synology + Docker +
existing `postgres-1` container).

---

## Phase 0 — Apply migration 0001

This is the first migration. It adds multi-user support, an audit log,
tags, and attachments, and retrofits ownership columns on all existing
root entities. It's wrapped in a single transaction — if anything fails,
the whole thing rolls back.

### 1. Back up the database first

Non-negotiable. Run this on the NAS, not inside the container:

```bash
docker exec postgres-1 pg_dump -U brandon -Fc life_dashboard \
    > "life_dashboard_$(date +%Y%m%d_%H%M%S).dump"
```

The `-Fc` flag produces a custom-format dump that `pg_restore` can
selectively replay later.

### 2. Copy the migration into the container

From wherever you have the `life-dashboard/` folder on the NAS:

```bash
docker cp life-dashboard/migrations/0001_multi_user_audit_tags_attachments.up.sql \
    postgres-1:/tmp/0001_up.sql
```

### 3. Dry-run the migration

Postgres doesn't have a true "dry run," but because the migration is a
single `BEGIN ... COMMIT` block, we can replace `COMMIT` with `ROLLBACK`
for a simulation. The easiest way is to wrap the whole file in a
psql-level transaction with `--single-transaction` and then abort:

```bash
# Simulated apply — fails intentionally at the end so nothing persists
docker exec -i postgres-1 psql -U brandon -d life_dashboard \
    -v ON_ERROR_STOP=1 \
    --single-transaction \
    -c "BEGIN;" \
    -f /tmp/0001_up.sql \
    -c "ROLLBACK;"
```

If that completes without errors, the migration is good to apply for
real. If it fails, read the error, fix, and re-run the dry-run.

### 4. Apply the migration

```bash
docker exec -i postgres-1 psql -U brandon -d life_dashboard \
    -v ON_ERROR_STOP=1 \
    -f /tmp/0001_up.sql
```

Expected output ends with `COMMIT`. If you see `ROLLBACK`, the
migration aborted and the database is unchanged — read the error above
the rollback to understand why.

### 5. Verify

```bash
docker exec -i postgres-1 psql -U brandon -d life_dashboard <<'SQL'
-- New tables should exist
\dt public.households
\dt public.users
\dt public.household_memberships
\dt public.refresh_tokens
\dt public.audit_log
\dt public.attachments
\dt public.tags
\dt public.taggings
\dt public.schema_migrations

-- Existing tables should have new columns
\d public.todos
\d public.goals

-- Default household + user should exist
SELECT id, name FROM public.households;
SELECT id, email, display_name FROM public.users;
SELECT h.name, u.email, m.role
    FROM public.household_memberships m
    JOIN public.households h ON h.id = m.household_id
    JOIN public.users u ON u.id = m.user_id;

-- Existing rows should all belong to the default household
SELECT
    (SELECT COUNT(*) FROM public.goals WHERE household_id IS NULL) AS orphan_goals,
    (SELECT COUNT(*) FROM public.todos WHERE household_id IS NULL) AS orphan_todos,
    (SELECT COUNT(*) FROM public.notes WHERE household_id IS NULL) AS orphan_notes;

-- Migration recorded
SELECT * FROM public.schema_migrations ORDER BY applied_at;
SQL
```

Every `orphan_*` count should be `0`.

### 6. Rollback (only if needed)

If something is wrong after applying, roll back with the down migration:

```bash
docker cp life-dashboard/migrations/0001_multi_user_audit_tags_attachments.down.sql \
    postgres-1:/tmp/0001_down.sql
docker exec -i postgres-1 psql -U brandon -d life_dashboard \
    -v ON_ERROR_STOP=1 \
    -f /tmp/0001_down.sql
```

The down migration drops the new tables (destroying any data in them)
and removes the new columns from existing tables. The original rows
in `goals`, `todos`, etc. are preserved exactly as they were.

If the rollback itself fails for any reason, restore from the backup
taken in step 1:

```bash
docker exec -i postgres-1 dropdb -U brandon life_dashboard
docker exec -i postgres-1 createdb -U brandon life_dashboard
docker exec -i postgres-1 pg_restore -U brandon -d life_dashboard \
    < life_dashboard_YYYYMMDD_HHMMSS.dump
```

---

## Post-migration tasks

After the migration applies successfully, the `brandon@life-dashboard.local`
user has a sentinel password_hash of `!` that cannot be matched by
argon2 verification. Setting the real password will be handled by the
Phase-1 backend's first-run flow — do nothing manual here.

---

## Troubleshooting

**"permission denied for function gen_random_uuid()"** — `gen_random_uuid()`
lives in the `pgcrypto` extension in older Postgres; in 16.x it's in core.
Your baseline schema already uses it in every `DEFAULT`, so if the baseline
applied cleanly this won't affect the migration.

**"type already exists"** — you probably ran the migration twice. Check
`SELECT * FROM schema_migrations;` — if `0001_...` is already there,
the migration is applied. Don't re-run it.

**"could not create unique index"** — indicates duplicate data that
violates a new unique constraint. The migration's unique constraints
are all on newly-created tables with no data, so this shouldn't happen
on the Phase-0 migration. If it does, it means the migration partially
applied despite the `BEGIN` — investigate carefully before doing
anything else and consider restoring from backup.
