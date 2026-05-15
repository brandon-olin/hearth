"""
Update M1 roadmap progress in the live life_dashboard database.

What this does:
  1. Marks all First-Run Setup Wizard todos as completed (all shipped).
  2. Adds missing future-work todos to the First-Run Setup Wizard sub-project
     (invited-user wizard, email opt-in verification).
  3. Creates a new "User Invitations" sub-project under M1 with its full
     todo list (invitation flow, email templates, acceptance wizard, owner UI).

Idempotent — safe to run more than once.  Existing completed statuses and
existing todo titles are never touched.

Usage (from repo root):
    make update-m1-progress

Or directly:
    cd api && .venv/bin/python3.12 scripts/update_m1_progress.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from life_dashboard.core.settings import settings


# ── Todos to mark completed in "First-Run Setup Wizard" ──────────────────────

WIZARD_COMPLETED = [
    "Add setup_complete flag (settings table or env file) checked on app boot",
    "Redirect to /setup when setup is not complete",
    "Build /setup route with multi-step form (Next.js)",
    "Step 1: Create admin account (name, email, password)",
    "Step 2: Name the household",
    "Step 3: Choose light / dark / system theme",
    "Step 4: Configure sidebar nav (choose which sections to show by default)",
    "Step 5: Confirmation screen with 'Open the app' CTA",
    "Wire POST /setup API endpoint to initialise household and first user",
    "Mark setup complete and invalidate bootstrap flow after wizard finishes",
    "Ensure wizard never re-appears after completion",
]

# ── New todos to append to "First-Run Setup Wizard" ───────────────────────────
# These capture the invited-user variant and email verification work.

WIZARD_NEW_TODOS = [
    "Invited-user wizard: shortened setup flow (name, email, password, theme, sidebar — no household step)",
    "Email double opt-in: send verification code on initial account creation",
    "Email double opt-in: send verification code when accepting a household invitation",
    "Setup wizard: require verified email code before completing account creation",
    "Invited-user wizard: pre-fill email from invitation token so it cannot be changed",
]

# ── New sub-project: User Invitations ─────────────────────────────────────────

INVITATIONS_SUBPROJECT = {
    "name": "User Invitations",
    "description": (
        "Allow household owners to invite additional members by email. "
        "Covers the invitation data model, API endpoints, email delivery, "
        "the acceptance flow, and owner-facing management UI."
    ),
    "status": "backlog",
    "sort_order": 7,
    "todos": [
        "Design invitations table (id, household_id, invited_email, token_hash, role, expires_at, accepted_at)",
        "Alembic migration: add invitations table",
        "API: POST /households/{id}/invitations — generate token, store hashed, send invite email",
        "API: GET /invitations/{token} — validate token and return household name + inviter display name",
        "API: POST /invitations/{token}/accept — create account via shortened wizard and join household",
        "API: DELETE /invitations/{token} — household owner can revoke a pending invitation",
        "Email template: household invitation (inviter name, household name, accept link, 48h expiry note)",
        "Email template: email verification code (6-digit OTP, 15-minute expiry)",
        "Frontend: /invitations/[token] acceptance page using shortened setup wizard",
        "Frontend: Settings > Members — list pending invitations with revoke button",
        "Frontend: Settings > Members — 'Invite someone' button opens email input modal",
        "Invitation expiry: reject tokens older than 48 hours with a clear error message",
        "Prevent duplicate invitations to the same email for the same household",
        "Handle case where invited email already has an account (join without re-registering)",
    ],
}


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:

        # ── Find root → M1 ───────────────────────────────────────────────────
        root_row = (await db.execute(sa.text(
            "SELECT id, household_id, created_by_user_id FROM projects "
            "WHERE name ILIKE '%Hearth%' AND parent_id IS NULL "
            "ORDER BY created_at LIMIT 1"
        ))).fetchone()
        if root_row is None:
            print("ERROR: 'Hearth App' root project not found.")
            return
        root_id, household_id, user_id = root_row
        print(f"Root project : {root_id}")

        m1_row = (await db.execute(sa.text(
            "SELECT id FROM projects "
            "WHERE household_id = :hid AND parent_id = :pid AND name ILIKE '%M1%' "
            "ORDER BY created_at LIMIT 1"
        ), {"hid": str(household_id), "pid": str(root_id)})).fetchone()
        if m1_row is None:
            print("ERROR: M1 sub-project not found.")
            return
        m1_id = m1_row[0]
        print(f"M1 project   : {m1_id}\n")

        # ── Find "First-Run Setup Wizard" sub-project ─────────────────────────
        wizard_row = (await db.execute(sa.text(
            "SELECT id FROM projects "
            "WHERE household_id = :hid AND parent_id = :m1id "
            "  AND name ILIKE '%Setup Wizard%' "
            "ORDER BY created_at LIMIT 1"
        ), {"hid": str(household_id), "m1id": str(m1_id)})).fetchone()
        if wizard_row is None:
            print("ERROR: 'First-Run Setup Wizard' sub-project not found.")
            return
        wizard_id = wizard_row[0]
        print(f"Wizard project: {wizard_id}")

        # ── 1. Mark wizard todos completed ────────────────────────────────────
        print("\n── Marking wizard todos completed ──")
        for title in WIZARD_COMPLETED:
            row = (await db.execute(sa.text(
                "SELECT id, status FROM todos "
                "WHERE project_id = :pid AND title = :title LIMIT 1"
            ), {"pid": str(wizard_id), "title": title})).fetchone()
            if row is None:
                print(f"  NOT FOUND : {title[:80]}")
            elif row[1] == "done":
                print(f"  already ✓ : {title[:80]}")
            else:
                await db.execute(sa.text(
                    "UPDATE todos SET status = 'done' WHERE id = :id"
                ), {"id": str(row[0])})
                print(f"  ✓ done: {title[:80]}")

        # ── 2. Append new wizard todos ────────────────────────────────────────
        print("\n── Adding new wizard todos ──")
        for title in WIZARD_NEW_TODOS:
            exists = (await db.execute(sa.text(
                "SELECT id FROM todos WHERE project_id = :pid AND title = :title LIMIT 1"
            ), {"pid": str(wizard_id), "title": title})).fetchone()
            if exists:
                print(f"  SKIP (exists): {title[:80]}")
            else:
                await db.execute(sa.text(
                    "INSERT INTO todos (id, household_id, created_by_user_id, project_id, title, status) "
                    "VALUES (:id, :hid, :uid, :pid, :title, 'pending')"
                ), {
                    "id": str(uuid.uuid4()),
                    "hid": str(household_id),
                    "uid": str(user_id) if user_id else None,
                    "pid": str(wizard_id),
                    "title": title,
                })
                print(f"  + added: {title[:80]}")

        # ── 3. Create "User Invitations" sub-project ──────────────────────────
        print("\n── User Invitations sub-project ──")
        sp = INVITATIONS_SUBPROJECT
        existing = (await db.execute(sa.text(
            "SELECT id FROM projects "
            "WHERE household_id = :hid AND parent_id = :pid AND name = :name LIMIT 1"
        ), {"hid": str(household_id), "pid": str(m1_id), "name": sp["name"]})).fetchone()

        if existing:
            inv_id = existing[0]
            print(f"  SKIP (exists): {sp['name']}  ({inv_id})")
        else:
            inv_id = uuid.uuid4()
            await db.execute(sa.text(
                """
                INSERT INTO projects
                    (id, household_id, created_by_user_id, parent_id,
                     name, description, status, show_in_nav, sort_order)
                VALUES
                    (:id, :hid, :uid, :pid,
                     :name, :description, :status, false, :sort_order)
                """
            ), {
                "id": str(inv_id),
                "hid": str(household_id),
                "uid": str(user_id) if user_id else None,
                "pid": str(m1_id),
                "name": sp["name"],
                "description": sp["description"],
                "status": sp["status"],
                "sort_order": sp["sort_order"],
            })
            print(f"  CREATED: {sp['name']}")

        for title in sp["todos"]:
            exists = (await db.execute(sa.text(
                "SELECT id FROM todos WHERE project_id = :pid AND title = :title LIMIT 1"
            ), {"pid": str(inv_id), "title": title})).fetchone()
            if exists:
                print(f"    SKIP (exists): {title[:80]}")
            else:
                await db.execute(sa.text(
                    "INSERT INTO todos (id, household_id, created_by_user_id, project_id, title, status) "
                    "VALUES (:id, :hid, :uid, :pid, :title, 'pending')"
                ), {
                    "id": str(uuid.uuid4()),
                    "hid": str(household_id),
                    "uid": str(user_id) if user_id else None,
                    "pid": str(inv_id),
                    "title": title,
                })
                print(f"    + todo: {title[:80]}")

        await db.commit()
        print("\nDone.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
