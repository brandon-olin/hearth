# CLAUDE.md — infra/

Docker Compose deployment for Life Dashboard. See the root `CLAUDE.md` for product vision.

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
