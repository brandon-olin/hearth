"""Fold the backfill_journal_kind boot hook into a migration.

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-20

infra-004 / ADR-014 action item 7. `backfill_journal_kind` ran on every boot
because migration 0032's backfill is Postgres-only (native JSONB operators),
leaving SQLite installs at kind=NULL. Now that Alembic runs on SQLite
(infra-003), the backfill belongs here and the hook is deleted.

Two jobs, both purely historical:

1. Tag kind=NULL notes-domain collections that look like journals — name is
   'journal' case-insensitively, OR auto_create_rule frequency == 'daily'.
2. Seed a journal collection for every household lacking one, attributed to
   the earliest-joined member (NULL created_by_user_id for orphan households).

Job 2 is not an ongoing invariant: `seed_default_journal_collection` is called
at both household-creation points (auth/router.py signup, setup/router.py
first-run), so new households already get one at creation.

Idempotency matters — this runs against production Postgres on the next deploy
(`api/railway.json` preDeployCommand), where 0032 already did most of the work.
Step 1 only touches kind IS NULL rows; step 2 only inserts for households with
no kind='journal' collection. A second run is a no-op.

Dialect portability is achieved by doing the work in Python over a SQLAlchemy
Core table rather than raw SQL: no JSONB operators, no `gen_random_uuid()`, and
UUID/JSON/boolean values are bound through typed columns so each backend gets
its own representation (Postgres native UUID vs. SQLite CHAR(32)).
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


_DEFAULT_JOURNAL_NAME = "Journal"
_DEFAULT_JOURNAL_ICON = "book-open"
_DEFAULT_JOURNAL_AUTO_CREATE = {
    "frequency": "daily",
    "title_template": "{{day_of_week}}, {{month}} {{day}}, {{year}}",
}


# Minimal Core definitions — typed so binds render correctly on both engines.
collections = sa.table(
    "collections",
    sa.column("id", sa.Uuid()),
    sa.column("household_id", sa.Uuid()),
    sa.column("created_by_user_id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("icon", sa.Text()),
    # `domain` is a native Postgres enum (`collection_domain`, created in 0013).
    # It must be declared as an Enum, not String: the asyncpg dialect renders
    # typed casts for bind params, so a String-typed column produces
    # `domain = $1::VARCHAR` — and Postgres has no `enum = varchar` operator.
    # Declaring the enum yields `$1::collection_domain` on Postgres and a plain
    # VARCHAR bind on SQLite. No DDL is emitted from a Core `sa.table()`, so the
    # type is never created or dropped here.
    sa.column("domain", sa.Enum("notes", "documents", name="collection_domain")),
    sa.column("kind", sa.String()),
    sa.column("default_tags", sa.JSON()),
    sa.column("auto_create_rule", sa.JSON()),
    sa.column("show_in_nav", sa.Boolean()),
    sa.column("sort_order", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

households = sa.table("households", sa.column("id", sa.Uuid()))

memberships = sa.table(
    "household_memberships",
    sa.column("household_id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("joined_at", sa.DateTime(timezone=True)),
)


def _looks_like_journal(name, auto_create_rule) -> bool:
    if (name or "").strip().lower() == "journal":
        return True
    # auto_create_rule may arrive decoded (JSON type) or as raw text depending
    # on how the column was created; only the decoded dict case can match.
    return (
        isinstance(auto_create_rule, dict)
        and auto_create_rule.get("frequency") == "daily"
    )


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1) Tag existing collections that look like journals ──────────────────
    candidates = bind.execute(
        sa.select(collections.c.id, collections.c.name, collections.c.auto_create_rule)
        .where(collections.c.kind.is_(None))
        .where(collections.c.domain == "notes")
    ).all()

    journal_ids = [
        row.id for row in candidates if _looks_like_journal(row.name, row.auto_create_rule)
    ]
    if journal_ids:
        bind.execute(
            sa.update(collections)
            .where(collections.c.id.in_(journal_ids))
            .values(kind="journal")
        )

    # ── 2) Seed households still missing a journal collection ────────────────
    missing = bind.execute(
        sa.select(households.c.id).where(
            ~sa.exists(
                sa.select(collections.c.id)
                .where(collections.c.household_id == households.c.id)
                .where(collections.c.kind == "journal")
            )
        )
    ).scalars().all()

    if not missing:
        return

    now = datetime.now(UTC)
    rows = []
    for household_id in missing:
        # Earliest-joined member owns the seeded collection; NULL is a valid
        # created_by_user_id for an orphan household with no memberships.
        owner_id = bind.execute(
            sa.select(memberships.c.user_id)
            .where(memberships.c.household_id == household_id)
            .order_by(memberships.c.joined_at.asc())
            .limit(1)
        ).scalar()

        rows.append(
            {
                "id": uuid.uuid4(),
                "household_id": household_id,
                "created_by_user_id": owner_id,
                "name": _DEFAULT_JOURNAL_NAME,
                "icon": _DEFAULT_JOURNAL_ICON,
                "domain": "notes",
                "kind": "journal",
                "default_tags": [],
                "auto_create_rule": _DEFAULT_JOURNAL_AUTO_CREATE,
                "show_in_nav": True,
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            }
        )

    bind.execute(sa.insert(collections), rows)


def downgrade() -> None:
    # Untagging journal collections would silently break the coach's narrative
    # fetch and the journal signal extractor, and the seeded rows are
    # indistinguishable from user-created ones. Leave the data in place.
    pass
