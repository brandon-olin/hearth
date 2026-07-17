#!/usr/bin/env python3
"""
refresh_test_data.py — Re-date stale seeded data so the dashboard looks current.

Finds all open todos (pending / in_progress) whose due_date is in the past and
spreads them across the coming days instead. Nothing is created or deleted —
existing rows are PATCHed in place, so re-running is safe (idempotent: a todo
that's no longer overdue is left alone).

Usage:
  python scripts/refresh_test_data.py [--host http://localhost:1338] \
                                      [--email test@hearth.local] \
                                      [--password password] \
                                      [--horizon 14] \
                                      [--dry-run]

  --horizon N   spread overdue todos over the next N days (default 14)
  --dry-run     show what would change without writing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.parse import urlencode

parser = argparse.ArgumentParser(description="Refresh overdue Hearth test data")
parser.add_argument("--host", default="http://localhost:1338")
parser.add_argument("--email", default="test@hearth.local")
parser.add_argument("--password", default="password")
parser.add_argument("--horizon", type=int, default=14)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

BASE = args.host.rstrip("/")
_headers: dict[str, str] = {"Content-Type": "application/json"}


def _request(method: str, path: str, body: dict | None = None,
             params: dict | None = None) -> tuple[int, dict | list]:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib_request.Request(url, data=data, headers=_headers, method=method)
    try:
        with urllib_request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except HTTPError as e:
        return e.code, {"_error": e.read().decode()[:200]}


def login() -> None:
    status, data = _request("POST", "/auth/login",
                            {"email": args.email, "password": args.password})
    if status != 200 or not isinstance(data, dict):
        print(f"❌  Login failed for {args.email}: {status} {data}")
        if status == 401:
            print(
                "\nℹ️   Note: the Hearth desktop app runs its own API sidecar on\n"
                "    127.0.0.1:1338 backed by a private SQLite database\n"
                "    (~/Library/Application Support/com.lifedashboard.desktop/life_dashboard.db),\n"
                "    NOT your dev Postgres. If the desktop app is running, this script\n"
                "    is talking to that SQLite DB, where the Postgres test account\n"
                "    doesn't exist.\n\n"
                "    → To refresh the desktop app's data: pass --email/--password for\n"
                "      an account created inside the desktop app.\n"
                "    → To refresh the dev-stack (Postgres) data: quit the desktop app,\n"
                "      start the dev API (cd api && source .venv/bin/activate &&\n"
                "      uvicorn life_dashboard.main:app --reload --port 1338), re-run."
            )
        sys.exit(1)
    _headers["Authorization"] = f"Bearer {data['access_token']}"
    print(f"✅  Logged in as {args.email}")


def fetch_open_todos() -> list[dict]:
    """Paginate through pending + in_progress todos."""
    todos: list[dict] = []
    for status_filter in ("pending", "in_progress"):
        offset = 0
        while True:
            code, data = _request("GET", "/todos", params={
                "status": status_filter, "limit": 500, "offset": offset,
            })
            if code != 200:
                print(f"  ⚠️  GET /todos ({status_filter}) → {code}: {data}")
                break
            items = data.get("items", data) if isinstance(data, dict) else data
            if not isinstance(items, list) or not items:
                break
            todos.extend(items)
            if len(items) < 500:
                break
            offset += 500
    return todos


def main() -> None:
    login()
    today = date.today()
    horizon = max(args.horizon, 1)

    todos = fetch_open_todos()
    overdue = [t for t in todos
               if t.get("due_date") and date.fromisoformat(t["due_date"]) < today]
    print(f"📋  {len(todos)} open todos; {len(overdue)} overdue")
    if not overdue:
        print("✨  Nothing to refresh.")
        return

    # Oldest first, then spread evenly across the horizon so no single day
    # gets dumped on. Integer stride keeps it deterministic.
    overdue.sort(key=lambda t: t["due_date"])
    changed = 0
    for i, todo in enumerate(overdue):
        new_due = today + timedelta(days=(i * horizon) // len(overdue))
        label = f"{todo.get('title', todo['id'])[:60]}: {todo['due_date']} → {new_due}"
        if args.dry_run:
            print(f"  🔍  would update {label}")
            continue
        code, data = _request("PATCH", f"/todos/{todo['id']}",
                              {"due_date": new_due.isoformat()})
        if code in (200, 201):
            changed += 1
            print(f"  ✅  {label}")
        else:
            print(f"  ⚠️  PATCH /todos/{todo['id']} → {code}: {data}")

    if args.dry_run:
        print(f"\n🔍  Dry run complete — {len(overdue)} todos would be re-dated.")
    else:
        print(f"\n✨  Done — {changed}/{len(overdue)} overdue todos re-dated "
              f"across the next {horizon} days.")


if __name__ == "__main__":
    main()
