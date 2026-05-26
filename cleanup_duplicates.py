#!/usr/bin/env python3
"""
cleanup_duplicates.py — Remove duplicate seed data from Hearth.

Deduplication keys per domain:
  Tags              → name
  Collections       → name
  Notes             → title
  Workouts          → name + workout_date
  Habits            → name
  Grocery lists     → name
  Goals             → title
  Budget profiles   → name
  Budget accounts   → name
  Budget txns       → account_id + date + description + amount
  Projects          → name + parent_id
  Todos             → title + project_id
  Calendar events   → title + starts_at (truncated to minute)
  Documents         → title

Usage:
  python cleanup_duplicates.py [--host http://localhost:1338] \
                               [--email test@hearth.local] \
                               [--password password] \
                               [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.parse import urlencode

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Clean up Hearth duplicate seed data")
parser.add_argument("--host", default="http://localhost:1338")
parser.add_argument("--email", default="test@hearth.local")
parser.add_argument("--password", default="password")
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Print what would be deleted without actually deleting anything",
)
args = parser.parse_args()

BASE    = args.host.rstrip("/")
DRY_RUN = args.dry_run

_headers: dict[str, str] = {"Content-Type": "application/json"}

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _request(
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
) -> tuple[int, dict | list]:
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
        body_text = e.read().decode()[:300]
        return e.code, {"_error": body_text}


def login(email: str, password: str) -> str:
    status, data = _request("POST", "/auth/login", {"email": email, "password": password})
    if status != 200:
        print(f"❌  Login failed: {status} {data}")
        sys.exit(1)
    print(f"✅  Logged in as {email}")
    return data["access_token"]  # type: ignore[index]


def get_all(path: str, extra_params: dict | None = None) -> list[dict]:
    """Fetch all pages from a paginated endpoint (items/total/limit/offset shape)."""
    items: list[dict] = []
    offset = 0
    limit  = 500
    while True:
        params = {"limit": limit, "offset": offset, **(extra_params or {})}
        status, data = _request("GET", path, params=params)
        if status != 200:
            print(f"  ⚠️  GET {path} → {status}: {data}")
            return items
        if isinstance(data, list):
            return data  # non-paginated endpoint
        page = data.get("items") or []
        items.extend(page)
        total = data.get("total", len(items))
        offset += limit
        if offset >= total:
            break
    return items


def delete(path: str, item_id: str, label: str) -> bool:
    if DRY_RUN:
        print(f"  🔍  [dry-run] would delete {label} ({item_id})")
        return True
    status, _ = _request("DELETE", path)
    if status in (200, 204):
        print(f"  🗑️   deleted {label}")
        return True
    else:
        print(f"  ⚠️  DELETE {path} → {status}")
        return False


# ── Dedup helpers ─────────────────────────────────────────────────────────────

def dedup(
    items: list[dict],
    key_fn,
    delete_path_fn,
    label_fn,
    keep: str = "first",
) -> tuple[int, int]:
    """
    Group items by key_fn. For any group with >1 member, keep one and delete
    the rest.

    keep="first"  → keep the first item in each group (oldest by list order,
                    which is typically creation order from the API)
    keep="last"   → keep the last item

    Returns (kept, deleted) counts.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        k = key_fn(item)
        if k is not None:
            groups[k].append(item)

    kept = 0
    deleted = 0
    for key, group in groups.items():
        if len(group) <= 1:
            kept += 1
            continue
        # Sort by created_at if available so "first" means truly oldest
        def sort_key(i: dict) -> str:
            return i.get("created_at") or i.get("date") or i.get("workout_date") or ""
        group.sort(key=sort_key)
        to_keep   = group[0] if keep == "first" else group[-1]
        to_delete = [i for i in group if i["id"] != to_keep["id"]]
        kept += 1
        for item in to_delete:
            path  = delete_path_fn(item)
            label = label_fn(item)
            if delete(path, item["id"], label):
                deleted += 1
    return kept, deleted


# ── Main ──────────────────────────────────────────────────────────────────────

token = login(args.email, args.password)
_headers["Authorization"] = f"Bearer {token}"

if DRY_RUN:
    print("⚠️  DRY RUN — nothing will actually be deleted\n")

total_deleted = 0


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Tags ──────────────────────────────────────────────────────────────────────
section("Tags")
tags = get_all("/tags")
print(f"  Found {len(tags)} tags")
k, d = dedup(
    tags,
    key_fn=lambda t: t["name"].lower(),
    delete_path_fn=lambda t: f"/tags/{t['id']}",
    label_fn=lambda t: f"tag '{t['name']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Collections ───────────────────────────────────────────────────────────────
section("Collections")
collections = get_all("/collections")
print(f"  Found {len(collections)} collections")
k, d = dedup(
    collections,
    key_fn=lambda c: c["name"].lower(),
    delete_path_fn=lambda c: f"/collections/{c['id']}",
    label_fn=lambda c: f"collection '{c['name']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Notes (including journal entries) ────────────────────────────────────────
section("Notes")
notes = get_all("/notes", {"include_all_collections": "true"})
print(f"  Found {len(notes)} notes")
k, d = dedup(
    notes,
    key_fn=lambda n: n["title"].strip().lower(),
    delete_path_fn=lambda n: f"/notes/{n['id']}",
    label_fn=lambda n: f"note '{n['title']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Workouts ──────────────────────────────────────────────────────────────────
section("Workouts")
workouts = get_all("/workouts")
print(f"  Found {len(workouts)} workouts")
k, d = dedup(
    workouts,
    key_fn=lambda w: f"{w['name'].lower()}|{w.get('workout_date', '')}",
    delete_path_fn=lambda w: f"/workouts/{w['id']}",
    label_fn=lambda w: f"workout '{w['name']}' on {w.get('workout_date', '?')}",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Habits ────────────────────────────────────────────────────────────────────
section("Habits")
habits = get_all("/habits")
print(f"  Found {len(habits)} habits")
k, d = dedup(
    habits,
    key_fn=lambda h: h["name"].lower(),
    delete_path_fn=lambda h: f"/habits/{h['id']}",
    label_fn=lambda h: f"habit '{h['name']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Grocery lists ─────────────────────────────────────────────────────────────
section("Grocery lists")
grocery_lists = get_all("/grocery-lists")
print(f"  Found {len(grocery_lists)} grocery lists")
k, d = dedup(
    grocery_lists,
    key_fn=lambda g: g["name"].lower(),
    delete_path_fn=lambda g: f"/grocery-lists/{g['id']}",
    label_fn=lambda g: f"grocery list '{g['name']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Goals ─────────────────────────────────────────────────────────────────────
section("Goals")
goals = get_all("/goals")
print(f"  Found {len(goals)} goals")
k, d = dedup(
    goals,
    key_fn=lambda g: g["title"].strip().lower(),
    delete_path_fn=lambda g: f"/goals/{g['id']}",
    label_fn=lambda g: f"goal '{g['title']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Budget profiles ───────────────────────────────────────────────────────────
section("Budget profiles")
profiles = get_all("/budget/profiles")
# profiles endpoint may return a plain list
if isinstance(profiles, dict):
    profiles = profiles.get("items") or []
print(f"  Found {len(profiles)} budget profiles")
k, d = dedup(
    profiles,
    key_fn=lambda p: p["name"].lower(),
    delete_path_fn=lambda p: f"/budget/profiles/{p['id']}",
    label_fn=lambda p: f"budget profile '{p['name']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Budget accounts ───────────────────────────────────────────────────────────
section("Budget accounts")
accounts = get_all("/budget/accounts")
if isinstance(accounts, dict):
    accounts = accounts.get("items") or []
print(f"  Found {len(accounts)} budget accounts")
k, d = dedup(
    accounts,
    key_fn=lambda a: a["name"].lower(),
    delete_path_fn=lambda a: f"/budget/accounts/{a['id']}",
    label_fn=lambda a: f"account '{a['name']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Budget transactions ───────────────────────────────────────────────────────
# Dedup key: account_id + date + description + amount (rounded to cents).
# Transactions that share all four are almost certainly from re-running the seed.
section("Budget transactions")
transactions = get_all("/budget/transactions")
if isinstance(transactions, dict):
    transactions = transactions.get("items") or []
print(f"  Found {len(transactions)} budget transactions")

def txn_key(t: dict) -> str:
    amount = round(float(t.get("amount", 0)), 2)
    return f"{t.get('account_id', '')}|{t.get('date', '')}|{t.get('description', '').strip().lower()}|{amount}"

k, d = dedup(
    transactions,
    key_fn=txn_key,
    delete_path_fn=lambda t: f"/budget/transactions/{t['id']}",
    label_fn=lambda t: f"txn '{t.get('description', '')}' on {t.get('date', '?')}",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Projects ──────────────────────────────────────────────────────────────────
# Fetch all projects (roots first, then sub-projects).
# Dedup key: name + parent_id (None for root projects).
section("Projects")
all_projects = get_all("/projects", {"include_archived": "true"})
print(f"  Found {len(all_projects)} projects (including sub-projects)")

def project_key(p: dict) -> str:
    parent = str(p.get("parent_id") or "root")
    return f"{p['name'].strip().lower()}|{parent}"

# Filter out system projects — never touch those
user_projects = [p for p in all_projects if not p.get("is_system")]
k, d = dedup(
    user_projects,
    key_fn=project_key,
    delete_path_fn=lambda p: f"/projects/{p['id']}",
    label_fn=lambda p: f"project '{p['name']}'",
)
print(f"  Kept {k} (+system projects untouched), deleted {d}")
total_deleted += d

# ── Todos ─────────────────────────────────────────────────────────────────────
# After deduping projects the surviving project IDs changed, so refetch.
section("Todos")
todos = get_all("/todos")
print(f"  Found {len(todos)} todos")

def todo_key(t: dict) -> str:
    project = str(t.get("project_id") or "none")
    return f"{t['title'].strip().lower()}|{project}"

k, d = dedup(
    todos,
    key_fn=todo_key,
    delete_path_fn=lambda t: f"/todos/{t['id']}",
    label_fn=lambda t: f"todo '{t['title']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Calendar events ───────────────────────────────────────────────────────────
# Dedup key: title + starts_at truncated to the minute.
# (The seed script creates events at whole-hour boundaries, so minute truncation
# is precise enough and resilient to tiny timestamp differences.)
section("Calendar events")
events = get_all("/events")
print(f"  Found {len(events)} calendar events")

def event_key(e: dict) -> str:
    starts = (e.get("starts_at") or "")[:16]  # "YYYY-MM-DDTHH:MM"
    return f"{e['title'].strip().lower()}|{starts}"

k, d = dedup(
    events,
    key_fn=event_key,
    delete_path_fn=lambda e: f"/events/{e['id']}",
    label_fn=lambda e: f"event '{e['title']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Documents ─────────────────────────────────────────────────────────────────
section("Documents")
documents = get_all("/documents")
print(f"  Found {len(documents)} documents")
k, d = dedup(
    documents,
    key_fn=lambda doc: doc["title"].strip().lower(),
    delete_path_fn=lambda doc: f"/documents/{doc['id']}",
    label_fn=lambda doc: f"document '{doc['title']}'",
)
print(f"  Kept {k}, deleted {d}")
total_deleted += d

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
if DRY_RUN:
    print(f"  DRY RUN complete — would have deleted {total_deleted} duplicate items")
else:
    print(f"  Cleanup complete — deleted {total_deleted} duplicate items")
print(f"{'═'*60}\n")
