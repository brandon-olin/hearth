#!/usr/bin/env python3
"""
One-shot script: mark known-complete todos as done via the Hearth API.
Run from the repo root:
  set -a && . infra/local.env && set +a
  api/.venv/bin/python3.12 infra/scripts/mark-done.py
"""
import json, os, urllib.request, urllib.error

API_URL = os.environ.get("API_URL", "http://127.0.0.1:1338")
EMAIL    = os.environ["HEARTH_SYNC_EMAIL"]
PASSWORD = os.environ["HEARTH_SYNC_PASSWORD"]

# ── IDs to mark done ──────────────────────────────────────────────────────────
DONE = {
    # Process Management
    "759c13a3928e4876a77b89ed4816c65c": "Linux: enable both units from install script",
    "1042f66edf174dc6bd4cc572af07edac": "Linux: write systemd unit for FastAPI",
    "08f252f425d04a229e20e4b20ea28752": "Linux: write systemd unit for Next.js",
    "fe27417f4f5b4e698d57a6e6953ba004": "Provide stop/start/restart CLI mechanism",
    "f22457e100d446c48813d54f1aa7714a": "Verify both processes restart after reboot",
    "bfbe05d9a8854fc38cb92a2a8ddf856d": "macOS: register and load both plists from install script",
    "d227ce7c22c04e5c83f4aa7674f798cc": "macOS: write launchd plist for FastAPI",
    "122181a75fc24a25b1580d7f7caef166": "macOS: write launchd plist for Next.js",
    # Install Script
    "e9f59b44a72648799e413625c7556626": "macOS: chain Postgres install, DB creation, migrations",
    "8e64e6a3131747b9bd99fd3caf462401": "macOS: register launchd agents and open app",
    "bfde35412f9542fdae51838015ec196e": "Make install.sh idempotent",
    # UX Debt
    "328fe8cc15a84a98b980ee1d63198c1b": "Projects: progress ring on project detail page",
}

def api(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

print(f"Authenticating as {EMAIL}…")
token = api("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})["access_token"]

ok = err = 0
for todo_id, label in DONE.items():
    try:
        api("PATCH", f"/todos/{todo_id}", {"status": "done"}, token=token)
        print(f"  ✓ {label}")
        ok += 1
    except urllib.error.HTTPError as e:
        print(f"  ✗ {label}  ({e.code})")
        err += 1

print(f"\nDone — {ok} marked complete, {err} errors.")
