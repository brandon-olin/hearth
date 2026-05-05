"""Drop logseq_index; restore retired domain tables

Revision ID: e2f9a4c7b5d1
Revises: d4f8c1e7a3b9
Create Date: 2026-05-05

Phase 3 pivot: the project returns to a custom React/Next.js app backed by
FastAPI. The Logseq-pivot tables (logseq_index, domain tables retired in
0004) are no longer needed as described.

Specifically:
  - logseq_index is dropped — the indexer service is retired.
  - The following tables are recreated to their Phase 1 state:
      goals, todos, habits, habit_occurrences,
      recipes, recipe_ingredients, recipe_steps,
      grocery_lists, grocery_items
  - The priority_level enum is recreated (served goals.priority /
    todos.priority; was dropped in 0004).
  - notes is intentionally NOT restored — it is superseded by the
    documents table added in migration 0007.

Create order respects FK dependencies:
  goals → todos → habits → habit_occurrences
                 → recipes → recipe_ingredients / recipe_steps
                 → grocery_lists → grocery_items

Downgrade drops all restored tables and recreates logseq_index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "e2f9a4c7b5d1"
down_revision: Union[str, None] = "d4f8c1e7a3b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop logseq_index ─────────────────────────────────────────────────────
    # Functional GIN indexes must be dropped before the table.
    op.drop_index("idx_logseq_index_content_fts", table_name="logseq_index")
    op.drop_index("idx_logseq_index_tags", table_name="logseq_index")
    op.drop_index("idx_logseq_index_graph", table_name="logseq_index")
    op.drop_table("logseq_index")

    # ── priority_level enum ───────────────────────────────────────────────────
    # Dropped in 0004 alongside goals/todos. Recreate before those tables.
    op.execute("CREATE TYPE priority_level AS ENUM ('low', 'medium', 'high')")

    # ── goals ─────────────────────────────────────────────────────────────────
    # Root entity. Self-referential parent_id for hierarchical goal trees.
    # target_value / current_value / unit support progress tracking (e.g.
    # "run 100 km", current = 37, unit = "km").
    op.create_table(
        "goals",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "household_id", UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "parent_id", UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column(
            "priority",
            sa.Enum("low", "medium", "high", name="priority_level", create_type=False),
            nullable=True,
        ),
        sa.Column("target_value", sa.Numeric(), nullable=True),
        sa.Column("current_value", sa.Numeric(), nullable=True, server_default="0"),
        sa.Column("unit", sa.String(100), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_goals_household_id", "goals", ["household_id"])
    op.create_index("idx_goals_parent_id", "goals", ["parent_id"])
    op.execute(
        "CREATE TRIGGER goals_updated_at BEFORE UPDATE ON goals "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── todos ─────────────────────────────────────────────────────────────────
    # Hierarchical via parent_id. Optional goal linkage. recurring JSONB stores
    # cadence config (e.g. {"freq": "weekly", "days": ["mon", "wed"]}).
    op.create_table(
        "todos",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "household_id", UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "parent_id", UUID(as_uuid=True),
            sa.ForeignKey("todos.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "goal_id", UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column(
            "priority",
            sa.Enum("low", "medium", "high", name="priority_level", create_type=False),
            nullable=True,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recurring", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_todos_household_id", "todos", ["household_id"])
    op.create_index("idx_todos_parent_id", "todos", ["parent_id"])
    op.create_index("idx_todos_goal_id", "todos", ["goal_id"])
    op.execute(
        "CREATE TRIGGER todos_updated_at BEFORE UPDATE ON todos "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── habits ────────────────────────────────────────────────────────────────
    # Defines the cadence template. Actual occurrences are in habit_occurrences.
    # cadence JSONB: {"freq": "daily"} | {"freq": "weekly", "days": ["mon"]} |
    #                {"freq": "monthly", "day_of_month": 1}
    op.create_table(
        "habits",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "household_id", UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "goal_id", UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("frequency", sa.String(50), nullable=False, server_default="daily"),
        sa.Column("cadence", JSONB(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_habits_household_id", "habits", ["household_id"])
    op.create_index("idx_habits_goal_id", "habits", ["goal_id"])
    op.execute(
        "CREATE TRIGGER habits_updated_at BEFORE UPDATE ON habits "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── habit_occurrences ─────────────────────────────────────────────────────
    # Materialized instances of a habit on a specific date. todo_id links to a
    # companion todo when the habit generates an actionable task.
    op.create_table(
        "habit_occurrences",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "habit_id", UUID(as_uuid=True),
            sa.ForeignKey("habits.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "todo_id", UUID(as_uuid=True),
            sa.ForeignKey("todos.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_habit_occurrences_habit_id", "habit_occurrences", ["habit_id"])
    op.create_index(
        "idx_habit_occurrences_scheduled_date", "habit_occurrences", ["scheduled_date"]
    )
    op.execute(
        "CREATE TRIGGER habit_occurrences_updated_at BEFORE UPDATE ON habit_occurrences "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── recipes ───────────────────────────────────────────────────────────────
    # Intentionally omits the legacy notes_id FK — notes is not restored.
    op.create_table(
        "recipes",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "household_id", UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "goal_id", UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("prep_time_minutes", sa.Integer(), nullable=True),
        sa.Column("cook_time_minutes", sa.Integer(), nullable=True),
        sa.Column("servings", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_recipes_household_id", "recipes", ["household_id"])
    op.execute(
        "CREATE TRIGGER recipes_updated_at BEFORE UPDATE ON recipes "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── recipe_ingredients ────────────────────────────────────────────────────
    # Child of recipe — no household_id, no timestamp trigger.
    # sort_order controls display sequence.
    op.create_table(
        "recipe_ingredients",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recipe_id", UUID(as_uuid=True),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("idx_recipe_ingredients_recipe_id", "recipe_ingredients", ["recipe_id"])

    # ── recipe_steps ──────────────────────────────────────────────────────────
    # Child of recipe — no household_id, no timestamp trigger.
    op.create_table(
        "recipe_steps",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recipe_id", UUID(as_uuid=True),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("idx_recipe_steps_recipe_id", "recipe_steps", ["recipe_id"])

    # ── grocery_lists ─────────────────────────────────────────────────────────
    # todo_id links to a companion todo so the shopping trip can be tracked as a task.
    op.create_table(
        "grocery_lists",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "household_id", UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "todo_id", UUID(as_uuid=True),
            sa.ForeignKey("todos.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("store", sa.String(200), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_grocery_lists_household_id", "grocery_lists", ["household_id"])
    op.execute(
        "CREATE TRIGGER grocery_lists_updated_at BEFORE UPDATE ON grocery_lists "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )

    # ── grocery_items ─────────────────────────────────────────────────────────
    # Child of grocery_list. recipe_id / recipe_ingredient_id are optional links
    # so meal-plan-generated lists can trace items back to their recipe.
    op.create_table(
        "grocery_items",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "list_id", UUID(as_uuid=True),
            sa.ForeignKey("grocery_lists.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "recipe_id", UUID(as_uuid=True),
            sa.ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "recipe_ingredient_id", UUID(as_uuid=True),
            sa.ForeignKey("recipe_ingredients.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(100), nullable=True),
        sa.Column("category", sa.String(200), nullable=True),
        sa.Column("is_checked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("idx_grocery_items_list_id", "grocery_items", ["list_id"])
    op.execute(
        "CREATE TRIGGER grocery_items_updated_at BEFORE UPDATE ON grocery_items "
        "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
    )


def downgrade() -> None:
    # ── Drop restored domain tables (reverse dependency order) ────────────────
    op.execute("DROP TRIGGER IF EXISTS grocery_items_updated_at ON grocery_items")
    op.drop_table("grocery_items")

    op.execute("DROP TRIGGER IF EXISTS grocery_lists_updated_at ON grocery_lists")
    op.drop_table("grocery_lists")

    op.drop_table("recipe_steps")
    op.drop_table("recipe_ingredients")

    op.execute("DROP TRIGGER IF EXISTS recipes_updated_at ON recipes")
    op.drop_table("recipes")

    op.execute("DROP TRIGGER IF EXISTS habit_occurrences_updated_at ON habit_occurrences")
    op.drop_table("habit_occurrences")

    op.execute("DROP TRIGGER IF EXISTS habits_updated_at ON habits")
    op.drop_table("habits")

    op.execute("DROP TRIGGER IF EXISTS todos_updated_at ON todos")
    op.drop_table("todos")

    op.execute("DROP TRIGGER IF EXISTS goals_updated_at ON goals")
    op.drop_table("goals")

    op.execute("DROP TYPE IF EXISTS priority_level")

    # ── Recreate logseq_index ─────────────────────────────────────────────────
    op.create_table(
        "logseq_index",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("graph", sa.Text(), nullable=False),
        sa.Column("page_name", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("properties", JSONB(), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("block_count", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint("graph", "page_name", name="logseq_index_graph_page_name_key"),
    )
    op.create_index("idx_logseq_index_graph", "logseq_index", ["graph"])
    op.create_index(
        "idx_logseq_index_tags", "logseq_index", ["tags"], postgresql_using="gin"
    )
    op.create_index(
        "idx_logseq_index_content_fts",
        "logseq_index",
        [sa.text("to_tsvector('english', coalesce(content, ''))")],
        postgresql_using="gin",
    )
