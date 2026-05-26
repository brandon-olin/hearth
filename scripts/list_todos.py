#!/usr/bin/env python3
"""
list_todos.py — Read-only: prints all existing projects and their todos.
Paste the output back so we can decide what to keep/create/mark done.

Usage:
    cd api && source .venv/bin/activate
    python ../scripts/list_todos.py
"""

import argparse
import getpass
import json
import sys
import urllib.request
import urllib.parse
import urllib.error


def api_get(base_url, token, path, params=None):
    url = f"{base_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def login(base_url, email, password):
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{base_url}/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        print("Login failed: {} {}".format(e.code, e.read().decode()))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:1338")
    parser.add_argument("--email", default="")
    args = parser.parse_args()

    email = args.email or input("Email: ").strip()
    password = getpass.getpass("Password: ")

    token = login(args.base_url, email, password)

    # Fetch all projects
    projects_data = api_get(args.base_url, token, "/projects", {"limit": 100})
    projects = projects_data.get("items", projects_data) if isinstance(projects_data, dict) else projects_data

    # Fetch all todos (paginate to get everything)
    all_todos = []
    offset = 0
    while True:
        data = api_get(args.base_url, token, "/todos", {"limit": 200, "offset": offset})
        items = data.get("items", [])
        all_todos.extend(items)
        total = data.get("total", 0)
        offset += len(items)
        if offset >= total or not items:
            break

    # Group todos by project_id
    by_project = {}
    for t in all_todos:
        pid = str(t["project_id"]) if t.get("project_id") else None
        by_project.setdefault(pid, []).append(t)

    print("\n" + "=" * 60)
    print("  {} project(s), {} todo(s) total".format(len(projects), len(all_todos)))
    print("=" * 60 + "\n")

    for p in projects:
        pid = str(p["id"])
        todos = by_project.get(pid, [])
        print("PROJECT: {}  [{}]  id={}".format(p["name"], p["status"], pid))
        if not todos:
            print("  (no todos)")
        for t in sorted(todos, key=lambda x: (x["status"] == "done", x.get("priority") or "z", x["title"])):
            icon = "✓" if t["status"] == "done" else "·"
            pri = "[{}]".format(t["priority"]) if t.get("priority") else "     "
            print("  {} {} {}".format(icon, pri, t["title"]))
        print()

    orphans = by_project.get(None, [])
    if orphans:
        print("NO PROJECT ({} todos):".format(len(orphans)))
        for t in sorted(orphans, key=lambda x: x["title"]):
            icon = "✓" if t["status"] == "done" else "·"
            print("  {} {}".format(icon, t["title"]))
        print()


if __name__ == "__main__":
    main()
