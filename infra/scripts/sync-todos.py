#!/usr/bin/env python3
"""
sync-todos.py — Keep your Hearth todo list in sync with feature_list.json.

Reads every planned feature and creates or updates a corresponding todo
in your running Hearth instance, so you always have a live view of the
build backlog right alongside your household tasks.

Configuration (via environment variables, easiest to put in infra/local.env):
  HEARTH_SYNC_EMAIL     Hearth account email to authenticate as
  HEARTH_SYNC_PASSWORD  Hearth account password
  API_URL               Hearth API base URL  (default: http://127.0.0.1:1338)

Run manually:
  cd /path/to/life-dashboard
  set -a && . infra/local.env && set +a
  api/.venv/bin/python3.12 infra/scripts/sync-todos.py

Or install the git post-commit hook with:
  make hook-install
"""

import json
import os
import sys
from pathlib import Path

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass  # stdlib, always present


# ── Config ─────────────────────────────────────────────────────────────────────

_script_dir = Path(__file__).resolve().parent
REPO_ROOT = _script_dir.parent.parent

API_URL = os.environ.get("API_URL", "http://127.0.0.1:1338").rstrip("/")
EMAIL = os.environ.get("HEARTH_SYNC_EMAIL", "")
PASSWORD = os.environ.get("HEARTH_SYNC_PASSWORD", "")

FEATURE_LIST = REPO_ROOT / "feature_list.json"

# Prefix added to every synced todo title — used to identify managed todos.
TITLE_PREFIX = "[hearth-dev] "

# Map feature priority → Hearth todo priority
PRIORITY_MAP = {1: "high", 2: "medium", 3: "low"}


# ── HTTP helpers ────────────────────────────────────────────────────────────────

def _request(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    url = f"{API_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {body_text}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach Hearth API at {API_URL}: {e.reason}") from e


def login(email: str, password: str) -> str:
    resp = _request("POST", "/auth/login", {"email": email, "password": password})
    return resp["access_token"]


def get_all_todos(token: str) -> list[dict]:
    """Fetch all todos (up to 500) for the authenticated user's household."""
    resp = _request("GET", "/todos?limit=500&offset=0", token=token)
    return resp.get("items", [])


def create_todo(token: str, payload: dict) -> dict:
    return _request("POST", "/todos", body=payload, token=token)


def update_todo(token: str, todo_id: str, payload: dict) -> dict:
    return _request("PATCH", f"/todos/{todo_id}", body=payload, token=token)


# ── Sync logic ──────────────────────────────────────────────────────────────────

def feature_to_todo(feature: dict) -> dict:
    """Build a TodoCreate/TodoUpdate payload from a feature_list entry."""
    steps_md = ""
    if feature.get("steps"):
        steps_md = "\n\nVerification steps:\n" + "\n".join(
            f"  {i+1}. {s}" for i, s in enumerate(feature["steps"])
        )
    description = (feature.get("description") or "") + steps_md

    priority = PRIORITY_MAP.get(feature.get("priority", 2), "medium")
    status = "done" if feature.get("passes") else "pending"

    return {
        "title": TITLE_PREFIX + f"[{feature['id']}] {feature['title']}",
        "description": description,
        "priority": priority,
        "status": status,
        "visibility": "household",
    }


def sync(email: str, password: str) -> None:
    if not email or not password:
        print(
            "✗ Missing credentials.\n"
            "  Set HEARTH_SYNC_EMAIL and HEARTH_SYNC_PASSWORD in infra/local.env\n"
            "  (and re-source it before running this script).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not FEATURE_LIST.exists():
        print(f"✗ {FEATURE_LIST} not found.", file=sys.stderr)
        sys.exit(1)

    features = json.loads(FEATURE_LIST.read_text()).get("features", [])

    print(f"→ Authenticating as {email} …")
    token = login(email, password)

    print("→ Fetching existing todos …")
    existing = get_all_todos(token)

    # Build a lookup: managed title → existing todo
    managed: dict[str, dict] = {
        t["title"]: t
        for t in existing
        if t["title"].startswith(TITLE_PREFIX)
    }

    created = updated = skipped = 0

    for feature in features:
        payload = feature_to_todo(feature)
        title = payload["title"]
        existing_todo = managed.get(title)

        if existing_todo is None:
            create_todo(token, payload)
            marker = "✓" if feature.get("passes") else "○"
            print(f"  + {marker} Created  {title}")
            created += 1
        else:
            # Only update if status or priority actually changed
            changed = (
                existing_todo.get("status") != payload["status"]
                or existing_todo.get("priority") != payload["priority"]
                or existing_todo.get("description") != payload["description"]
            )
            if changed:
                update_todo(token, str(existing_todo["id"]), payload)
                marker = "✓" if feature.get("passes") else "○"
                print(f"  ~ {marker} Updated  {title}")
                updated += 1
            else:
                skipped += 1

    # Report any managed todos that no longer have a matching feature
    feature_titles = {feature_to_todo(f)["title"] for f in features}
    orphans = [t for title, t in managed.items() if title not in feature_titles]
    for orphan in orphans:
        print(f"  ? Orphan  {orphan['title']}  (feature removed from list — not touching it)")

    total = len(features)
    done = sum(1 for f in features if f.get("passes"))
    print(
        f"\n✅ Sync complete — {total} features ({done} done, {total - done} pending)\n"
        f"   {created} created  ·  {updated} updated  ·  {skipped} unchanged"
    )


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sync(EMAIL, PASSWORD)
