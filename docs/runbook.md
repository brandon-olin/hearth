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

The migration file contains its own `BEGIN;` / `COMMIT;`. Wrapping it
in an outer transaction and expecting `ROLLBACK` to undo it does not
work — PostgreSQL ignores the inner `BEGIN` as a no-op but honours the
inner `COMMIT`, so the outer `ROLLBACK` arrives after the transaction
has already been committed.

The practical approach: trust the migration's own atomic wrapper plus
the backup from step 1. If the migration fails mid-way, Postgres rolls
back automatically because everything is inside `BEGIN...COMMIT`. If
it applies but the verify queries (step 5) show something wrong, the
down migration and backup restore are the recovery path.

Before applying, do a quick syntax check to catch typos without touching
the database:

```bash
# Syntax-only check — parses the SQL but executes nothing
docker exec -i postgres-1 psql -U brandon -d life_dashboard \
    --dry-run \
    -f /tmp/0001_up.sql 2>&1 | head -20
```

Note: `--dry-run` was added in psql 16. If your `postgres-1` image is
older than 16, skip this step and proceed directly to step 4.

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

## Phase 1 — Deploy the API container to the NAS

All commands run on the NAS over SSH unless noted. All `docker` and
`docker compose` commands require `sudo` on Synology.

### Prerequisites

- Phase 0 migration already applied (see above).
- Tailscale installed on the NAS and the machine is authenticated.
- The `life-dashboard/` repo directory is present on the NAS (copy via
  `scp -O -r` from the Mac — Synology SSH does not expose the SFTP
  subsystem, so plain `scp` fails).

### 1. Copy the repo to the NAS

From the Mac:

```bash
scp -O -r ~/Code/Personal/life-dashboard brandon@192.168.68.58:/volume1/docker/
```

### 2. Connect postgres-1 to the life-dashboard network (one time only)

The compose file creates a `life-dashboard` Docker network. `postgres-1`
was created outside compose, so it needs to join manually. This command
is idempotent — safe to re-run if you're unsure.

```bash
sudo docker network create life-dashboard 2>/dev/null || true
sudo docker network connect life-dashboard postgres-1
```

Verify connectivity after the API is up:

```bash
sudo docker exec life-dashboard-api-1 \
    python3 -c "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://brandon:PASSWORD@postgres-1:5432/life_dashboard'))"
```

### 3. Obtain a Tailscale TLS certificate

```bash
sudo tailscale cert YOUR_NAS.tailnet-name.ts.net
```

The cert and key land in `/var/packages/Tailscale/var/certs/`. Verify:

```bash
ls -la /var/packages/Tailscale/var/certs/
```

### 4. Create the environment file

```bash
cd /volume1/docker/life-dashboard/infra
cp .env.example .env
# Edit .env — fill in DB_PASSWORD, JWT_SECRET_KEY, BOOTSTRAP_PASSWORD,
# and replace the placeholder Tailscale hostname in ALLOWED_ORIGINS.
vi .env
```

### 5. Update the Caddyfile

Replace `YOUR_NAS.tailnet-name.ts.net` with your actual Tailscale hostname
in `infra/caddy/Caddyfile`.

### 6. Run Alembic migrations

Alembic migrations must be applied before starting the API for the first
time, and after any schema migration is added.

```bash
cd /volume1/docker/life-dashboard/infra
sudo docker compose run --rm api \
    alembic -c /app/alembic.ini upgrade head
```

The `--rm` flag removes the ephemeral container after the command exits.

### 7. Start the services

```bash
cd /volume1/docker/life-dashboard/infra
sudo docker compose up -d
```

### 8. Verify

```bash
# Container health
sudo docker compose ps

# API liveness
curl -s http://localhost:8000/health | python3 -m json.tool

# Logs (follow)
sudo docker compose logs -f api
```

Expected health response: `{"status":"ok","database":"reachable"}`.

The first startup will trigger the bootstrap flow: the backend detects
the sentinel `!` password hash, hashes `BOOTSTRAP_PASSWORD` with argon2,
writes it to the DB, and logs `Bootstrap complete`. After that you can
clear `BOOTSTRAP_PASSWORD` from `.env` and run `docker compose up -d`
again (no restart required — the env var is only read at startup).

---

## Ongoing operations

### Update the API after a code change

From the Mac, push changes to the NAS, then rebuild and restart:

```bash
# On the Mac — copy updated source
scp -O -r ~/Code/Personal/life-dashboard brandon@192.168.68.58:/volume1/docker/

# On the NAS
cd /volume1/docker/life-dashboard/infra
sudo docker compose build api
sudo docker compose run --rm api alembic -c /app/alembic.ini upgrade head
sudo docker compose up -d api
```

### View logs

```bash
sudo docker compose logs -f api       # follow API logs
sudo docker compose logs --tail=100 caddy  # last 100 Caddy lines
```

### Restart a service

```bash
sudo docker compose restart api
```

### Refresh the Tailscale certificate (every ~90 days)

```bash
sudo tailscale cert YOUR_NAS.tailnet-name.ts.net
sudo docker compose restart caddy
```

### Back up the database

```bash
sudo docker exec postgres-1 pg_dump -U brandon -Fc life_dashboard \
    > "life_dashboard_$(date +%Y%m%d_%H%M%S).dump"
```

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
