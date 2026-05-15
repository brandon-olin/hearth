"""
One-shot migration: add visibility columns to all 9 domain tables.
Run from the api/ directory with the API server STOPPED:

    python3 add_visibility_columns.py
"""
import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(__file__), "life_dashboard.db")

if not os.path.exists(DB_PATH):
    sys.exit(f"ERROR: database not found at {DB_PATH}")

print(f"Opening {DB_PATH}")
conn = sqlite3.connect(DB_PATH)

HOUSEHOLD_TABLES = ["todos", "projects", "grocery_lists", "recipes"]
PERSONAL_TABLES  = ["notes", "documents", "workouts", "habits", "goals"]

statements = []
for table in HOUSEHOLD_TABLES:
    statements.append((table, "visibility",          f"ALTER TABLE {table} ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'household'"))
    statements.append((table, "shared_with_user_ids", f"ALTER TABLE {table} ADD COLUMN shared_with_user_ids JSON"))

for table in PERSONAL_TABLES:
    statements.append((table, "visibility",           f"ALTER TABLE {table} ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'personal'"))
    statements.append((table, "shared_with_user_ids", f"ALTER TABLE {table} ADD COLUMN shared_with_user_ids JSON"))

ok = 0
skipped = 0
for table, col, sql in statements:
    try:
        conn.execute(sql)
        print(f"  + {table}.{col}")
        ok += 1
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print(f"  = {table}.{col}  (already exists, skipped)")
            skipped += 1
        else:
            print(f"  ! {table}.{col}  ERROR: {e}")

conn.commit()
conn.close()
print(f"\nDone — {ok} added, {skipped} already existed. Restart the API.")
