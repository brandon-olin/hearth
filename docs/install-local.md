# Local Install Guide

Life Dashboard runs directly on your machine — no Docker, no cloud account required. The install script sets up a Python virtual environment, installs Node dependencies, and registers background services that start automatically at login.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| macOS or Linux | — | Windows is not yet supported |
| Python | 3.12 or newer | `brew install python@3.12` · `sudo apt install python3.12` |
| Git | any recent | usually pre-installed |
| Node.js | 20 or newer | optional — downloaded automatically if missing |
| PostgreSQL | 14 or newer | optional — downloaded automatically if missing |

---

## Install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/brandon-olin/life-dashboard/main/install.sh | bash
```

This will:

1. Clone the repo to `~/life-dashboard` (or update it if already there)
2. Create a Python virtual environment and install dependencies
3. Install Node dependencies
4. Generate `infra/local.env` with a random JWT secret
5. Start Postgres (system or bundled), run migrations, build the web app
6. Register `com.lifedashboard.api` and `com.lifedashboard.web` as background services that restart at login

When it finishes, open **http://localhost:3000** and complete the setup wizard.

---

## Manual install (if you prefer)

```bash
# 1. Clone
git clone https://github.com/brandon-olin/life-dashboard.git
cd life-dashboard

# 2. Python environment
cd api && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]' && cd ..

# 3. Node dependencies
cd web && npm install && cd ..

# 4. Environment file
cp infra/local.env.example infra/local.env
# Edit infra/local.env — set JWT_SECRET_KEY at minimum:
#   python3 -c "import secrets; print(secrets.token_hex(32))"

# 5. Install and start services
make service-install
```

---

## Daily management

All commands run from the repo root:

```bash
make service-status     # are the services running?
make service-logs       # tail live logs (Ctrl-C to exit)
make service-restart    # restart after a code change
make service-stop       # stop everything
make service-start      # start again
make service-uninstall  # remove background services (data is untouched)
```

---

## How it works

**macOS** — the installer generates two LaunchAgent plist files in `~/Library/LaunchAgents/`:

```
com.lifedashboard.api.plist   FastAPI + uvicorn, port 8000
com.lifedashboard.web.plist   Next.js, port 3000
```

launchd loads them at login and restarts them automatically if they crash. No terminal window needed.

**Linux** — the installer generates two systemd user units in `~/.config/systemd/user/`:

```
life-dashboard-api.service
life-dashboard-web.service
```

These are user-level units (no root required). They start at login via `systemctl --user`.

**Postgres** — the script checks for a system Postgres (≥ 14) first. If none is found, it downloads a bundled EDB Postgres 16 binary (~90 MB) into `infra/runtime/postgres/` and registers it as a third background service. Either way, the database lives at:

- macOS: `~/Library/Application Support/LifeDashboard/postgres`
- Linux: `~/.local/share/life-dashboard/postgres`

---

## Logs

| Platform | Location |
|---|---|
| macOS | `~/Library/Logs/LifeDashboard/api.log`, `web.log` |
| Linux | `journalctl --user -u life-dashboard-api` |

```bash
# Shortcut for both services at once:
make service-logs
```

---

## Updating

```bash
git pull
make service-install   # rebuilds the web app and restarts services
```

If there are database migrations in the update, they run automatically as part of `service-install`.

---

## Uninstall

```bash
# Remove services only (app files and database are untouched):
make service-uninstall

# Full removal including app files and database:
make service-uninstall
rm -rf ~/life-dashboard
rm -rf ~/Library/Application\ Support/LifeDashboard   # macOS data directory
# Linux: rm -rf ~/.local/share/life-dashboard
```

---

## Troubleshooting

**The app doesn't open at localhost:3000**

Check whether the services are running:

```bash
make service-status
```

If the web service shows as stopped, check the logs:

```bash
make service-logs
```

**"role does not exist" error during install**

If you see a Postgres role error, your system Postgres may use a different superuser. The install script detects this automatically by using your OS username (`$USER`) instead of `postgres`. Re-running `make service-install` after the first attempt usually resolves it.

**Port 3000 or 8000 is already in use**

Another process has claimed the port. Find and stop it:

```bash
lsof -i :3000
lsof -i :8000
```

**Migrations fail**

Check that `infra/local.env` exists and that `DATABASE_URL` points to a running Postgres. Then run migrations manually:

```bash
make migrate
```

**Bundled Node / Postgres binaries won't run on macOS**

macOS Gatekeeper may quarantine downloaded binaries. The install script removes the quarantine flag automatically with `xattr -dr`, but if you still see a security warning, run:

```bash
xattr -dr com.apple.quarantine infra/runtime/
```
