"""
Seed script: rebuild M1 sub-projects with a revised roadmap.

What this does:
  1. Finds the M1 sub-project under the top-level "Hearth App" project.
  2. Deletes all existing todos directly under M1.
  3. Creates sub-projects under M1 (idempotent — skips existing by name).
  4. Seeds todos under each sub-project (idempotent — skips existing by title).

Usage (from repo root):
    make seed-m1-subprojects

Or directly:
    cd api && .venv/bin/python3.12 scripts/seed_m1_subprojects.py
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


# ── Sub-project definitions ───────────────────────────────────────────────────

M1_SUBPROJECTS = [
    {
        "name": "Postgres Setup",
        "description": "Install and configure native Postgres on the user's machine without Docker. Invisible to the user.",
        "status": "active",
        "sort_order": 1,
        "todos": [
            "Download and install Postgres.app programmatically on macOS",
            "Start Postgres service and verify it is running",
            "Create life_dashboard database if it does not exist",
            "Run Alembic migrations automatically on every app start",
            "Linux: apt/dnf install path with clear sudo prompt explanation",
            "Test Postgres setup on clean macOS machine",
            "Test Postgres setup on clean Ubuntu machine",
        ],
    },
    {
        "name": "Process Management",
        "description": "Keep the API and web processes alive and launch them at login — no terminal required after install.",
        "status": "active",
        "sort_order": 2,
        "todos": [
            "macOS: write launchd plist for the FastAPI process",
            "macOS: write launchd plist for the Next.js process",
            "macOS: register and load both plists from the install script",
            "Linux: write systemd unit for the FastAPI process",
            "Linux: write systemd unit for the Next.js process",
            "Linux: enable both units from the install script",
            "Verify both processes restart automatically after a reboot",
            "Provide a stop/start/restart mechanism the user can trigger (menu bar or CLI)",
        ],
    },
    {
        "name": "Code Signing & Notarization",
        "description": "macOS distribution prerequisite — sign and notarize the installer so users don't see the unidentified developer warning.",
        "status": "backlog",
        "sort_order": 3,
        "todos": [
            "Obtain Apple Developer account ($99/yr)",
            "Generate Developer ID Application certificate",
            "Sign the install script / app bundle with codesign",
            "Submit to Apple notarization service via notarytool",
            "Staple the notarization ticket to the installer",
            "Test the signed installer on a clean Mac with Gatekeeper enabled",
        ],
    },
    {
        "name": "First-Run Setup Wizard",
        "description": "Replace the raw bootstrap password flow with a guided UI that walks new users through initial configuration.",
        "status": "active",
        "sort_order": 4,
        "todos": [
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
        ],
    },
    {
        "name": "Install Script",
        "description": "A single install.sh that chains Postgres setup, dependency install, process registration, and first-run launch.",
        "status": "backlog",
        "sort_order": 5,
        "todos": [
            "macOS: check for Python 3.12 and Node prerequisites; prompt to install if missing",
            "macOS: chain Postgres.app install, DB creation, and migration steps",
            "macOS: install Python deps (venv) and Node deps",
            "macOS: register launchd agents and open the app in the browser",
            "Linux: equivalent apt-based install chain",
            "Make install.sh idempotent (safe to re-run on existing installs)",
            "Test full install on clean macOS",
            "Test full install on clean Ubuntu",
        ],
    },
    {
        "name": "Documentation",
        "description": "End-to-end install guide and updated README for the local install path.",
        "status": "backlog",
        "sort_order": 6,
        "todos": [
            "Write docs/install-local.md (prerequisites, install command, first-run walkthrough)",
            "Document how to start, stop, and restart the app after install",
            "Document how to back up the Postgres data directory",
            "Document how to update to a new version",
            "Update root README.md to link to install-local.md prominently",
        ],
    },
]


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:

        # ── 1. Find top-level Hearth App project ──────────────────────
        result = await db.execute(
            sa.text(
                "SELECT id, household_id, created_by_user_id "
                "FROM projects "
                "WHERE name ILIKE '%Hearth%' AND parent_id IS NULL "
                "ORDER BY created_at LIMIT 1"
            )
        )
        root = result.fetchone()
        if root is None:
            print("ERROR: Could not find top-level 'Hearth App' project.")
            return
        root_id, household_id, user_id = root
        print(f"Found root project: {root_id}")

        # ── 2. Find the M1 sub-project ────────────────────────────────────────
        result = await db.execute(
            sa.text(
                "SELECT id FROM projects "
                "WHERE household_id = :hid AND parent_id = :pid AND name ILIKE '%M1%' "
                "ORDER BY created_at LIMIT 1"
            ),
            {"hid": str(household_id), "pid": str(root_id)},
        )
        m1_row = result.fetchone()
        if m1_row is None:
            print("ERROR: Could not find M1 sub-project under the root project.")
            return
        m1_id = m1_row[0]
        print(f"Found M1 project: {m1_id}")

        # ── 3. Delete all existing todos directly under M1 ────────────────────
        deleted = await db.execute(
            sa.text("DELETE FROM todos WHERE project_id = :pid RETURNING id"),
            {"pid": str(m1_id)},
        )
        print(f"Deleted {len(deleted.fetchall())} existing M1 todos")

        # ── 4. Create sub-projects and their todos ────────────────────────────
        for sp in M1_SUBPROJECTS:
            # Check if sub-project already exists
            exists = await db.execute(
                sa.text(
                    "SELECT id FROM projects "
                    "WHERE household_id = :hid AND parent_id = :pid AND name = :name "
                    "LIMIT 1"
                ),
                {"hid": str(household_id), "pid": str(m1_id), "name": sp["name"]},
            )
            existing = exists.fetchone()

            if existing:
                sub_id = existing[0]
                print(f"  SKIP (exists): {sp['name']}")
            else:
                sub_id = uuid.uuid4()
                await db.execute(
                    sa.text(
                        """
                        INSERT INTO projects
                            (id, household_id, created_by_user_id, parent_id,
                             name, description, status, show_in_nav, sort_order)
                        VALUES
                            (:id, :household_id, :user_id, :parent_id,
                             :name, :description, :status, false, :sort_order)
                        """
                    ),
                    {
                        "id": str(sub_id),
                        "household_id": str(household_id),
                        "user_id": str(user_id) if user_id else None,
                        "parent_id": str(m1_id),
                        "name": sp["name"],
                        "description": sp["description"],
                        "status": sp["status"],
                        "sort_order": sp["sort_order"],
                    },
                )
                print(f"  CREATED: {sp['name']}")

            # Seed todos
            for title in sp["todos"]:
                todo_exists = await db.execute(
                    sa.text(
                        "SELECT id FROM todos "
                        "WHERE household_id = :hid AND project_id = :pid AND title = :title "
                        "LIMIT 1"
                    ),
                    {"hid": str(household_id), "pid": str(sub_id), "title": title},
                )
                if todo_exists.fetchone():
                    print(f"    SKIP todo (exists): {title[:70]}")
                else:
                    await db.execute(
                        sa.text(
                            """
                            INSERT INTO todos
                                (id, household_id, created_by_user_id, project_id,
                                 title, status)
                            VALUES
                                (:id, :household_id, :user_id, :project_id,
                                 :title, 'pending')
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "household_id": str(household_id),
                            "user_id": str(user_id) if user_id else None,
                            "project_id": str(sub_id),
                            "title": title,
                        },
                    )
                    print(f"    + todo: {title[:70]}")

        await db.commit()
        print("\nDone.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
