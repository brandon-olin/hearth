"""0036 — Field-level encryption for sensitive columns.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-26

Covers two concerns:

1. Schema change
   journal_signals.notable_phrases: JSON → TEXT
   EncryptedJSON stores Fernet ciphertext, which is not valid JSON.
   The column must be TEXT so Postgres accepts the encrypted bytes.
   Existing JSON values are cast to text first, then encrypted below.

2. Data migration
   Encrypts all existing plaintext rows in every newly-encrypted column
   using the FIELD_ENCRYPTION_KEY environment variable.

   If FIELD_ENCRYPTION_KEY is not set (local dev, CI without secrets),
   the data step is skipped and a notice is printed.  In that case every
   row stays plaintext, which is fine for local dev — the TypeDecorators
   will pass values through unencrypted until the key is configured.

   To run this migration with encryption on an existing database:
     export FIELD_ENCRYPTION_KEY=<your-key>
     alembic upgrade head

Columns encrypted (all TEXT or already-TEXT-cast):
  budget_accounts         teller_access_token
  ai_settings             api_key_encrypted
  member_ai_memory        memory_text
  ai_coach_digests        content
  user_profile_updates    proposed_content_md
  user_profile_versions   content_md
  journal_signals         notable_phrases      (JSON → TEXT, then encrypt)
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_fernet():
    """Return a MultiFernet if FIELD_ENCRYPTION_KEY is set, else None."""
    raw = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    # Import here so Alembic doesn't require cryptography at import time
    # when the migration file is merely being enumerated.
    from cryptography.fernet import Fernet, MultiFernet
    keys = [k.strip().encode() for k in raw.split(",") if k.strip()]
    return MultiFernet([Fernet(k) for k in keys])


def _encrypt_text_column(conn, fernet, table: str, pk_col: str, col: str) -> int:
    """Read all non-NULL rows, encrypt each value, write back. Returns row count."""
    rows = conn.execute(
        sa.text(f"SELECT {pk_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
    ).fetchall()
    count = 0
    for row in rows:
        pk_val, plaintext = row[0], row[1]
        if not plaintext:
            continue
        encrypted = fernet.encrypt(plaintext.encode()).decode()
        conn.execute(
            sa.text(f"UPDATE {table} SET {col} = :enc WHERE {pk_col} = :pk"),
            {"enc": encrypted, "pk": pk_val},
        )
        count += 1
    return count


def _encrypt_json_column(conn, fernet, table: str, pk_col: str, col: str) -> int:
    """Read all non-NULL JSON-as-text rows, encrypt each, write back."""
    rows = conn.execute(
        sa.text(f"SELECT {pk_col}, {col} FROM {table} WHERE {col} IS NOT NULL")
    ).fetchall()
    count = 0
    for row in rows:
        pk_val, raw = row[0], row[1]
        if raw is None:
            continue
        # raw is already a string (column was cast to TEXT in step 1).
        encrypted = fernet.encrypt(raw.encode()).decode()
        conn.execute(
            sa.text(f"UPDATE {table} SET {col} = :enc WHERE {pk_col} = :pk"),
            {"enc": encrypted, "pk": pk_val},
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ── Step 1: Schema change — notable_phrases JSON → TEXT ─────────────────
    # EncryptedJSON's impl is Text, so Alembic/Postgres needs a TEXT column.
    # We cast existing JSON values to their text representation before
    # encrypting them in Step 2.
    with op.batch_alter_table("journal_signals") as batch_op:
        batch_op.alter_column(
            "notable_phrases",
            type_=sa.Text(),
            existing_nullable=True,
            postgresql_using="notable_phrases::text",
        )

    # ── Step 2: Data migration — encrypt plaintext values ───────────────────
    fernet = _get_fernet()
    if fernet is None:
        print(
            "\n  [0036] FIELD_ENCRYPTION_KEY is not set — skipping data encryption.\n"
            "         Existing rows remain plaintext. Set the key and re-run this\n"
            "         migration (after rolling back to 0035) to encrypt them.\n"
        )
        return

    conn = op.get_bind()

    specs = [
        # (table, primary_key_column, sensitive_column, is_json)
        ("budget_accounts",       "id",      "teller_access_token",  False),
        ("ai_settings",           "user_id", "api_key_encrypted",    False),
        ("member_ai_memory",      "user_id", "memory_text",          False),
        ("ai_coach_digests",      "id",      "content",              False),
        ("user_profile_updates",  "id",      "proposed_content_md",  False),
        ("user_profile_versions", "id",      "content_md",           False),
        ("journal_signals",       "id",      "notable_phrases",      True),
    ]

    total = 0
    for table, pk_col, col, is_json in specs:
        fn = _encrypt_json_column if is_json else _encrypt_text_column
        n = fn(conn, fernet, table, pk_col, col)
        if n:
            print(f"  [0036] Encrypted {n} row(s) in {table}.{col}")
        total += n

    print(f"  [0036] Data migration complete — {total} row(s) encrypted.")


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Revert the schema change: TEXT → JSON on notable_phrases.
    # NOTE: data is NOT decrypted on downgrade — rows written while encryption
    # was active will contain Fernet ciphertext in the JSON column, which is
    # invalid JSON.  Manually decrypt and restore from backup if needed.
    with op.batch_alter_table("journal_signals") as batch_op:
        batch_op.alter_column(
            "notable_phrases",
            type_=sa.JSON(),
            existing_nullable=True,
        )
