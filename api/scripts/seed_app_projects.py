"""
Seed script: build out the Life Dashboard App project hierarchy.

Creates sub-projects M1–M5, AI, and UX Debt under the existing
"Life Dashboard App" top-level project, then adds to-dos to each.

Usage (from api/ directory with venv active):
    python scripts/seed_app_projects.py

The script is idempotent — re-running it skips anything that already exists.
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Make sure the src package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from life_dashboard.core.settings import settings


# ── Project + todo definitions ────────────────────────────────────────────────

SUBPROJECTS = [
    {
        "name": "M1 · Stable Local Install",
        "description": "Make the app installable by anyone on their local machine — no Docker, no external Postgres required.",
        "status": "active",
        "todos": [
            "Replace external Postgres with an embedded/bundled option (SQLite or bundled PG)",
            "Build a first-run setup wizard (replaces raw bootstrap password flow)",
            "Write a one-command install script for macOS and Linux",
            "Document the local install path end-to-end",
        ],
    },
    {
        "name": "M2 · NAS & Self-Hosted Polish",
        "description": "Harden the Docker-based self-hosted path for NAS and home-server installs.",
        "status": "active",
        "todos": [
            "Run Alembic migrations automatically on container startup",
            "Add Docker Compose healthchecks and restart policies",
            "Write Caddy + Tailscale setup documentation",
            "Build backup and restore tooling for the Postgres volume",
            "Test and document upgrade path between versions",
        ],
    },
    {
        "name": "M3 · Feature Complete MVP",
        "description": "The app is genuinely useful day-to-day — all core domains are functional.",
        "status": "backlog",
        "todos": [
            "Build out Calendar: event creation, month/week/day views, recurrence, member assignment",
            "Habits full UI: streak tracking, completion heatmap, frequency config",
            "Todos full UI: filters, due dates, recurrence, completion flow",
            "Goals UI polish: milestones, progress tracking, project linkage",
            "Mobile responsiveness audit across all core pages",
            "Household invite flow: add members, role enforcement in UI",
            "Full-text search across documents and notes",
        ],
    },
    {
        "name": "M4 · Cloud-Ready",
        "description": "Infrastructure that can serve strangers' data safely at scale.",
        "status": "backlog",
        "todos": [
            "Deploy frontend to Vercel",
            "Provision Vercel Postgres and wire DATABASE_URL",
            "Multi-tenant isolation audit (ensure household scoping is airtight)",
            "Proper signup and onboarding flow for new cloud users",
            "Automated database backups on the cloud tier",
            "Environment-aware config (self-hosted vs cloud feature flags)",
        ],
    },
    {
        "name": "M5 · Monetization & Launch",
        "description": "Paid tier infrastructure, pricing, and the public launch moment.",
        "status": "backlog",
        "todos": [
            "Decide and document open-core pricing model",
            "Integrate Stripe (subscriptions + customer portal)",
            "Build pricing page and upgrade/downgrade flows",
            "Gate cloud-tier features behind subscription check",
            "Set up transactional email (welcome, billing receipts, password reset)",
            "Write public launch announcement and landing page copy",
        ],
    },
    {
        "name": "AI",
        "description": "Ongoing AI assistant improvements — not milestone-gated.",
        "status": "active",
        "todos": [
            "Add create_note and update_note write tools",
            "Add create_todo write tool",
            "Scheduled AI summaries (weekly digest, habit nudges)",
            "Audit log for AI-triggered writes shown in chat",
            "Improve tool error messages and retry behaviour",
        ],
    },
    {
        "name": "UX Debt",
        "description": "Rough edges and polish items that don't belong to a specific milestone.",
        "status": "active",
        "todos": [
            "Workouts: exercise summary on workout list cards",
            "Workouts: volume and progress charts (weight over time, weekly volume)",
            "Workouts: exercise name autocomplete from past entries",
            "Workouts: workout templates",
            "Documents: drag-to-reorder pages in the tree",
            "Documents: archive and delete individual pages",
            "Documents/Notes: inline image upload in BlockNote editor",
            "Shell: focus mode (collapse sidebars, keyboard shortcut ⌘⇧F)",
            "Projects: progress ring on project detail page",
        ],
    },
]


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Find the "Life Dashboard App" project
        result = await db.execute(
            sa.text(
                "SELECT id, household_id, created_by_user_id "
                "FROM projects "
                "WHERE name ILIKE '%Life Dashboard%' AND parent_id IS NULL "
                "ORDER BY created_at "
                "LIMIT 1"
            )
        )
        row = result.fetchone()
        if row is None:
            print("ERROR: Could not find a top-level project matching 'Life Dashboard'.")
            print("Please create the 'Life Dashboard App' project in the UI first, then re-run.")
            return

        parent_id, household_id, user_id = row
        print(f"Found parent project: {parent_id}")

        for sp in SUBPROJECTS:
            # Check if a sub-project with this name already exists under the parent
            exists = await db.execute(
                sa.text(
                    "SELECT id FROM projects "
                    "WHERE household_id = :hid AND parent_id = :pid AND name = :name "
                    "LIMIT 1"
                ),
                {"hid": str(household_id), "pid": str(parent_id), "name": sp["name"]},
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
                             :name, :description, :status, false, 0)
                        """
                    ),
                    {
                        "id": str(sub_id),
                        "household_id": str(household_id),
                        "user_id": str(user_id) if user_id else None,
                        "parent_id": str(parent_id),
                        "name": sp["name"],
                        "description": sp["description"],
                        "status": sp["status"],
                    },
                )
                print(f"  CREATED: {sp['name']}")

            # Seed to-dos
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
                    print(f"    SKIP todo (exists): {title[:60]}")
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
                    print(f"    + todo: {title[:60]}")

        await db.commit()
        print("\nDone.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
