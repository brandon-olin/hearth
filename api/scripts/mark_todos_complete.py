"""
Interactive script to mark todos as complete.

Fetches all pending todos (grouped by project), suggests known-completed items
based on what's shipped in the codebase, then lets you confirm which to mark done.

Usage (from api/ directory with venv active):
    python scripts/mark_todos_complete.py

Options:
    --dry-run   Print what would be marked without writing anything
    --yes       Skip confirmation and mark all suggested items automatically
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from life_dashboard.core.settings import settings


# ── Known-completed todo titles ───────────────────────────────────────────────
# These match the seeded titles exactly. Add/remove as needed before running.

KNOWN_COMPLETE: set[str] = {
    # AI project
    "Add create_note and update_note write tools",

    # UX Debt project
    "Shell: focus mode (collapse sidebars, keyboard shortcut ⌘⇧F)",

    # M1 – Stable Local Install
    "Build a first-run setup wizard (replaces raw bootstrap password flow)",
    "Write a one-command install script for macOS and Linux",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"


def fmt(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(dry_run: bool = False, auto_yes: bool = False) -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Fetch all pending todos with project names
        result = await db.execute(
            sa.text(
                """
                SELECT
                    t.id,
                    t.title,
                    COALESCE(p.name, '(no project)') AS project_name,
                    t.created_at
                FROM todos t
                LEFT JOIN projects p ON p.id = t.project_id
                WHERE t.status = 'pending'
                ORDER BY project_name, t.created_at
                """
            )
        )
        rows = result.fetchall()

    if not rows:
        print("No pending todos found.")
        await engine.dispose()
        return

    # Group by project
    by_project: dict[str, list[tuple]] = {}
    for row in rows:
        by_project.setdefault(row.project_name, []).append(row)

    # Print with suggested completions highlighted
    print(f"\n{fmt(BOLD, 'Pending todos')}  ({len(rows)} total)\n")
    print(f"  {fmt(GREEN, '✓')} = suggested complete   {fmt(DIM, '(enter numbers to add/remove)')}\n")

    idx = 1
    row_map: dict[int, tuple] = {}
    suggested: set[int] = set()

    for project, todos in by_project.items():
        print(f"  {fmt(CYAN, project)}")
        for row in todos:
            marker = fmt(GREEN, "✓") if row.title in KNOWN_COMPLETE else " "
            print(f"    {fmt(DIM, str(idx).rjust(3))}  [{marker}]  {row.title}")
            row_map[idx] = row
            if row.title in KNOWN_COMPLETE:
                suggested.add(idx)
            idx += 1
        print()

    if dry_run:
        print(fmt(YELLOW, "Dry run — no changes written.\n"))
        print(f"Would mark {len(suggested)} todo(s) as complete:")
        for n in sorted(suggested):
            print(f"  · {row_map[n].title}")
        await engine.dispose()
        return

    # ── Interactive selection ──────────────────────────────────────────────────
    selected = set(suggested)

    if not auto_yes:
        print("Enter numbers to toggle (space or comma separated), or press Enter to accept suggestions.")
        print(fmt(DIM, "Examples:  '3 7 12'  adds/removes those items   |  'all' selects everything   |  'none' clears all\n"))

        raw = input("Toggle> ").strip().lower()

        if raw == "all":
            selected = set(row_map.keys())
        elif raw == "none":
            selected = set()
        elif raw:
            for token in raw.replace(",", " ").split():
                try:
                    n = int(token)
                    if n in row_map:
                        if n in selected:
                            selected.discard(n)
                        else:
                            selected.add(n)
                    else:
                        print(fmt(YELLOW, f"  Skipping unknown number: {n}"))
                except ValueError:
                    print(fmt(YELLOW, f"  Skipping non-number token: {token!r}"))

    if not selected:
        print("\nNothing selected — exiting without changes.")
        await engine.dispose()
        return

    # ── Confirm ───────────────────────────────────────────────────────────────
    print(f"\nWill mark {fmt(BOLD, str(len(selected)))} todo(s) as complete:")
    for n in sorted(selected):
        print(f"  {fmt(GREEN, '✓')}  {row_map[n].title}")

    if not auto_yes:
        confirm = input("\nProceed? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            await engine.dispose()
            return

    # ── Write ─────────────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    # IDs come from our own SELECT — safe to inline directly to avoid asyncpg
    # issues with ::uuid[] array casts in named-parameter queries.
    id_list = ", ".join(f"'{row_map[n].id}'" for n in selected)

    async with async_session() as db:
        await db.execute(
            sa.text(
                f"""
                UPDATE todos
                SET status = 'done',
                    completed_at = :now,
                    updated_at = :now
                WHERE id IN ({id_list})
                """
            ),
            {"now": now},
        )
        await db.commit()

    print(fmt(GREEN, f"\n✓ Marked {len(selected)} todo(s) as complete.\n"))
    await engine.dispose()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    auto_yes = "--yes" in sys.argv
    asyncio.run(main(dry_run=dry_run, auto_yes=auto_yes))
