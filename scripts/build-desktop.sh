#!/usr/bin/env bash
# ── scripts/build-desktop.sh ──────────────────────────────────────────────────
#
# Local desktop build script.  Produces a Tauri installable bundle for the
# current host platform (macOS, Linux; Windows users should run the equivalent
# commands in PowerShell — see the comment at the bottom).
#
# Usage:
#   ./scripts/build-desktop.sh [--skip-api] [--skip-web] [--dev]
#
#   --skip-api   Re-use the last PyInstaller binary (speeds up iteration).
#   --skip-web   Re-use the last Next.js static export.
#   --dev        Run `tauri dev` instead of `tauri build` (opens dev window).
#
# Prerequisites:
#   - Rust + Cargo  (curl https://sh.rustup.rs | sh)
#   - Node 20+      (brew install node / https://nodejs.org)
#   - Python 3.12+  (brew install python@3.12)
#   - api/.venv     (cd api && python3 -m venv .venv && .venv/bin/pip install -e .[dev])
#   - desktop/node_modules  (cd desktop && npm install)
#   - web/node_modules      (cd web && npm install)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$REPO_ROOT/api"
WEB_DIR="$REPO_ROOT/web"
DESKTOP_DIR="$REPO_ROOT/desktop"
BINARIES_DIR="$DESKTOP_DIR/src-tauri/binaries"

SKIP_API=false
SKIP_WEB=false
DEV_MODE=false

# Parse flags
for arg in "$@"; do
  case "$arg" in
    --skip-api) SKIP_API=true ;;
    --skip-web) SKIP_WEB=true ;;
    --dev)      DEV_MODE=true ;;
    *) echo "Unknown flag: $arg" && exit 1 ;;
  esac
done

# ── Detect host triple ────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS-$ARCH" in
  Darwin-x86_64)  TARGET_TRIPLE="x86_64-apple-darwin" ;;
  Darwin-arm64)   TARGET_TRIPLE="aarch64-apple-darwin" ;;
  Linux-x86_64)   TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
  *)
    echo "Unsupported platform: $OS-$ARCH"
    echo "Windows users: run the equivalent commands manually — see notes at the bottom of this script."
    exit 1
    ;;
esac

BINARY_NAME="life_dashboard_api-$TARGET_TRIPLE"

echo "==> Platform: $OS $ARCH  →  $TARGET_TRIPLE"

# ── Step 1: PyInstaller API binary ───────────────────────────────────────────
if [ "$SKIP_API" = true ]; then
  echo "==> [skip] Skipping API binary build (--skip-api)"
  if [ ! -f "$BINARIES_DIR/$BINARY_NAME" ]; then
    echo "ERROR: Expected binary not found at $BINARIES_DIR/$BINARY_NAME"
    echo "       Remove --skip-api to build it first."
    exit 1
  fi
else
  echo "==> Building FastAPI binary with PyInstaller …"
  cd "$API_DIR"

  # Ensure venv exists
  if [ ! -d ".venv" ]; then
    echo "    Creating virtual environment …"
    python3 -m venv .venv
  fi

  # Install deps (idempotent)
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -e ".[dev]"
  .venv/bin/pip install --quiet pyinstaller

  # Run PyInstaller
  .venv/bin/pyinstaller life_dashboard.spec --distpath dist --noconfirm

  # Copy to binaries dir with target-triple suffix
  mkdir -p "$BINARIES_DIR"
  cp "dist/life_dashboard_api" "$BINARIES_DIR/$BINARY_NAME"
  chmod +x "$BINARIES_DIR/$BINARY_NAME"
  echo "    → $BINARIES_DIR/$BINARY_NAME"
fi

# ── Step 2: Next.js static export ────────────────────────────────────────────
if [ "$SKIP_WEB" = true ]; then
  echo "==> [skip] Skipping web build (--skip-web)"
  if [ ! -d "$WEB_DIR/out" ]; then
    echo "ERROR: Expected $WEB_DIR/out not found — remove --skip-web to build it."
    exit 1
  fi
else
  echo "==> Building Next.js static export …"

  # Next.js 16 uses Turbopack for both dev and build, so webpack plugins can't
  # swap files at compile time.  Instead we temporarily replace route.ts with
  # its static shim (force-static, required for output: export) and restore it
  # afterwards — even if the build fails.
  ROUTE_FILE="$WEB_DIR/src/app/api/[...path]/route.ts"
  ROUTE_STATIC="$WEB_DIR/src/app/api/[...path]/route.static.ts"
  ROUTE_BACKUP="$(mktemp)"

  cp "$ROUTE_FILE" "$ROUTE_BACKUP"
  cp "$ROUTE_STATIC" "$ROUTE_FILE"
  trap "cp '$ROUTE_BACKUP' '$ROUTE_FILE'; rm -f '$ROUTE_BACKUP'" EXIT

  cd "$WEB_DIR"
  TAURI=1 \
    NEXT_PUBLIC_API_BASE_URL=http://localhost:1338 \
    NEXT_PUBLIC_TAURI=true \
    npm run build

  # Restore immediately on success; trap handles failure.
  cp "$ROUTE_BACKUP" "$ROUTE_FILE"
  rm -f "$ROUTE_BACKUP"
  trap - EXIT

  echo "    → $WEB_DIR/out"
fi

# ── Step 3: Tauri build / dev ─────────────────────────────────────────────────
cd "$DESKTOP_DIR"

if [ "$DEV_MODE" = true ]; then
  echo "==> Starting Tauri dev window …"
  npm run tauri dev
else
  echo "==> Running Tauri build …"
  npm run tauri build

  echo ""
  echo "✓ Desktop build complete!"
  echo ""
  echo "Installers:"
  case "$OS" in
    Darwin)
      echo "  DMG:  $DESKTOP_DIR/src-tauri/target/release/bundle/dmg/"
      echo "  App:  $DESKTOP_DIR/src-tauri/target/release/bundle/macos/"
      ;;
    Linux)
      echo "  AppImage: $DESKTOP_DIR/src-tauri/target/release/bundle/appimage/"
      echo "  .deb:     $DESKTOP_DIR/src-tauri/target/release/bundle/deb/"
      ;;
  esac
fi

# ── Windows note ──────────────────────────────────────────────────────────────
# Run these commands in a PowerShell session from the repo root:
#
#   # Step 1: API binary
#   cd api
#   python -m venv .venv
#   .venv\Scripts\activate
#   pip install -e ".[dev]" pyinstaller
#   pyinstaller life_dashboard.spec --distpath dist --noconfirm
#   mkdir -Force desktop\src-tauri\binaries
#   Copy-Item dist\life_dashboard_api.exe `
#     desktop\src-tauri\binaries\life_dashboard_api-x86_64-pc-windows-msvc.exe
#
#   # Step 2: Web
#   cd ..\web
#   $env:TAURI="1"; $env:NEXT_PUBLIC_API_BASE_URL="http://localhost:1338"
#   $env:NEXT_PUBLIC_TAURI="true"; npm run build
#
#   # Step 3: Tauri
#   cd ..\desktop
#   npm run tauri build
