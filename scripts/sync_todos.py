#!/usr/bin/env python3
"""
sync_todos.py — Seed Hearth with development projects and todos.

Creates two projects:
  - Hearth — Feature Backlog   (non-AI work)
  - Hearth — AI Coach          (coach redesign work)

Idempotent: finds existing todos globally by title, moves them into the
correct project if needed, and updates status if changed.

Usage:
    python ../scripts/sync_todos.py
"""

import argparse
import getpass
import json
import sys
import urllib.request
import urllib.parse
import urllib.error


# ── Feature definitions ────────────────────────────────────────────────────────

BACKLOG_TODOS = [
    # Calendar
    {
        "title": "[hearth-dev] [calendar-001] Show todo due dates on calendar",
        "description": "Show todos with due dates as chips on the calendar page (month, week, day views). Click to open the todo sheet.",
        "status": "done",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [calendar-002] Show scheduled habits on calendar",
        "description": "Show habit occurrences as chips on the calendar page. Purely client-side scheduling using cadence data.",
        "status": "done",
        "priority": "high",
    },
    # Budget
    {
        "title": "[hearth-dev] [budget-016] Goal financial linking — spending_cap syncs with budget category",
        "description": "UI in goal-sheet.tsx to link a goal to a budget category spending cap. Saves financial_link JSON, backend syncs monthly_limit to BudgetCategory.default_monthly_amount.",
        "status": "done",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [budget-017] Account balance field",
        "description": "Manually-maintained current_balance on budget accounts. Balance chip below account selector; click to edit inline.",
        "status": "done",
        "priority": "medium",
    },
    {
        "title": "[hearth-dev] [budget-018] Teller bank linking — connect real bank accounts",
        "description": "APScheduler job in main.py (every 4 hours) calls sync_all_teller_accounts_globally() which iterates all households with Teller-linked accounts and syncs each.",
        "status": "pending",
        "priority": "medium",
    },
    # Notifications
    {
        "title": "[hearth-dev] [notifications-001] Notification center UI",
        "description": "Bell icon in header with unread count badge, dropdown panel, per-item mark-read, mark-all-read. Polls unread count every 30s.",
        "status": "done",
        "priority": "medium",
    },
    # Search
    {
        "title": "[hearth-dev] [search-001] Global full-text search across all domains",
        "description": "Command palette searches documents, todos, goals, habits with debouncing and load-more pagination.",
        "status": "done",
        "priority": "medium",
    },
    # Goals
    {
        "title": "[hearth-dev] [goals-001] Link goals to projects",
        "description": "Add a Linked project field in the goal sheet. When linked, goal progress bar derives from the project completion percentage.",
        "status": "pending",
        "priority": "medium",
    },
    # Household
    {
        "title": "[hearth-dev] [household-001] Email-based household invitations",
        "description": "Admin invites by email. Invitee receives link, completes signup pre-scoped to the household, appears in member list.",
        "status": "pending",
        "priority": "medium",
    },
    # Dashboard
    {
        "title": "[hearth-dev] [dashboard-001] Notes widget on dashboard",
        "description": "Quick-editable sticky note widget. Content persists per-widget instance. Useful for household reminders visible at a glance.",
        "status": "pending",
        "priority": "medium",
    },
    # Settings
    {
        "title": "[hearth-dev] [settings-001] Full data export (household backup)",
        "description": "Export my data button in Settings downloads a ZIP with all household data as JSON plus uploaded files.",
        "status": "pending",
        "priority": "low",
    },
    {
        "title": "[hearth-dev] [settings-002] Notification preferences in settings",
        "description": "Settings Notifications page. Toggle which notification types to receive per member.",
        "status": "pending",
        "priority": "low",
    },
    # Workouts
    {
        "title": "[hearth-dev] [workouts-001] Workout templates",
        "description": "Save a workout as a template. When logging a new workout, pick a template to pre-fill the exercise list.",
        "status": "pending",
        "priority": "low",
    },
    # UX Polish
    {
        "title": "[hearth-dev] [ux-001] Empty state illustrations for all domain pages",
        "description": "Every domain list page shows a friendly empty state with short message and call-to-action when the list is empty.",
        "status": "pending",
        "priority": "low",
    },
    {
        "title": "[hearth-dev] [ux-002] Keyboard shortcuts for common actions",
        "description": "N = new item on current domain page. ? = shortcuts help modal. Escape closes any open sheet.",
        "status": "pending",
        "priority": "low",
    },
]

AI_COACH_TODOS = [
    {
        "title": "[hearth-dev] [coach-001] User profile + bootstrap pass (Phase 1 of AI coach redesign)",
        "description": "Persistent per-user markdown profile. last_bootstrapped_at on member_ai_memory. user_profile_updates table. POST /ai/profile/bootstrap. Profile subsection in Settings AI.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [coach-001b] Notes-driven incremental profile proposer (Phase 1.5 of AI coach redesign)",
        "description": "After every N net-new notes (default 5), run proposer on last 15 notes. notes_at_last_proposal counter. Skips until bootstrap has run once.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [coach-002] Journal signal extraction (Phase 2 of AI coach redesign)",
        "description": "Per-entry signal extraction: sentiment, self_talk_valence, themes, energy_level. journal_signals table. Opt-out flag on ai_settings. Backfill endpoint.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [coach-003] CBT-aware coach prompt rewrite (Phase 3 of AI coach redesign)",
        "description": "Rewrite prompts to reason across profile + narrative signals + raw journal. _fetch_narrative_context helper. Reality-tests harsh self-talk against data.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [chat-001] Context-aware chatbot — read the currently open resource",
        "description": "Optional context type+id on ChatRequest. Server resolves to a What the user is currently viewing block. CurrentResourceProvider in layout. Discussing chip in sidebar.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [coach-005] Silent profile + auto-bootstrap on API key save + key validation",
        "description": "ProfileSubSection removed. Bootstrap writes directly to memory_text. AIProvider.validate() probe. Auto-bootstrap fires on successful new-key save if profile is empty.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [coach-006] Chat-driven profile updates via update_profile tool + coach widget combobox",
        "description": "update_profile chat tool rewrites memory_text on durable user statements. PinnedSection switches to searchable combobox above 8 items.",
        "status": "pending",
        "priority": "high",
    },
    {
        "title": "[hearth-dev] [coach-004] Coach widget free-text focus field",
        "description": "1-2 sentence free-text guidance per coach widget. Persisted in AiCoachWidgetConfig.focus. Threaded to digest as What I want you to focus on right now section.",
        "status": "pending",
        "priority": "medium",
    },
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

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


def api_get(base_url, token, path, params=None):
    url = f"{base_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_post(base_url, token, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_patch(base_url, token, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ── Logic ──────────────────────────────────────────────────────────────────────

def get_all_projects(base_url, token):
    """Returns {name: project_dict} for all projects."""
    data = api_get(base_url, token, "/projects", {"limit": 100})
    items = data.get("items", data) if isinstance(data, dict) else data
    return {p["name"]: p for p in items}


def get_or_create_project(base_url, token, name, description, all_projects, parent_id=None):
    if name in all_projects:
        p = all_projects[name]
        pid = str(p["id"])
        current_parent = str(p["parent_id"]) if p.get("parent_id") else ""
        expected_parent = str(parent_id) if parent_id else ""
        if current_parent != expected_parent:
            body = {"parent_id": parent_id}
            api_patch(base_url, token, "/projects/{}".format(pid), body)
            print("  moved under parent: {}".format(name))
        else:
            print("  exists: {}".format(name))
        return pid
    proj = api_post(base_url, token, "/projects", {
        "name": name,
        "description": description,
        "status": "active",
        "show_in_nav": False,
        "parent_id": parent_id,
        "visibility": "personal",
    })
    print("  + created: {}".format(name))
    return str(proj["id"])


def get_all_todos(base_url, token):
    """Returns {title: (todo_id, status, project_id)} for ALL todos globally."""
    result = {}
    offset = 0
    while True:
        data = api_get(base_url, token, "/todos", {"limit": 200, "offset": offset})
        items = data.get("items", [])
        for t in items:
            pid = str(t["project_id"]) if t.get("project_id") else ""
            result[t["title"]] = (str(t["id"]), t["status"], pid)
        total = data.get("total", 0)
        offset += len(items)
        if offset >= total or not items:
            break
    return result


def sync_todos(base_url, token, project_id, todos, all_existing):
    created = updated = skipped = 0
    for t in todos:
        title = t["title"]
        target_status = t.get("status", "pending")
        if title in all_existing:
            todo_id, current_status, current_project_id = all_existing[title]
            patch_body = {}
            if current_status != target_status:
                patch_body["status"] = target_status
            if current_project_id != project_id:
                patch_body["project_id"] = project_id
            if patch_body:
                api_patch(base_url, token, "/todos/{}".format(todo_id), patch_body)
                changes = []
                if "status" in patch_body:
                    changes.append("status->{}".format(target_status))
                if "project_id" in patch_body:
                    changes.append("moved to project")
                icon = "v" if target_status == "done" else "."
                print("    {} ({}) {}".format(icon, ", ".join(changes), title[:70]))
                updated += 1
            else:
                skipped += 1
            continue
        body = {
            "title": title,
            "description": t.get("description"),
            "status": target_status,
            "priority": t.get("priority"),
            "project_id": project_id,
            "visibility": "personal",
        }
        api_post(base_url, token, "/todos", body)
        icon = "v" if target_status == "done" else "."
        print("    {} (new) {}".format(icon, title[:70]))
        created += 1
    print("  -> {} created, {} updated, {} unchanged".format(created, updated, skipped))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed Hearth dev todos")
    parser.add_argument("--base-url", default="http://localhost:1338")
    parser.add_argument("--email", default="")
    args = parser.parse_args()

    email = args.email or input("Email: ").strip()
    password = getpass.getpass("Password: ")

    print("\nLogging in to {}...".format(args.base_url))
    token = login(args.base_url, email, password)
    print("  authenticated\n")

    print("Projects:")
    all_projects = get_all_projects(args.base_url, token)

    if "Hearth App" not in all_projects:
        print("ERROR: 'Hearth App' project not found. Create it in the app first.")
        sys.exit(1)
    hearth_app_id = str(all_projects["Hearth App"]["id"])
    print("  parent: Hearth App ({})".format(hearth_app_id))

    backlog_id = get_or_create_project(
        args.base_url, token,
        "Hearth — Feature Backlog",
        "Non-AI feature work: budget, calendar, goals, household, UX polish, etc.",
        all_projects,
        parent_id=hearth_app_id,
    )
    coach_id = get_or_create_project(
        args.base_url, token,
        "Hearth — AI Coach",
        "AI coach redesign: profile bootstrap, journal signals, CBT prompts, chat context.",
        all_projects,
        parent_id=hearth_app_id,
    )

    print("\nFetching all existing todos...")
    all_existing = get_all_todos(args.base_url, token)
    print("  {} todos found globally".format(len(all_existing)))

    print("\nFeature Backlog todos:")
    sync_todos(args.base_url, token, backlog_id, BACKLOG_TODOS, all_existing)

    print("\nAI Coach todos:")
    sync_todos(args.base_url, token, coach_id, AI_COACH_TODOS, all_existing)

    print("\nDone.")


if __name__ == "__main__":
    main()
