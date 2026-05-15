"""
Fix double-encoded JSON columns in SQLite.

asyncpg returns JSON/JSONB columns as Python strings (not parsed dicts),
so json.dumps() in the migration script encoded them twice.
SQLAlchemy decodes once on read, returning a string instead of a dict.

This script detects double-encoded values (those that JSON-decode to a string)
and decodes them one extra time so SQLAlchemy sees the correct type.

Run from api/ directory:
    python scripts/fix_sqlite_json.py
"""

import json
import sqlite3
from pathlib import Path

SQLITE_PATH = Path(__file__).parent.parent / "life_dashboard.db"

# (table, id_col, json_col)
JSON_COLUMNS = [
    ("users",   "id", "preferences"),
    ("todos",   "id", "recurring"),
    ("recipes", "id", "body"),
    ("habits",  "id", "cadence"),
]

conn = sqlite3.connect(str(SQLITE_PATH))
total = 0

for table, id_col, json_col in JSON_COLUMNS:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        print(f"  skipping {table} (not found)")
        continue

    rows = conn.execute(
        f"SELECT {id_col}, {json_col} FROM {table} WHERE {json_col} IS NOT NULL"
    ).fetchall()

    fixed = 0
    for row_id, value in rows:
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue  # not valid JSON, skip

        # If decoding gives a string, it was double-encoded — decode once more
        if isinstance(decoded, str):
            conn.execute(
                f"UPDATE {table} SET {json_col} = ? WHERE {id_col} = ?",
                (decoded, row_id),
            )
            fixed += 1

    if fixed:
        print(f"  {table}.{json_col}: fixed {fixed} row(s)")
    else:
        print(f"  {table}.{json_col}: ok (no double-encoding found)")
    total += fixed

conn.commit()
conn.close()
print(f"\nDone. {total} total values fixed.")
