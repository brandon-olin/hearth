"""Add meal plans — the weekly meal planner's storage.

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-22

meal-001. Two new tables, no ALTER-shaped work anywhere, so plain
`create_table` + `create_index` replay identically on Postgres and SQLite and
no `batch_alter_table` is needed. Nothing here is Postgres-only:

* `meal_slot` is VARCHAR + CHECK rather than a native enum (ADR-015) — native
  enum types are exactly the drift that broke 0046.
* `visibility` / `shared_with_user_ids` mirror VisibilityMixin's columns
  exactly (String(20) + JSON), so a plan is scoped like a recipe or a grocery
  list rather than inventing a second sharing model.

The two unique constraints are what make the planner idempotent, and both are
enforced by the database rather than a check-then-insert race:

* `uq_meal_plans_household_week` — one plan per household per week. "Plan this
  week" is a get-or-create, and a double-click cannot mint a second plan for
  the same Monday.
* `uq_meal_plan_entries_slot_recipe` — the same recipe cannot land twice in one
  day+slot. Dragging the same recipe onto Wednesday dinner twice is a no-op,
  while the same recipe on Wednesday *and* Thursday is two legitimate rows.

FK behaviour is deliberate: `recipe_id` CASCADEs because a planned meal whose
recipe no longer exists has nothing left to say, whereas `created_by_user_id`
is SET NULL — a departed member must not take the household's plan with them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meal_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # The Monday the plan covers. Normalised server-side, so a client may
        # send any day in the week and still address the same row.
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        # VisibilityMixin columns — same shape as recipes / grocery_lists.
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="household"
        ),
        sa.Column("shared_with_user_ids", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "household_id", "week_start", name="uq_meal_plans_household_week"
        ),
    )
    # The planner's only list query: this household's weeks, most recent first.
    op.create_index(
        "ix_meal_plans_household_week", "meal_plans", ["household_id", "week_start"]
    )

    op.create_table(
        "meal_plan_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("meal_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The calendar date this meal is planned for — always inside the parent
        # plan's week. Named entry_date rather than `date` so it never collides
        # with the SQL type name in raw SQL or an ORM attribute lookup.
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("meal_slot", sa.String(20), nullable=False),
        # Scales the recipe when the plan feeds the grocery generator.
        sa.Column("servings", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "meal_slot IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_meal_plan_entries_slot",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "entry_date",
            "meal_slot",
            "recipe_id",
            name="uq_meal_plan_entries_slot_recipe",
        ),
    )
    # Rendering a week reads every entry for one plan ordered by day then slot.
    op.create_index(
        "ix_meal_plan_entries_plan_date",
        "meal_plan_entries",
        ["plan_id", "entry_date"],
    )
    # "Which plans use this recipe" — read when a recipe is about to be removed.
    op.create_index(
        "ix_meal_plan_entries_recipe", "meal_plan_entries", ["recipe_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_meal_plan_entries_recipe", table_name="meal_plan_entries")
    op.drop_index("ix_meal_plan_entries_plan_date", table_name="meal_plan_entries")
    op.drop_table("meal_plan_entries")
    op.drop_index("ix_meal_plans_household_week", table_name="meal_plans")
    op.drop_table("meal_plans")
