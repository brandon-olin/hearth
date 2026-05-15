import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.visibility import VisibilityMixin


class Project(VisibilityMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        SaEnum(
            "backlog", "active", "on_deck", "in_progress", "complete", "archived",
            native_enum=False,
        ),
        default="active",
        server_default="active",
    )
    due_date: Mapped[date | None] = mapped_column(Date)

    # System projects (e.g. "To-dos") cannot be renamed or deleted by users
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Whether this project is pinned to the main nav sidebar
    show_in_nav: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Sub-projects (depth enforced in service layer, max 7)
    children: Mapped[list["Project"]] = relationship(
        "Project", lazy="noload", passive_deletes=True
    )


class ProjectGoal(Base):
    """Many-to-many join between projects and goals."""

    __tablename__ = "project_goals"
    __table_args__ = (
        UniqueConstraint("project_id", "goal_id", name="uq_project_goals"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("projects.id", ondelete="CASCADE")
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("goals.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
