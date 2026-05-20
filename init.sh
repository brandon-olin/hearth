#!/usr/bin/env bash
# init.sh — Hearth agent harness startup script
#
# Run this at the start of every agent session to:
#   1. Start the dev API server (uvicorn --reload on port 1339)
#   2. Apply any pending database migrations
#   3. Verify the API is responding
#   4. Report web server status
#
# Usage: ./init.sh
# Logs:  .agent-logs/api.log

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_PORT=1339
API_URL="http://localhost:${API_PORT}"
WEB_PORT=1337
WEB_URL="http://localhost:${WEB_PORT}"
LOG_DIR="${REPO_ROOT}/.agent-logs"
PID_FILE="${LOG_DIR}/api.pid"

mkdir -p "$LOG_DIR"

echo "╔══════════════════════════════════════╗"
echo "║     Hearth — agent init              ║"
echo "╚══════════════════════════════════════╝"
echo "Repo: $REPO_ROOT"
echo "Date: $(date)"
echo ""

# ── 1. Dev API (uvicorn --reload, port 1339) ──────────────────────────────────
echo "→ Checking dev API on :${API_PORT}..."
if curl -sf "${API_URL}/openapi.json" >/dev/null 2>&1; then
    echo "  ✓ Already running"
else
    echo "  Starting uvicorn --reload on :${API_PORT}..."
    cd "$REPO_ROOT"
    # Kill any stale pid
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        kill "$OLD_PID" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    # Activate venv and start in background
    nohup bash -c "cd '${REPO_ROOT}/api' && .venv/bin/uvicorn life_dashboard.main:app --reload --port ${API_PORT}" \
        > "$LOG_DIR/api.log" 2>&1 &
    echo $! > "$PID_FILE"
    echo "  PID: $(cat $PID_FILE) — logs at .agent-logs/api.log"

    echo "  Waiting for API to be ready..."
    MAX_WAIT=60
    waited=0
    until curl -sf "${API_URL}/openapi.json" >/dev/null 2>&1; do
        if [ "$waited" -ge "$MAX_WAIT" ]; then
            echo ""
            echo "ERROR: API did not come up within ${MAX_WAIT}s."
            echo "Check logs: cat .agent-logs/api.log"
            exit 1
        fi
        sleep 2
        waited=$((waited + 2))
        printf "  %ds...\r" "$waited"
    done
    echo "  ✓ API ready after ${waited}s"
fi

# ── 2. Apply pending migrations ───────────────────────────────────────────────
echo ""
echo "→ Applying pending migrations..."
cd "$REPO_ROOT/api"
if .venv/bin/alembic upgrade head 2>&1 | tail -3; then
    echo "  ✓ Migrations up to date"
fi

# ── 3. Smoke test — API ───────────────────────────────────────────────────────
echo ""
echo "→ Running API smoke tests..."

# OpenAPI schema
if curl -sf "${API_URL}/openapi.json" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  ✓ OpenAPI schema OK —', len(d.get('paths',{})), 'routes')"; then
    :
else
    echo "  ✗ Failed to parse OpenAPI schema"
    exit 1
fi

# Auth endpoint exists
if curl -sf -o /dev/null -w "  ✓ POST /auth/login → HTTP %{http_code}\n" \
    -X POST "${API_URL}/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"_ping_","password":"_ping_"}'; then
    :
fi

# ── 4. Web server status ──────────────────────────────────────────────────────
echo ""
echo "→ Checking web server on :${WEB_PORT}..."
if curl -sf "${WEB_URL}" >/dev/null 2>&1; then
    # Distinguish launchd (next start) from dev (next dev) by checking for HMR
    if curl -sf "${WEB_URL}/_next/webpack-hmr" >/dev/null 2>&1; then
        echo "  ✓ Next.js dev server running (hot reload active)"
    else
        echo "  ✓ Next.js production server running (launchd)"
        echo "  ⚠  Web code changes won't hot-reload."
        echo "     To enable: make service-stop && make web (new terminal)"
    fi
else
    echo "  ✗ Web server not running on :${WEB_PORT}"
    echo "     To start: make web (new terminal), or: make service-start (production)"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Init complete — ready to work       ║"
echo "╚══════════════════════════════════════╝"
echo "API: ${API_URL}/docs"
echo "Web: ${WEB_URL}"
echo ""
echo "Next steps:"
echo "  1. Read claude-progress.txt for recent context"
echo "  2. Run: git log --oneline -20"
echo "  3. Read feature_list.json to choose the next feature"
