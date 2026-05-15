"""
Fix UUID format in SQLite DB.

SQLAlchemy's Uuid() type stores as CHAR(32) — no hyphens.
The migration script inserted 36-char hyphenated UUIDs, which breaks
UPDATE/DELETE statements (WHERE id = ? uses no-hyphen format, matches 0 rows).

Run from api/ directory:
    python scripts/fix_sqlite_uuids.py
"""

import sqlite3
from pathlib import Path

SQLITE_PATH = Path(__file__).parent.parent / "life_dashboard.db"

# (table, [uuid_columns])
UUID_COLUMNS = [
    ("households",             ["id"]),
    ("users",                  ["id"]),
    ("household_memberships",  ["id", "household_id", "user_id"]),
    ("refresh_tokens",         ["id", "user_id"]),
    ("projects",               ["id", "household_id", "created_by_user_id", "parent_id"]),
    ("todos",                  ["id", "household_id", "created_by_user_id", "project_id", "assigned_to_user_id"]),
    ("recipes",                ["id", "household_id", "created_by_user_id", "goal_id"]),
    ("recipe_ingredients",     ["id", "recipe_id"]),
    ("recipe_steps",           ["id", "recipe_id"]),
    ("habits",                 ["id", "household_id", "created_by_user_id"]),
    ("habit_occurrences",      ["id", "habit_id"]),
    ("documents",              ["id", "household_id", "created_by_user_id"]),
    ("goals",                  ["id", "household_id", "created_by_user_id"]),
    ("tags",                   ["id", "household_id"]),
    ("notifications",          ["id", "household_id", "recipient_id", "actor_id"]),
]

conn = sqlite3.connect(str(SQLITE_PATH))
conn.execute("PRAGMA foreign_keys = OFF")

total_updated = 0
for table, cols in UUID_COLUMNS:
    # Check the table exists
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        print(f"  skipping {table} (table not found)")
        continue

    for col in cols:
        # Only touch rows where the value looks like a hyphenated UUID (length 36)
        result = conn.execute(
            f"UPDATE {table} SET {col} = REPLACE({col}, '-', '') "
            f"WHERE {col} IS NOT NULL AND length({col}) = 36"
        )
        if result.rowcount:
            print(f"  {table}.{col}: fixed {result.rowcount} row(s)")
            total_updated += result.rowcount

conn.commit()
conn.execute("PRAGMA foreign_keys = ON")
conn.close()

print(f"\nDone. {total_updated} total values converted to no-hyphen format.")
