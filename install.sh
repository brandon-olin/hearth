#!/usr/bin/env bash
# install.sh — Hearth local installer
#
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/brandon-olin/life-dashboard/main/install.sh | bash
#
# Or clone the repo and run directly:
#   git clone https://github.com/brandon-olin/life-dashboard.git
#   cd life-dashboard && ./install.sh

set -euo pipefail

REPO_URL="https://github.com/brandon-olin/life-dashboard.git"
INSTALL_DIR="${LIFE_DASHBOARD_DIR:-$HOME/life-dashboard}"

# ── Colours ───────────────────────────────────────────────────────────────────

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "  ${BOLD}→${NC} $*"; }
success() { echo -e "  ${GREEN}✓${NC} $*"; }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $*" >&2; }
die()     { echo -e "  ${RED}✗${NC}  $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── Prerequisite checks ───────────────────────────────────────────────────────

check_prerequisites() {
  header "Checking prerequisites"

  # git
  command -v git &>/dev/null \
    || die "git is required but not found.\n     Install it from https://git-scm.com or via your package manager."
  success "git $(git --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"

  # Python 3.12+
  local python=""
  for candidate in python3.12 python3.13 python3.14; do
    if command -v "$candidate" &>/dev/null; then
      python="$candidate"
      break
    fi
  done

  if [[ -z "$python" ]]; then
    # Fall back to python3 if it's >= 3.12
    if command -v python3 &>/dev/null; then
      local ver
      ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      local minor
      minor="$(echo "$ver" | cut -d. -f2)"
      if [[ "$minor" -ge 12 ]]; then
        python="python3"
      fi
    fi
  fi

  [[ -n "$python" ]] || die "Python 3.12 or newer is required but not found.
     Install it from https://python.org or via your package manager:
       macOS:  brew install python@3.12
       Ubuntu: sudo apt install python3.12"

  local py_ver
  py_ver="$("$python" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
  success "Python $py_ver ($python)"
  export PYTHON="$python"

  # Node.js 20+ (optional — service.sh will download if missing)
  if command -v node &>/dev/null; then
    local node_major
    node_major="$(node --version | grep -oE '[0-9]+' | head -1)"
    if [[ "$node_major" -ge 20 ]]; then
      success "Node.js $(node --version) (system)"
    else
      warn "System Node.js $(node --version) is older than v20 — service.sh will download a bundled version"
    fi
  else
    info "Node.js not found — service.sh will download a bundled version during install"
  fi
}

# ── Repo setup ────────────────────────────────────────────────────────────────

setup_repo() {
  header "Repository"

  # If we're already inside the repo (e.g. the user cloned and ran ./install.sh),
  # use the current directory instead of cloning.
  if [[ -f "$(pwd)/infra/scripts/service.sh" ]]; then
    INSTALL_DIR="$(pwd)"
    success "Using existing repo at ${INSTALL_DIR}"
    return
  fi

  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating existing install at ${INSTALL_DIR}…"
    git -C "$INSTALL_DIR" pull --ff-only \
      || warn "git pull failed — continuing with existing code"
    success "Repo up to date"
  else
    info "Cloning into ${INSTALL_DIR}…"
    git clone "$REPO_URL" "$INSTALL_DIR"
    success "Cloned to ${INSTALL_DIR}"
  fi
}

# ── Python virtual environment ────────────────────────────────────────────────

setup_python() {
  header "Python environment"

  local venv_dir="${INSTALL_DIR}/api/.venv"

  if [[ ! -d "$venv_dir" ]]; then
    info "Creating virtual environment…"
    "$PYTHON" -m venv "$venv_dir"
    success "Virtual environment created"
  else
    success "Virtual environment already exists"
  fi

  info "Installing Python dependencies…"
  "${venv_dir}/bin/pip" install --quiet -e "${INSTALL_DIR}/api[dev]"
  success "Python dependencies installed"
}

# ── Node dependencies ─────────────────────────────────────────────────────────

setup_node() {
  header "Node dependencies"

  if [[ ! -d "${INSTALL_DIR}/web/node_modules" ]]; then
    info "Installing Node dependencies (this takes ~30s)…"
    (cd "${INSTALL_DIR}/web" && npm install --silent)
    success "Node dependencies installed"
  else
    success "Node dependencies already installed"
  fi
}

# ── Environment file ──────────────────────────────────────────────────────────

setup_env() {
  header "Environment"

  local env_file="${INSTALL_DIR}/infra/local.env"
  local example="${INSTALL_DIR}/infra/local.env.example"

  if [[ -f "$env_file" ]]; then
    success "local.env already exists — skipping"
    return
  fi

  info "Creating infra/local.env from template…"
  cp "$example" "$env_file"

  # Generate a random JWT secret key automatically
  local secret
  secret="$("$PYTHON" -c "import secrets; print(secrets.token_hex(32))")"
  sed -i.bak "s|JWT_SECRET_KEY=CHANGE_ME|JWT_SECRET_KEY=${secret}|" "$env_file"
  rm -f "${env_file}.bak"

  success "infra/local.env created with a generated JWT secret"
  echo
  echo -e "  ${YELLOW}Note:${NC} The JWT secret has been generated automatically."
  echo    "        Never change it after first run — it invalidates all sessions."
}

# ── Service install ───────────────────────────────────────────────────────────

run_service_install() {
  header "Installing services"

  local service_sh="${INSTALL_DIR}/infra/scripts/service.sh"
  chmod +x "$service_sh"

  # Run from the repo root so service.sh can find APP_DIR correctly
  (cd "$INSTALL_DIR" && "$service_sh" install)
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
  echo
  echo -e "${BOLD}Hearth — Local Installer${NC}"
  echo    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo

  check_prerequisites
  setup_repo
  setup_python
  setup_node
  setup_env
  run_service_install

  echo
  echo -e "${BOLD}${GREEN}All done!${NC}"
  echo
  echo    "  Hearth is running at http://localhost:1337"
  echo    "  Open the URL in your browser to finish setup."
  echo
  echo    "  Useful commands:"
  echo    "    make service-status    — check if services are running"
  echo    "    make service-logs      — tail live logs"
  echo    "    make service-restart   — restart after a code change"
  echo    "    make service-stop      — stop everything"
  echo
}

main "$@"
