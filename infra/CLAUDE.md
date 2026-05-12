# CLAUDE.md — infra/

Two deployment paths live here: Docker Compose (existing NAS install) and the local install path (M1 milestone). See the root `CLAUDE.md` for product vision.

---

## Local install (M1 — macOS / Linux, no Docker)

### First-time setup

```bash
# 1. Copy and fill in the env file
cp infra/local.env.example infra/local.env
$EDITOR infra/local.env          # set JWT_SECRET_KEY at minimum

# 2. Install Python deps and Node deps (if not already done)
cd api && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cd web && npm install

# 3. Run database migrations
make migrate

# 4. Register background services, build web app, start everything
make service-install
```

After `service-install`, the API and web server run silently in the background and restart automatically at login. No terminal windows needed.

### Daily management

```bash
make service-status     # check if running
make service-logs       # tail live logs (Ctrl-C to exit)
make service-stop       # stop both processes
make service-start      # start both processes
make service-restart    # restart both processes
make service-uninstall  # remove the background services (app files untouched)
```

### How it works

- **macOS**: `service.sh install` generates `~/Library/LaunchAgents/com.lifedashboard.{api,web}.plist` from templates in `infra/launchd/`. launchd loads them at login and keeps them alive if they crash.
- **Linux**: generates `~/.config/systemd/user/life-dashboard-{api,web}.service` from templates in `infra/systemd/`. No root required — these are user-level systemd units.
- Both platforms source `infra/local.env` at startup for secrets and config.
- Logs: `~/Library/Logs/LifeDashboard/` (macOS) or `journalctl --user` (Linux).

### Generated files (gitignored)

These are produced by `service.sh install` and should never be committed:
- `infra/scripts/run-api.sh` — wrapper that sources `local.env` + starts uvicorn
- `infra/scripts/run-web.sh` — wrapper that sources `local.env` + starts Next.js
- `~/Library/LaunchAgents/com.lifedashboard.*.plist` (macOS)
- `~/.config/systemd/user/life-dashboard-*.service` (Linux)

---

---

## What's here

```
infra/
  docker-compose.yml    Defines api, web, and postgres services
  caddy/                Caddy reverse proxy config (TLS termination, routing)
  logseq/               Legacy — ignore; historical personal config
```

---

## Common commands

All commands run from the `infra/` directory on the NAS:

```bash
# Rebuild and restart everything
sudo docker compose build && sudo docker compose up -d

# Rebuild only the API (Python changes)
sudo docker compose build api && sudo docker compose up -d

# Rebuild only the web frontend (Next.js changes)
sudo docker compose build web && sudo docker compose up -d

# View logs
sudo docker compose logs -f api
sudo docker compose logs -f web

# Restart without rebuilding
sudo docker compose up -d
```

The NAS path is `/volume1/docker/life-dashboard/infra`.

---

## Services

- **api** — FastAPI app, listens on port 8000 internally; not directly exposed
- **web** — Next.js app, listens on port 3000 internally; proxies `/api/*` to the api service
- **postgres** — Postgres 15; data volume persisted on the NAS; port 5433 exposed locally for dev access
- **caddy** — Reverse proxy; handles TLS via Let's Encrypt; routes external traffic to the web service

---

## Environment

Each service reads from `.env` files. The `API_URL` in the web service's env tells Next.js where to proxy backend requests. Inside Docker Compose, services communicate via service names (e.g. `http://api:8000`).

---

## Migrations

Migrations must be applied manually after schema changes. Connect to the running API container and run Alembic:

```bash
sudo docker compose exec api alembic -c /app/migrations/alembic.ini upgrade head
```

Or run from your local machine if you have direct Postgres access (NAS port 5433).

---

## Notes

- The NAS (Synology) has limited CPU — expect 2–3 minute build times for the web image.
- Rebuilding `api` is fast (~30s) since it has no compile step.
- Caddy handles TLS automatically via ACME/Let's Encrypt — no manual cert management.
- Tailscale is installed on the NAS for secure remote access without port-forwarding.
