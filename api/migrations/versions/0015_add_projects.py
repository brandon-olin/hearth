"""add projects domain, project_goals join, update todos

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-11

Introduces Projects as a first-class container for tasks and goals.

Changes:
  - New `project_status` enum
  - New `projects` table (self-referential via parent_id, depth up to 7)
  - New `project_goals` join table (m2m between projects and goals)
  - `todos`: drop parent_id (no more todo nesting), drop goal_id, add project_id FK → projects
  - Seed: INSERT a system "To-dos" project for each existing household
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def _index_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = :t AND constraint_name = :c"
        ),
        {"t": table, "c": constraint},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── project_status enum ───────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE project_status AS ENUM (
                'backlog', 'active', 'on_deck', 'in_progress', 'complete', 'archived'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ── projects ──────────────────────────────────────────────────────────────
    if not _table_exists(conn, "projects"):
        op.create_table(
            "projects",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "household_id",
                UUID(as_uuid=True),
                sa.ForeignKey("households.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_by_user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            # Self-referential: sub-projects; depth enforced in service layer (max 7)
            sa.Column(
                "parent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                PgEnum(
                    "backlog",
                    "active",
                    "on_deck",
                    "in_progress",
                    "complete",
                    "archived",
                    name="project_status",
                    create_type=False,
                ),
                nullable=False,
                server_default="active",
            ),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("show_in_nav", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        )
        if not _index_exists(conn, "ix_projects_household_id"):
            op.create_index("ix_projects_household_id", "projects", ["household_id"])
        if not _index_exists(conn, "ix_projects_parent_id"):
            op.create_index("ix_projects_parent_id", "projects", ["parent_id"])

    # ── project_goals (m2m) ───────────────────────────────────────────────────
    if not _table_exists(conn, "project_goals"):
        op.create_table(
            "project_goals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "goal_id",
                UUID(as_uuid=True),
                sa.ForeignKey("goals.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("project_id", "goal_id", name="uq_project_goals"),
        )
        if not _index_exists(conn, "ix_project_goals_project_id"):
            op.create_index("ix_project_goals_project_id", "project_goals", ["project_id"])
        if not _index_exists(conn, "ix_project_goals_goal_id"):
            op.create_index("ix_project_goals_goal_id", "project_goals", ["goal_id"])

    # ── todos: drop parent_id and goal_id ─────────────────────────────────────
    if _constraint_exists(conn, "todos", "todos_parent_id_fkey"):
        op.drop_constraint("todos_parent_id_fkey", "todos", type_="foreignkey")
    if _column_exists(conn, "todos", "parent_id"):
        op.drop_column("todos", "parent_id")

    if _constraint_exists(conn, "todos", "todos_goal_id_fkey"):
        op.drop_constraint("todos_goal_id_fkey", "todos", type_="foreignkey")
    if _column_exists(conn, "todos", "goal_id"):
        op.drop_column("todos", "goal_id")

    # ── todos: add project_id ─────────────────────────────────────────────────
    if not _column_exists(conn, "todos", "project_id"):
        op.add_column(
            "todos",
            sa.Column(
                "project_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        if not _index_exists(conn, "ix_todos_project_id"):
            op.create_index("ix_todos_project_id", "todos", ["project_id"])

    # ── seed system "To-dos" project for every existing household ─────────────
    households = conn.execute(sa.text("SELECT id FROM households")).fetchall()
    for (household_id,) in households:
        already = conn.execute(
            sa.text(
                "SELECT 1 FROM projects "
                "WHERE household_id = :hid AND is_system = true LIMIT 1"
            ),
            {"hid": str(household_id)},
        ).fetchone()
        if not already:
            project_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    """
                    INSERT INTO projects
                        (id, household_id, name, status, is_system, show_in_nav, sort_order)
                    VALUES
                        (:id, :household_id, 'To-dos', 'active', true, true, 0)
                    """
                ),
                {"id": str(project_id), "household_id": str(household_id)},
            )


def downgrade() -> None:
    op.drop_index("ix_todos_project_id", table_name="todos")
    op.drop_column("todos", "project_id")

    # Restore goal_id and parent_id on todos
    op.add_column(
        "todos",
        sa.Column(
            "goal_id",
            UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "todos",
        sa.Column(
            "parent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("todos.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.drop_index("ix_project_goals_goal_id", table_name="project_goals")
    op.drop_index("ix_project_goals_project_id", table_name="project_goals")
    op.drop_table("project_goals")

    op.drop_index("ix_projects_parent_id", table_name="projects")
    op.drop_index("ix_projects_household_id", table_name="projects")
    op.drop_table("projects")

    op.execute(sa.text("DROP TYPE IF EXISTS project_status"))
