#!/usr/bin/env python3
"""
backfill_category_colors.py — Patch missing icon/color on budget categories.

Reads all budget categories for the account and applies icon + color for any
category whose name matches the table below. Existing values are never
overwritten — only fills in gaps.

Usage:
  python backfill_category_colors.py [--host http://localhost:1338] \
                                     [--email test@hearth.local] \
                                     [--password password] \
                                     [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.parse import urlencode

# ── Category defaults ─────────────────────────────────────────────────────────
# Covers both the CATEGORY_DEFAULTS names in service.py and the seed script's
# custom names. Exact case-insensitive match.

DEFAULTS: dict[str, dict] = {
    # Seed script names
    "groceries":               {"icon": "🛒", "color": "#3b82f6"},
    "dining out":              {"icon": "🍽️", "color": "#f97316"},
    "rent / mortgage":         {"icon": "🏠", "color": "#64748b"},
    "utilities":               {"icon": "⚡", "color": "#eab308"},
    "transport":               {"icon": "🚗", "color": "#8b5cf6"},
    "gym & fitness":           {"icon": "🏋️", "color": "#14b8a6"},
    "entertainment":           {"icon": "🎬", "color": "#a855f7"},
    "coffee & drinks":         {"icon": "☕", "color": "#b45309"},
    "salary":                  {"icon": "💼", "color": "#22c55e"},
    "freelance / side income": {"icon": "💡", "color": "#a3e635"},
    "savings transfer":        {"icon": "🏦", "color": "#0ea5e9"},
    "subscriptions":           {"icon": "📱", "color": "#6366f1"},
    "home improvement":        {"icon": "🔨", "color": "#92400e"},
    "medical":                 {"icon": "🏥", "color": "#ef4444"},
    "clothing":                {"icon": "👕", "color": "#ec4899"},
    # service.py CATEGORY_DEFAULTS names (in case anyone used those)
    "income":                  {"icon": "💰", "color": "#22c55e"},
    "housing":                 {"icon": "🏠", "color": "#64748b"},
    "dining":                  {"icon": "🍽️", "color": "#f97316"},
    "transportation":          {"icon": "🚗", "color": "#8b5cf6"},
    "travel":                  {"icon": "✈️", "color": "#14b8a6"},
    "shopping":                {"icon": "🛍️", "color": "#0ea5e9"},
    "healthcare":              {"icon": "🏥", "color": "#ef4444"},
    "insurance":               {"icon": "🛡️", "color": "#f43f5e"},
    "personal care":           {"icon": "💆", "color": "#ec4899"},
    "education":               {"icon": "📚", "color": "#6366f1"},
    "savings":                 {"icon": "📈", "color": "#22c55e"},
    "household":               {"icon": "🛋️", "color": "#b45309"},
    "gifts":                   {"icon": "🎁", "color": "#db2777"},
    "gaming":                  {"icon": "🎮", "color": "#06b6d4"},
    "vices":                   {"icon": "🍷", "color": "#92400e"},
}

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Backfill budget category colors")
parser.add_argument("--host",     default="http://localhost:1338")
parser.add_argument("--email",    default="test@hearth.local")
parser.add_argument("--password", default="password")
parser.add_argument("--dry-run",  action="store_true",
                    help="Show what would change without patching anything")
args = parser.parse_args()

BASE    = args.host.rstrip("/")
DRY_RUN = args.dry_run
_headers: dict[str, str] = {"Content-Type": "application/json"}

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _request(method, path, body=None, params=None):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib_request.Request(url, data=data, headers=_headers, method=method)
    try:
        with urllib_request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except HTTPError as e:
        return e.code, {"_error": e.read().decode()[:300]}

def login(email, password):
    status, data = _request("POST", "/auth/login", {"email": email, "password": password})
    if status != 200:
        print(f"❌  Login failed: {status} {data}")
        sys.exit(1)
    print(f"✅  Logged in as {email}")
    return data["access_token"]

def get_all_categories():
    status, data = _request("GET", "/budget/categories")
    if status != 200:
        print(f"⚠️  GET /budget/categories → {status}: {data}")
        return []
    if isinstance(data, list):
        return data
    return data.get("items") or []

# ── Main ──────────────────────────────────────────────────────────────────────

_headers["Authorization"] = f"Bearer {login(args.email, args.password)}"

if DRY_RUN:
    print("⚠️  DRY RUN — nothing will actually be changed\n")

categories = get_all_categories()
print(f"Found {len(categories)} budget categories\n")

patched = skipped = unrecognized = 0

for cat in categories:
    name  = cat.get("name", "")
    key   = name.strip().lower()
    defs  = DEFAULTS.get(key)

    if not defs:
        print(f"  — '{name}': no defaults defined, skipping")
        unrecognized += 1
        continue

    patch: dict = {}
    if not cat.get("icon")  and defs.get("icon"):
        patch["icon"]  = defs["icon"]
    if not cat.get("color") and defs.get("color"):
        patch["color"] = defs["color"]

    if not patch:
        print(f"  ✓  '{name}': already has icon + color, no change needed")
        skipped += 1
        continue

    if DRY_RUN:
        print(f"  🔍  '{name}': would patch {patch}")
        patched += 1
        continue

    status, result = _request("PATCH", f"/budget/categories/{cat['id']}", patch)
    if status == 200:
        print(f"  🎨  '{name}': patched with {patch}")
        patched += 1
    else:
        print(f"  ⚠️  '{name}': PATCH failed → {status}: {result}")

print(f"\n{'═'*50}")
if DRY_RUN:
    print(f"  DRY RUN — would patch {patched} categories")
else:
    print(f"  Done — patched {patched}, already complete {skipped}, unrecognized {unrecognized}")
print(f"{'═'*50}\n")
