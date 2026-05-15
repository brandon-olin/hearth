"""
Migrate data from local Postgres → SQLite (life_dashboard.db).

Migrates: households, users, household_memberships, projects, todos,
          recipes, recipe_ingredients, recipe_steps.

Run from the api/ directory with the venv active:
    python scripts/migrate_pg_to_sqlite.py

Assumes:
  - Postgres DB named 'life_dashboard' on localhost (default port)
  - SQLite DB at api/life_dashboard.db (already created by app startup)
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import asyncpg

PG_DSN = "postgresql://localhost/life_dashboard"
SQLITE_PATH = Path(__file__).parent.parent / "life_dashboard.db"


def iso(val):
    return val.isoformat() if val is not None else None


def uid(val):
    return str(val) if val is not None else None


async def migrate():
    if not SQLITE_PATH.exists():
        print(f"ERROR: SQLite DB not found at {SQLITE_PATH}")
        print("Start the API once first so create_all() builds the schema, then re-run this script.")
        return

    print(f"Connecting to Postgres ({PG_DSN})...")
    pg = await asyncpg.connect(PG_DSN)

    print(f"Opening SQLite ({SQLITE_PATH})...")
    sq = sqlite3.connect(str(SQLITE_PATH))
    sq.execute("PRAGMA foreign_keys = OFF")

    try:
        # ── 1. households ────────────────────────────────────────────────────
        rows = await pg.fetch(
            "SELECT id, name, created_at, updated_at FROM households"
        )
        sq.executemany(
            "INSERT OR REPLACE INTO households (id, name, created_at, updated_at) VALUES (?,?,?,?)",
            [(uid(r["id"]), r["name"], iso(r["created_at"]), iso(r["updated_at"])) for r in rows],
        )
        print(f"  households:            {len(rows)}")

        # ── 2. users ─────────────────────────────────────────────────────────
        rows = await pg.fetch(
            """SELECT id, email, password_hash, display_name, is_active, is_agent,
                      last_login_at, preferences, created_at, updated_at
               FROM users"""
        )
        sq.executemany(
            """INSERT OR REPLACE INTO users
               (id, email, password_hash, display_name, is_active, is_agent,
                last_login_at, preferences, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    uid(r["id"]),
                    r["email"],
                    r["password_hash"],
                    r["display_name"],
                    r["is_active"],
                    r["is_agent"],
                    iso(r["last_login_at"]),
                    json.dumps(r["preferences"]) if r["preferences"] else None,
                    iso(r["created_at"]),
                    iso(r["updated_at"]),
                )
                for r in rows
            ],
        )
        print(f"  users:                 {len(rows)}")

        # ── 3. household_memberships ──────────────────────────────────────────
        rows = await pg.fetch(
            "SELECT id, household_id, user_id, role, joined_at FROM household_memberships"
        )
        sq.executemany(
            """INSERT OR REPLACE INTO household_memberships
               (id, household_id, user_id, role, joined_at) VALUES (?,?,?,?,?)""",
            [
                (uid(r["id"]), uid(r["household_id"]), uid(r["user_id"]), r["role"], iso(r["joined_at"]))
                for r in rows
            ],
        )
        print(f"  household_memberships: {len(rows)}")

        # ── 4. projects (self-referential — insert without FK enforcement) ────
        rows = await pg.fetch(
            """SELECT id, household_id, created_by_user_id, parent_id, name, description,
                      status, due_date, is_system, show_in_nav, sort_order,
                      archived_at, created_at, updated_at
               FROM projects"""
        )
        sq.executemany(
            """INSERT OR REPLACE INTO projects
               (id, household_id, created_by_user_id, parent_id, name, description,
                status, due_date, is_system, show_in_nav, sort_order,
                archived_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    uid(r["id"]),
                    uid(r["household_id"]),
                    uid(r["created_by_user_id"]),
                    uid(r["parent_id"]),
                    r["name"],
                    r["description"],
                    r["status"],
                    iso(r["due_date"]),
                    r["is_system"],
                    r["show_in_nav"],
                    r["sort_order"],
                    iso(r["archived_at"]),
                    iso(r["created_at"]),
                    iso(r["updated_at"]),
                )
                for r in rows
            ],
        )
        print(f"  projects:              {len(rows)}")

        # ── 5. todos ──────────────────────────────────────────────────────────
        rows = await pg.fetch(
            """SELECT id, household_id, created_by_user_id, title, description, status,
                      priority, due_date, completed_at, recurring, created_at, updated_at,
                      project_id, assigned_to_user_id, link_url
               FROM todos"""
        )
        sq.executemany(
            """INSERT OR REPLACE INTO todos
               (id, household_id, created_by_user_id, title, description, status,
                priority, due_date, completed_at, recurring, created_at, updated_at,
                project_id, assigned_to_user_id, link_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    uid(r["id"]),
                    uid(r["household_id"]),
                    uid(r["created_by_user_id"]),
                    r["title"],
                    r["description"],
                    r["status"],
                    r["priority"],
                    iso(r["due_date"]),
                    iso(r["completed_at"]),
                    json.dumps(r["recurring"]) if r["recurring"] else None,
                    iso(r["created_at"]),
                    iso(r["updated_at"]),
                    uid(r["project_id"]),
                    uid(r["assigned_to_user_id"]),
                    r["link_url"],
                )
                for r in rows
            ],
        )
        print(f"  todos:                 {len(rows)}")

        # ── 6. recipes ────────────────────────────────────────────────────────
        rows = await pg.fetch(
            """SELECT id, household_id, created_by_user_id, goal_id, name, description,
                      cover_image_url, source_url, prep_time_minutes, cook_time_minutes,
                      servings, notes, body, created_at, updated_at
               FROM recipes"""
        )
        sq.executemany(
            """INSERT OR REPLACE INTO recipes
               (id, household_id, created_by_user_id, goal_id, name, description,
                cover_image_url, source_url, prep_time_minutes, cook_time_minutes,
                servings, notes, body, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    uid(r["id"]),
                    uid(r["household_id"]),
                    uid(r["created_by_user_id"]),
                    uid(r["goal_id"]),
                    r["name"],
                    r["description"],
                    r["cover_image_url"],
                    r["source_url"],
                    r["prep_time_minutes"],
                    r["cook_time_minutes"],
                    r["servings"],
                    r["notes"],
                    json.dumps(r["body"]) if r["body"] else None,
                    iso(r["created_at"]),
                    iso(r["updated_at"]),
                )
                for r in rows
            ],
        )
        print(f"  recipes:               {len(rows)}")

        # ── 7. recipe_ingredients ─────────────────────────────────────────────
        rows = await pg.fetch(
            """SELECT id, recipe_id, name, quantity, unit, notes, sort_order
               FROM recipe_ingredients"""
        )
        sq.executemany(
            """INSERT OR REPLACE INTO recipe_ingredients
               (id, recipe_id, name, quantity, unit, notes, sort_order)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (
                    uid(r["id"]),
                    uid(r["recipe_id"]),
                    r["name"],
                    float(r["quantity"]) if r["quantity"] is not None else None,
                    r["unit"],
                    r["notes"],
                    r["sort_order"],
                )
                for r in rows
            ],
        )
        print(f"  recipe_ingredients:    {len(rows)}")

        # ── 8. recipe_steps ───────────────────────────────────────────────────
        rows = await pg.fetch(
            "SELECT id, recipe_id, step_number, instruction, notes FROM recipe_steps"
        )
        sq.executemany(
            """INSERT OR REPLACE INTO recipe_steps
               (id, recipe_id, step_number, instruction, notes)
               VALUES (?,?,?,?,?)""",
            [
                (uid(r["id"]), uid(r["recipe_id"]), r["step_number"], r["instruction"], r["notes"])
                for r in rows
            ],
        )
        print(f"  recipe_steps:          {len(rows)}")

        sq.commit()
        sq.execute("PRAGMA foreign_keys = ON")
        print("\nMigration complete. All data committed to SQLite.")

    except Exception as e:
        sq.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        await pg.close()
        sq.close()


if __name__ == "__main__":
    asyncio.run(migrate())
