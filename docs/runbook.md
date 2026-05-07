# Runbook — life-dashboard (Self-Hosted)

Operational reference for deploying and maintaining life-dashboard on self-hosted infrastructure.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Docker + Docker Compose | Compose v2 (`docker compose`) recommended |
| Postgres 15+ | Can be a container or a managed instance |
| Python 3.12 | Only needed if running the API outside Docker |
| Node 20+ | Only needed if building the frontend outside Docker |

---

## Repository layout

```
life-dashboard/
├── api/                # FastAPI backend
├── web/                # Next.js frontend
├── agent/              # AI/automation tooling (planned)
├── infra/              # Docker Compose and Caddy config
│   ├── docker-compose.yml
│   ├── .env.example
│   └── caddy/
│       └── Caddyfile
└── migrations/         # Alembic migration files
```

---

## First-time setup

### 1. Configure environment

```bash
cp infra/.env.example infra/.env
```

Edit `infra/.env` with your values:

```
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/life_dashboard
BOOTSTRAP_PASSWORD=choose-a-strong-password
SECRET_KEY=generate-with-openssl-rand-hex-32
```

Generate a secret key:

```bash
openssl rand -hex 32
```

### 2. Start services

```bash
cd infra
docker compose up -d
```

### 3. Run migrations

```bash
docker compose exec api alembic upgrade head
```

The first startup seeds a default user account. On first login, use the password from `BOOTSTRAP_PASSWORD` in your `.env`.

### 4. Verify

```bash
# API health check
curl http://localhost:8000/health

# View logs
docker compose logs -f api
docker compose logs -f web
```

---

## Migrations

Alembic manages all schema changes. Never modify the database schema by hand.

```bash
# Apply all pending migrations
docker compose exec api alembic upgrade head

# Check current migration state
docker compose exec api alembic current

# View migration history
docker compose exec api alembic history

# Roll back one migration
docker compose exec api alembic downgrade -1
```

To create a new migration after changing an ORM model:

```bash
docker compose exec api alembic revision --autogenerate -m "describe the change"
```

Review auto-generated migrations before applying — autogenerate does not detect all changes (e.g., custom indexes, trigger changes, enum renames).

---

## Updating the app

```bash
# Pull new code
git pull

# Rebuild and restart containers
cd infra
docker compose build
docker compose up -d

# Apply any new migrations
docker compose exec api alembic upgrade head
```

To rebuild a single service (faster when only one layer changed):

```bash
docker compose build api && docker compose up -d   # Python/API changes only
docker compose build web && docker compose up -d   # Next.js changes only
```

---

## Backup

### Database

```bash
# Dump the database
docker compose exec postgres pg_dump -U USER life_dashboard > backup-$(date +%Y%m%d).sql

# Or if Postgres is running outside Docker
pg_dump -h HOST -U USER life_dashboard > backup-$(date +%Y%m%d).sql
```

### Restore

```bash
psql -h HOST -U USER life_dashboard < backup-YYYYMMDD.sql
```

---

## Logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f api
docker compose logs -f web
```

---

## TLS with Caddy

The `infra/caddy/Caddyfile` is a template for TLS termination via Caddy. Replace `YOUR_HOST` with your actual hostname (a public domain or Tailscale MagicDNS name).

```bash
# Start Caddy alongside the app
docker compose --profile caddy up -d
```

Caddy handles certificate acquisition automatically via ACME/Let's Encrypt for public domains. For private network access, use a Tailscale MagicDNS hostname.

---

## Auth notes

- Passwords are hashed with argon2.
- Access tokens: 15-minute lifetime, stored in memory on the client.
- Refresh tokens: long-lived, stored in httpOnly cookies with rotation on every use.
- `BOOTSTRAP_PASSWORD` is used only on first startup to set the default user's password. Once written, the env variable is no longer read — clear it from `.env` after first login.

---

## Troubleshooting

**API fails to start — database connection error**
- Confirm `DATABASE_URL` in `.env` is correct.
- Confirm the Postgres container or server is running and reachable from the API container.

**Migrations fail — relation already exists**
- Check the current migration state: `alembic current`
- If the schema is ahead of what Alembic tracks, stamp the current head: `alembic stamp head`

**Frontend returns 401 on all requests**
- The access token may have expired and the refresh endpoint is failing.
- Check `docker compose logs api` for auth errors.
- Clearing browser cookies and logging in again typically resolves this.

**Container restarts in a loop**
- Check `docker compose logs api` for the traceback.
- Common causes: bad env variable, failed migration, database unreachable.

---

## NAS-specific notes (Synology)

> Personal reference for the Synology NAS deployment.

| Item | Value |
|---|---|
| Postgres port | 5433 external / 5432 internal |
| App path | `/volume1/docker/life-dashboard/` |
| Infra path | `/volume1/docker/life-dashboard/infra/` |

**All Docker commands require `sudo` on Synology.**

```bash
cd /volume1/docker/life-dashboard/infra
sudo docker compose build && sudo docker compose up -d
```

**Postgres shell access:**

```bash
sudo docker compose exec postgres psql -U USERNAME -d life_dashboard
```

**Tailscale** is installed for secure remote access without port-forwarding. Caddy uses the Tailscale MagicDNS hostname for TLS.

**SCP to NAS** requires the `-O` flag on newer SSH clients:

```bash
scp -O file.txt USER@NAS_IP:/volume1/docker/life-dashboard/
```
