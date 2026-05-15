"""
Visibility / sharing model for household domain entities.

Every domain entity that participates in visibility control inherits
VisibilityMixin, which adds two columns:

  visibility          VARCHAR(20)  — "household" | "personal" | "members"
  shared_with_user_ids  JSON       — list of user-id strings (only when
                                     visibility == "members")

apply_visibility_filter() wraps any SELECT statement so that only items
the requesting user is entitled to see are returned:

  household  → visible to all household members (the default for shared data)
  personal   → only the creator (used for private notes, journals, workouts)
  members    → explicitly listed user IDs (the creator is always implicitly
               included even if not listed)

Cross-database JSON containment
--------------------------------
SQLAlchemy's JSON type doesn't expose a portable "array contains" operator.
We use cast(column, String).contains(uuid_str) which generates
  CAST(col AS TEXT) LIKE '%<uuid>%'
This is safe for UUID values (hex chars + dashes only — no LIKE wildcards)
and works on both SQLite and PostgreSQL.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, String, cast, or_, and_
from sqlalchemy.orm import Mapped, mapped_column, validates

# ── Visibility constants ──────────────────────────────────────────────────────

VISIBILITY_HOUSEHOLD = "household"
VISIBILITY_PERSONAL  = "personal"
VISIBILITY_MEMBERS   = "members"

VALID_VISIBILITIES = {VISIBILITY_HOUSEHOLD, VISIBILITY_PERSONAL, VISIBILITY_MEMBERS}


# ── SQLAlchemy mixin ──────────────────────────────────────────────────────────

class VisibilityMixin:
    """
    Mixin that adds visibility + shared_with_user_ids to a mapped class.

    Usage::

        class Note(VisibilityMixin, Base):
            __tablename__ = "notes"
            ...

    Override the default in the model by setting a class-level
    ``__visibility_default__`` attribute before the mixin columns are
    processed — or simply pass the desired default in the mapped_column
    call in the concrete subclass.  The pattern here uses a single shared
    mixin with "household" as the default; the migration sets the
    correct column DEFAULT per table.
    """

    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=VISIBILITY_HOUSEHOLD,
        server_default=VISIBILITY_HOUSEHOLD,
    )
    shared_with_user_ids: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    @validates("shared_with_user_ids")
    def _coerce_shared_with(self, key: str, value: list[str] | None) -> list[str]:
        """Coerce NULL (legacy rows) to an empty list so Pydantic never sees None."""
        return value if value is not None else []


# ── Query helper ──────────────────────────────────────────────────────────────

def apply_visibility_filter(stmt: Any, model: Any, user_id: uuid.UUID) -> Any:
    """
    Append a WHERE clause that restricts results to rows the given user
    is allowed to see.

    :param stmt:    A SQLAlchemy SELECT statement already filtered by
                    household_id.
    :param model:   The ORM model class (must have VisibilityMixin columns
                    and a created_by_user_id column).
    :param user_id: The UUID of the requesting user.
    :returns:       The statement with the visibility filter applied.
    """
    uid_str = str(user_id)

    return stmt.where(
        or_(
            # Shared with everyone in the household
            model.visibility == VISIBILITY_HOUSEHOLD,

            # Creator-only personal items
            and_(
                model.visibility == VISIBILITY_PERSONAL,
                model.created_by_user_id == user_id,
            ),

            # Explicitly shared with specific members.
            # The creator is always implicitly allowed even when not listed.
            and_(
                model.visibility == VISIBILITY_MEMBERS,
                or_(
                    model.created_by_user_id == user_id,
                    # CAST(shared_with_user_ids AS TEXT) LIKE '%<uuid>%'
                    # Safe for UUID values (no LIKE wildcard chars in hex+dash).
                    cast(model.shared_with_user_ids, String).contains(uid_str),
                ),
            ),
        )
    )
