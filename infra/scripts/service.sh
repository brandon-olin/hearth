#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Hearth — process management script
#
# Usage:
#   ./infra/scripts/service.sh <command>
#
# Commands:
#   install     Provision Postgres + Node, build web app, register + start all services
#   uninstall   Stop and unregister services (data and app files untouched)
#   start       Start all services (postgres → api → web)
#   stop        Stop all services (web → api → postgres)
#   restart     Stop then start all services
#   status      Show whether each service is running
#   logs        Tail live logs from all services (Ctrl-C to exit)
#   logs-api    Tail API logs only
#   logs-web    Tail web logs only
#   logs-pg     Tail Postgres logs only
#
# Supports macOS (launchd) and Linux (systemd user services).
# Postgres and Node.js are automatically provisioned if not already installed.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INFRA_DIR="${APP_DIR}/infra"

# ── OS detection ──────────────────────────────────────────────────────────────

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  *)
    echo "ERROR: Unsupported platform: $OS" >&2
    exit 1
    ;;
esac

# ── Platform-specific config ──────────────────────────────────────────────────

if [[ "$PLATFORM" == "macos" ]]; then
  LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
  LOG_DIR="$HOME/Library/Logs/LifeDashboard"
  PG_DATA_DIR="$HOME/Library/Application Support/LifeDashboard/postgres"

  API_LABEL="com.lifedashboard.api"
  WEB_LABEL="com.lifedashboard.web"
  PG_LABEL="com.lifedashboard.postgres"

  API_PLIST="${LAUNCH_AGENTS_DIR}/${API_LABEL}.plist"
  WEB_PLIST="${LAUNCH_AGENTS_DIR}/${WEB_LABEL}.plist"
  PG_PLIST="${LAUNCH_AGENTS_DIR}/${PG_LABEL}.plist"
else
  SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
  LOG_DIR="$HOME/.local/share/life-dashboard/logs"
  PG_DATA_DIR="$HOME/.local/share/life-dashboard/postgres"

  API_UNIT="life-dashboard-api"
  WEB_UNIT="life-dashboard-web"
  PG_UNIT="life-dashboard-postgres"
fi

# ── Runtime state (populated during install) ──────────────────────────────────

NODE_DIR=""
PG_BIN_DIR=""
PG_SUPERUSER="postgres"     # superuser used for DB ops; may be overridden to $USER for system Postgres
POSTGRES_IS_BUNDLED=false   # true = we manage the Postgres service; false = system manages it

# ── Helpers ───────────────────────────────────────────────────────────────────

info()    { echo "  → $*"; }
success() { echo "  ✓ $*"; }
warn()    { echo "  ⚠ $*" >&2; }
die()     { echo "ERROR: $*" >&2; exit 1; }

render_template() {
  local src="$1" dst="$2"
  sed \
    -e "s|{{APP_DIR}}|${APP_DIR}|g" \
    -e "s|{{LOG_DIR}}|${LOG_DIR}|g" \
    -e "s|{{NODE_DIR}}|${NODE_DIR}|g" \
    -e "s|{{PG_BIN_DIR}}|${PG_BIN_DIR}|g" \
    -e "s|{{PG_DATA_DIR}}|${PG_DATA_DIR}|g" \
    -e "s|{{PG_SUPERUSER}}|${PG_SUPERUSER}|g" \
    "$src" > "$dst"
}

# ── Node.js provisioning ──────────────────────────────────────────────────────

NODE_BUNDLE_VERSION="22.14.0"
NODE_BUNDLE_MIN_MAJOR=20

ensure_node() {
  local system_node
  system_node="$(command -v node 2>/dev/null || true)"

  if [[ -n "$system_node" ]]; then
    local major
    major="$("$system_node" --version | sed 's/v//' | cut -d. -f1)"
    if [[ "$major" -ge "$NODE_BUNDLE_MIN_MAJOR" ]]; then
      NODE_DIR="$(dirname "$system_node")"
      success "Node.js v${major} (system) at ${system_node}"
      return
    else
      warn "System Node.js v${major} is too old (need >= ${NODE_BUNDLE_MIN_MAJOR}); downloading bundled version"
    fi
  else
    info "Node.js not found on PATH — downloading bundled version"
  fi

  local os_name arch node_platform node_arch
  os_name="$(uname -s)"
  arch="$(uname -m)"

  case "$os_name" in
    Darwin) node_platform="darwin" ;;
    Linux)  node_platform="linux"  ;;
    *) die "Unsupported OS for bundled Node: ${os_name}" ;;
  esac

  case "$arch" in
    arm64|aarch64) node_arch="arm64" ;;
    x86_64)        node_arch="x64"   ;;
    *) die "Unsupported architecture for bundled Node: ${arch}" ;;
  esac

  local bundle_dir="${APP_DIR}/infra/runtime/node"
  local tarball="node-v${NODE_BUNDLE_VERSION}-${node_platform}-${node_arch}.tar.gz"
  local url="https://nodejs.org/dist/v${NODE_BUNDLE_VERSION}/${tarball}"
  local tmp_dir
  tmp_dir="$(mktemp -d)"

  info "Downloading Node.js v${NODE_BUNDLE_VERSION} (${node_platform}-${node_arch})…"
  curl -fsSL --progress-bar "$url" -o "${tmp_dir}/${tarball}" \
    || die "Failed to download Node.js from ${url}"

  mkdir -p "$bundle_dir"
  tar -xzf "${tmp_dir}/${tarball}" -C "$bundle_dir" --strip-components=1
  rm -rf "$tmp_dir"

  NODE_DIR="${bundle_dir}/bin"
  success "Bundled Node.js v${NODE_BUNDLE_VERSION} installed at ${bundle_dir}"
}

# ── Postgres provisioning ─────────────────────────────────────────────────────
# Pinned to Postgres 16 — no upgrade path needed for M1.
# To update the bundled version, change PG_BUNDLE_VERSION and re-run install.
#
# Download URLs use EDB (EnterpriseDB) community builds — the official
# binary distribution endorsed by postgresql.org.
# Verify / update at: https://www.enterprisedb.com/download-postgresql-binaries

PG_BUNDLE_VERSION="16.6"
PG_BUNDLE_MIN_MAJOR=14

ensure_postgres() {
  # ── Prefer system Postgres if it meets minimum version ────────────────────
  local system_pg
  system_pg="$(command -v pg_ctl 2>/dev/null || true)"

  if [[ -n "$system_pg" ]]; then
    local major
    major="$("$system_pg" --version | grep -oE '[0-9]+' | head -1)"
    if [[ "$major" -ge "$PG_BUNDLE_MIN_MAJOR" ]]; then
      PG_BIN_DIR="$(dirname "$system_pg")"
      POSTGRES_IS_BUNDLED=false
      # System Postgres (e.g. Homebrew) uses the current OS user as superuser.
      PG_SUPERUSER="$USER"
      success "PostgreSQL v${major} (system) at ${PG_BIN_DIR}"
      return
    else
      warn "System PostgreSQL v${major} is too old (need >= ${PG_BUNDLE_MIN_MAJOR}); downloading bundled version"
    fi
  else
    info "PostgreSQL not found on PATH — downloading bundled version"
  fi

  # ── Resolve platform / architecture ───────────────────────────────────────
  local os_name arch pg_platform pg_arch
  os_name="$(uname -s)"
  arch="$(uname -m)"

  case "$os_name" in
    Darwin)
      pg_platform="osx"
      # EDB provides native arm64 builds for macOS from Postgres 15+.
      # For older versions or if arm64 build is unavailable, x64 runs via Rosetta 2.
      case "$arch" in
        arm64|aarch64) pg_arch="aarch64" ;;
        *)             pg_arch=""        ;;  # empty = x64 (default EDB naming)
      esac
      ;;
    Linux)
      pg_platform="linux"
      case "$arch" in
        arm64|aarch64) pg_arch="arm64" ;;
        x86_64)        pg_arch="x64"   ;;
        *) die "Unsupported architecture for bundled Postgres: ${arch}" ;;
      esac
      ;;
    *) die "Unsupported OS for bundled Postgres: ${os_name}" ;;
  esac

  # ── Build download URL ─────────────────────────────────────────────────────
  local bundle_dir="${APP_DIR}/infra/runtime/postgres"
  local filename suffix url

  if [[ "$pg_platform" == "osx" ]]; then
    if [[ "$pg_arch" == "aarch64" ]]; then
      filename="postgresql-${PG_BUNDLE_VERSION}-1-osx-aarch64-binaries.zip"
    else
      filename="postgresql-${PG_BUNDLE_VERSION}-1-osx-binaries.zip"
    fi
    suffix="zip"
  else
    filename="postgresql-${PG_BUNDLE_VERSION}-1-${pg_platform}-${pg_arch}-binaries.tar.gz"
    suffix="tar.gz"
  fi

  url="https://get.enterprisedb.com/postgresql/${filename}"

  # ── Download and extract ───────────────────────────────────────────────────
  local tmp_dir
  tmp_dir="$(mktemp -d)"

  info "Downloading PostgreSQL v${PG_BUNDLE_VERSION} (${pg_platform} ${pg_arch:-x64})…"
  info "This is a ~90MB download — please wait…"
  curl -fsSL --progress-bar "$url" -o "${tmp_dir}/${filename}" \
    || die "Failed to download PostgreSQL from ${url}
       Verify the URL at: https://www.enterprisedb.com/download-postgresql-binaries"

  info "Extracting…"
  mkdir -p "$bundle_dir"
  if [[ "$suffix" == "zip" ]]; then
    unzip -q "${tmp_dir}/${filename}" -d "${tmp_dir}/pg_extract"
    # EDB zip extracts to a 'pgsql/' subdirectory
    cp -R "${tmp_dir}/pg_extract/pgsql/." "$bundle_dir/"
    # Remove macOS quarantine so binaries run without Gatekeeper prompts
    xattr -dr com.apple.quarantine "$bundle_dir" 2>/dev/null || true
  else
    tar -xzf "${tmp_dir}/${filename}" -C "$bundle_dir" --strip-components=1
  fi
  rm -rf "$tmp_dir"

  PG_BIN_DIR="${bundle_dir}/bin"
  POSTGRES_IS_BUNDLED=true
  success "Bundled PostgreSQL v${PG_BUNDLE_VERSION} installed at ${bundle_dir}"
}

# ── Postgres data directory setup ─────────────────────────────────────────────

setup_postgres_data() {
  if [[ -d "$PG_DATA_DIR" && -f "${PG_DATA_DIR}/PG_VERSION" ]]; then
    success "Postgres data directory already initialised at ${PG_DATA_DIR}"
    return
  fi

  info "Initialising Postgres data directory at ${PG_DATA_DIR}…"
  mkdir -p "$PG_DATA_DIR"

  "${PG_BIN_DIR}/initdb" \
    -D "$PG_DATA_DIR" \
    --auth=trust \
    --username=postgres \
    --encoding=UTF8 \
    --locale=C

  # ── pg_hba.conf: trust all local connections ───────────────────────────────
  # Safe for a single-user local install — the DB is never exposed to the network.
  cat > "${PG_DATA_DIR}/pg_hba.conf" << 'EOF'
# Hearth — local install pg_hba.conf
# Trust auth on Unix socket and loopback — no passwords needed for local access.
local   all   all                trust
host    all   all   127.0.0.1/32 trust
host    all   all   ::1/32       trust
EOF

  # ── postgresql.conf: minimal overrides ────────────────────────────────────
  cat >> "${PG_DATA_DIR}/postgresql.conf" << EOF

# ── Hearth settings ──────────────────────────────────────────────────
port = 5432
# Write logs to stderr; launchd/systemd captures them into our log files.
log_destination = 'stderr'
logging_collector = off
EOF

  success "Postgres data directory initialised"
}

# ── Postgres readiness / database helpers ─────────────────────────────────────

wait_for_postgres() {
  info "Waiting for Postgres to accept connections…"
  local i
  for i in $(seq 1 30); do
    "${PG_BIN_DIR}/pg_isready" -q -h 127.0.0.1 -U "$PG_SUPERUSER" 2>/dev/null && return
    sleep 1
  done
  die "Postgres did not become ready within 30 seconds.
     Check logs with:  ./infra/scripts/service.sh logs-pg"
}

ensure_database() {
  local db="life_dashboard"
  if "${PG_BIN_DIR}/psql" -h 127.0.0.1 -U "$PG_SUPERUSER" -lqt 2>/dev/null \
      | cut -d'|' -f1 | grep -qw "$db"; then
    success "Database '${db}' already exists"
  else
    "${PG_BIN_DIR}/createdb" -h 127.0.0.1 -U "$PG_SUPERUSER" "$db"
    success "Database '${db}' created"
  fi
}

run_migrations() {
  info "Running Alembic migrations…"
  (
    set -a
    # shellcheck disable=SC1091
    . "${INFRA_DIR}/local.env"
    set +a
    cd "${APP_DIR}/api"
    .venv/bin/alembic upgrade head
  )
  success "Migrations complete"
}

# ── macOS helpers ─────────────────────────────────────────────────────────────

macos_load() {
  local label="$1" plist="$2"
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load -w "$plist"
  success "Loaded ${label}"
}

macos_unload() {
  local label="$1" plist="$2"
  launchctl unload "$plist" 2>/dev/null && success "Unloaded ${label}" || warn "${label} was not loaded"
}

macos_start() {
  local label="$1"
  launchctl start "$label" && success "Started ${label}" || warn "Could not start ${label} (may already be running)"
}

macos_stop() {
  local label="$1"
  launchctl stop "$label" && success "Stopped ${label}" || warn "Could not stop ${label} (may not be running)"
}

macos_status() {
  local label="$1"
  local pid
  pid=$(launchctl list | awk -v lbl="$label" '$3 == lbl {print $1}')
  if [[ -n "$pid" && "$pid" != "-" ]]; then
    echo "  ● ${label}   running (PID ${pid})"
  else
    local last_exit
    last_exit=$(launchctl list | awk -v lbl="$label" '$3 == lbl {print $2}')
    if [[ -n "$last_exit" ]]; then
      echo "  ○ ${label}   stopped (last exit: ${last_exit})"
    else
      echo "  ○ ${label}   not registered"
    fi
  fi
}

# ── Linux helpers ─────────────────────────────────────────────────────────────

linux_enable() {
  local unit="$1"
  systemctl --user enable --now "${unit}" && success "Enabled + started ${unit}" || die "Failed to enable ${unit}"
}

linux_disable() {
  local unit="$1"
  systemctl --user disable --now "${unit}" 2>/dev/null && success "Disabled ${unit}" || warn "${unit} was not enabled"
}

linux_start() {
  local unit="$1"
  systemctl --user start "${unit}" && success "Started ${unit}" || warn "Could not start ${unit}"
}

linux_stop() {
  local unit="$1"
  systemctl --user stop "${unit}" && success "Stopped ${unit}" || warn "Could not stop ${unit}"
}

linux_status() {
  local unit="$1"
  systemctl --user status "${unit}" --no-pager -l 2>&1 | head -5 || true
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_install() {
  echo "Installing Hearth…"
  echo

  # ── Preflight checks ───────────────────────────────────────────────────────

  if [[ ! -f "${INFRA_DIR}/local.env" ]]; then
    die "infra/local.env not found.
       Copy the example and fill in your values:
         cp infra/local.env.example infra/local.env
         \$EDITOR infra/local.env"
  fi

  if [[ ! -f "${APP_DIR}/api/.venv/bin/uvicorn" ]]; then
    die "Python venv not found at api/.venv
       Run:  cd api && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  fi

  if [[ ! -d "${APP_DIR}/web/node_modules" ]]; then
    die "web/node_modules not found.
       Run:  cd web && npm install"
  fi

  # ── Provision runtimes ─────────────────────────────────────────────────────

  echo "── Runtimes ──"
  ensure_node
  ensure_postgres
  echo

  # ── Set up Postgres data directory ────────────────────────────────────────

  echo "── Database ──"

  # For bundled Postgres we own the data directory; for system Postgres the
  # package manager (e.g. Homebrew) already owns and manages it.
  if [[ "$POSTGRES_IS_BUNDLED" == true ]]; then
    setup_postgres_data
  fi

  # Patch DATABASE_URL in local.env to use the active superuser.
  # Bundled Postgres is always initialised with the "postgres" role;
  # system Postgres (Homebrew etc.) uses the OS user as superuser.
  if [[ -f "${INFRA_DIR}/local.env" && "$PG_SUPERUSER" != "postgres" ]]; then
    sed -i.bak \
      "s|postgresql+asyncpg://[^@]*@|postgresql+asyncpg://${PG_SUPERUSER}@|g" \
      "${INFRA_DIR}/local.env"
    rm -f "${INFRA_DIR}/local.env.bak"
    info "Updated DATABASE_URL to use system Postgres user '${PG_SUPERUSER}'"
  fi

  # Register and start Postgres service first (API depends on it)
  if [[ "$POSTGRES_IS_BUNDLED" == true ]]; then
    mkdir -p "$LOG_DIR"
    if [[ "$PLATFORM" == "macos" ]]; then
      mkdir -p "$LAUNCH_AGENTS_DIR"
      render_template "${INFRA_DIR}/launchd/com.lifedashboard.postgres.plist.tpl" "$PG_PLIST"
      macos_load "$PG_LABEL" "$PG_PLIST"
    else
      mkdir -p "$SYSTEMD_USER_DIR"
      render_template \
        "${INFRA_DIR}/systemd/life-dashboard-postgres.service.tpl" \
        "${SYSTEMD_USER_DIR}/${PG_UNIT}.service"
      systemctl --user daemon-reload
      linux_enable "$PG_UNIT"
    fi
  else
    info "Using system Postgres — skipping service registration"
  fi

  wait_for_postgres
  ensure_database
  run_migrations
  echo

  # ── Build the Next.js app ──────────────────────────────────────────────────

  echo "── Web app ──"
  info "Building Next.js (this takes ~60s)…"
  set -a
  # shellcheck disable=SC1091
  . "${INFRA_DIR}/local.env"
  set +a
  (cd "${APP_DIR}/web" && node_modules/.bin/next build)
  success "Web app built"
  echo

  # ── Generate run wrapper scripts ───────────────────────────────────────────

  echo "── Services ──"
  mkdir -p "$LOG_DIR"

  local run_api="${INFRA_DIR}/scripts/run-api.sh"
  local run_web="${INFRA_DIR}/scripts/run-web.sh"

  render_template "${INFRA_DIR}/scripts/run-api.sh.tpl" "$run_api"
  render_template "${INFRA_DIR}/scripts/run-web.sh.tpl" "$run_web"
  chmod +x "$run_api" "$run_web"
  success "Generated run-api.sh and run-web.sh"

  # ── Register API + web services ────────────────────────────────────────────

  if [[ "$PLATFORM" == "macos" ]]; then
    render_template "${INFRA_DIR}/launchd/com.lifedashboard.api.plist.tpl" "$API_PLIST"
    render_template "${INFRA_DIR}/launchd/com.lifedashboard.web.plist.tpl" "$WEB_PLIST"
    success "Generated LaunchAgent plists"
    macos_load "$API_LABEL" "$API_PLIST"
    macos_load "$WEB_LABEL" "$WEB_PLIST"
  else
    render_template \
      "${INFRA_DIR}/systemd/life-dashboard-api.service.tpl" \
      "${SYSTEMD_USER_DIR}/${API_UNIT}.service"
    render_template \
      "${INFRA_DIR}/systemd/life-dashboard-web.service.tpl" \
      "${SYSTEMD_USER_DIR}/${WEB_UNIT}.service"
    success "Generated systemd unit files"
    systemctl --user daemon-reload
    linux_enable "$API_UNIT"
    linux_enable "$WEB_UNIT"
  fi

  echo
  echo "✓ Hearth installed and running."
  echo "  App  →  http://localhost:1337"
  echo "  API  →  http://127.0.0.1:1338"
  echo
  echo "  Logs:    ./infra/scripts/service.sh logs"
  echo "  Status:  ./infra/scripts/service.sh status"
}

cmd_uninstall() {
  echo "Uninstalling Hearth services…"
  echo

  if [[ "$PLATFORM" == "macos" ]]; then
    [[ -f "$WEB_PLIST" ]] && { macos_unload "$WEB_LABEL" "$WEB_PLIST"; rm -f "$WEB_PLIST"; } || warn "web plist not found"
    [[ -f "$API_PLIST" ]] && { macos_unload "$API_LABEL" "$API_PLIST"; rm -f "$API_PLIST"; } || warn "api plist not found"
    [[ -f "$PG_PLIST"  ]] && { macos_unload "$PG_LABEL"  "$PG_PLIST";  rm -f "$PG_PLIST";  } || true
  else
    linux_disable "$WEB_UNIT" || true
    linux_disable "$API_UNIT" || true
    linux_disable "$PG_UNIT"  || true
    rm -f "${SYSTEMD_USER_DIR}/${WEB_UNIT}.service" \
          "${SYSTEMD_USER_DIR}/${API_UNIT}.service" \
          "${SYSTEMD_USER_DIR}/${PG_UNIT}.service"
    systemctl --user daemon-reload
  fi

  echo
  echo "✓ Services uninstalled."
  echo "  Your data is intact at: ${PG_DATA_DIR}"
  echo "  To remove data too:     rm -rf \"${PG_DATA_DIR}\""
}

cmd_start() {
  echo "Starting Hearth…"
  if [[ "$PLATFORM" == "macos" ]]; then
    # Postgres first — API waits for it in run-api.sh
    [[ -f "$PG_PLIST" ]] && macos_start "$PG_LABEL" || true
    macos_start "$API_LABEL"
    macos_start "$WEB_LABEL"
  else
    [[ -f "${SYSTEMD_USER_DIR}/${PG_UNIT}.service" ]] && linux_start "$PG_UNIT" || true
    linux_start "$API_UNIT"
    linux_start "$WEB_UNIT"
  fi
}

cmd_stop() {
  echo "Stopping Hearth…"
  if [[ "$PLATFORM" == "macos" ]]; then
    macos_stop "$WEB_LABEL"
    macos_stop "$API_LABEL"
    [[ -f "$PG_PLIST" ]] && macos_stop "$PG_LABEL" || true
  else
    linux_stop "$WEB_UNIT"
    linux_stop "$API_UNIT"
    [[ -f "${SYSTEMD_USER_DIR}/${PG_UNIT}.service" ]] && linux_stop "$PG_UNIT" || true
  fi
}

cmd_restart() {
  cmd_stop
  sleep 2
  cmd_start
}

cmd_status() {
  echo "Hearth service status:"
  echo
  if [[ "$PLATFORM" == "macos" ]]; then
    [[ -f "$PG_PLIST"  ]] && macos_status "$PG_LABEL"
    macos_status "$API_LABEL"
    macos_status "$WEB_LABEL"
  else
    [[ -f "${SYSTEMD_USER_DIR}/${PG_UNIT}.service" ]] && linux_status "$PG_UNIT"
    linux_status "$API_UNIT"
    linux_status "$WEB_UNIT"
  fi
  echo
}

cmd_logs() {
  echo "Tailing logs (Ctrl-C to exit)…"
  echo
  if [[ "$PLATFORM" == "macos" ]]; then
    tail -f \
      "${LOG_DIR}/postgres.log" "${LOG_DIR}/postgres.error.log" \
      "${LOG_DIR}/api.log"      "${LOG_DIR}/api.error.log" \
      "${LOG_DIR}/web.log"      "${LOG_DIR}/web.error.log" \
      2>/dev/null
  else
    journalctl --user -u "$PG_UNIT" -u "$API_UNIT" -u "$WEB_UNIT" -f --output=short-iso
  fi
}

cmd_logs_api() {
  echo "Tailing API logs (Ctrl-C to exit)…"
  if [[ "$PLATFORM" == "macos" ]]; then
    tail -f "${LOG_DIR}/api.log" "${LOG_DIR}/api.error.log" 2>/dev/null
  else
    journalctl --user -u "$API_UNIT" -f --output=short-iso
  fi
}

cmd_logs_web() {
  echo "Tailing web logs (Ctrl-C to exit)…"
  if [[ "$PLATFORM" == "macos" ]]; then
    tail -f "${LOG_DIR}/web.log" "${LOG_DIR}/web.error.log" 2>/dev/null
  else
    journalctl --user -u "$WEB_UNIT" -f --output=short-iso
  fi
}

cmd_logs_pg() {
  echo "Tailing Postgres logs (Ctrl-C to exit)…"
  if [[ "$PLATFORM" == "macos" ]]; then
    tail -f "${LOG_DIR}/postgres.log" "${LOG_DIR}/postgres.error.log" 2>/dev/null
  else
    journalctl --user -u "$PG_UNIT" -f --output=short-iso
  fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

CMD="${1:-}"

case "$CMD" in
  install)   cmd_install   ;;
  uninstall) cmd_uninstall ;;
  start)     cmd_start     ;;
  stop)      cmd_stop      ;;
  restart)   cmd_restart   ;;
  status)    cmd_status    ;;
  logs)      cmd_logs      ;;
  logs-api)  cmd_logs_api  ;;
  logs-web)  cmd_logs_web  ;;
  logs-pg)   cmd_logs_pg   ;;
  *)
    echo "Usage: $0 <command>"
    echo
    echo "Commands:"
    echo "  install    Provision Postgres + Node, build web app, start everything"
    echo "  uninstall  Stop and unregister services (data untouched)"
    echo "  start      Start all services"
    echo "  stop       Stop all services"
    echo "  restart    Restart all services"
    echo "  status     Show running status"
    echo "  logs       Tail live logs (all services)"
    echo "  logs-api   Tail API logs only"
    echo "  logs-web   Tail web logs only"
    echo "  logs-pg    Tail Postgres logs only"
    echo
    exit 1
    ;;
esac
