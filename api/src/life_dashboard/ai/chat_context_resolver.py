"""Chat context resolver — Phase 1 of context-aware chat (chat-001).

Given a {type, id} hint from the client (what resource the user is
currently viewing in the app), produce a brief markdown block to be
prepended to the chat system prompt so the AI knows what "this" refers
to without the user having to paste content.

Two principles:

1. Visibility-aware. The resolver runs the same access checks the
   listing/detail endpoints do — personal notes are only readable by
   their author, household resources respect VisibilityMixin. An
   unauthorised or missing ref returns "" silently rather than raising,
   so a stale browser tab never breaks chat.

2. Conservative content budgets. Each formatter caps the included text
   so the system prompt stays small. The point is to ground the AI on
   *this resource*, not to dump full content; if the AI needs more it
   can call the corresponding domain tool (list_notes, get_recipe, etc).

Supported types (chat-001 scope): note, recipe, document, todo, goal, habit.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai.schemas import ChatContextRef

logger = logging.getLogger(__name__)


# Per-resource character cap for any body/description text we splice in.
# Bigger than a tweet, smaller than a doc page — enough to ground the
# AI on what's interesting without burning tokens.
_BODY_CHAR_CAP = 1500


# ── Per-type formatters ───────────────────────────────────────────────────────

async def _format_note(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    note_id: uuid.UUID,
) -> str:
    """Notes are always personal (visibility='personal'). Only the author
    can read them. We don't go through apply_visibility_filter here
    because notes don't expose household-shared visibility today.
    """
    from life_dashboard.domains.notes.models import Note
    from life_dashboard.domains.collections.models import Collection

    note = (await db.execute(
        select(Note).where(
            Note.id == note_id,
            Note.household_id == household_id,
            Note.created_by_user_id == user_id,
            Note.archived_at.is_(None),
        )
    )).scalar_one_or_none()
    if note is None:
        return ""

    # Is this note in a journal-kind collection? Worth labeling so the AI
    # knows to lean on the journal-coaching register if relevant.
    journal_label = ""
    if note.collection_id:
        col_kind = (await db.execute(
            select(Collection.kind).where(Collection.id == note.collection_id)
        )).scalar_one_or_none()
        if col_kind == "journal":
            journal_label = " (Journal entry)"

    body = (note.content_md or "").strip()
    if len(body) > _BODY_CHAR_CAP:
        body = body[:_BODY_CHAR_CAP] + " […]"

    parts = [
        f"**Note** — {(note.title or 'Untitled').strip()}{journal_label}",
    ]
    if body:
        parts += ["", body]
    return "\n".join(parts)


async def _format_recipe(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
) -> str:
    from life_dashboard.domains.recipes.models import Recipe
    from life_dashboard.core.visibility import apply_visibility_filter

    q = select(Recipe).where(
        Recipe.id == recipe_id,
        Recipe.household_id == household_id,
    )
    q = apply_visibility_filter(q, Recipe, user_id)
    recipe = (await db.execute(q)).scalar_one_or_none()
    if recipe is None:
        return ""

    parts = [f"**Recipe** — {(recipe.name or 'Untitled').strip()}"]
    meta_bits: list[str] = []
    if getattr(recipe, "servings", None):
        meta_bits.append(f"Servings: {recipe.servings}")
    if getattr(recipe, "prep_minutes", None):
        meta_bits.append(f"Prep: {recipe.prep_minutes}m")
    if getattr(recipe, "cook_minutes", None):
        meta_bits.append(f"Cook: {recipe.cook_minutes}m")
    if meta_bits:
        parts.append(" · ".join(meta_bits))

    desc = (getattr(recipe, "description", None) or "").strip()
    if desc:
        if len(desc) > 400:
            desc = desc[:400] + " […]"
        parts += ["", desc]

    # Ingredients are stored as JSON on Recipe.
    ingredients = getattr(recipe, "ingredients", None) or []
    if isinstance(ingredients, list) and ingredients:
        ing_lines: list[str] = []
        for ing in ingredients[:25]:  # cap to keep prompt tidy
            if isinstance(ing, dict):
                name = (ing.get("name") or "").strip()
                qty = (ing.get("quantity") or ing.get("amount") or "").strip() if isinstance(ing.get("quantity") or ing.get("amount"), str) else ""
                if name:
                    ing_lines.append(f"- {qty + ' ' if qty else ''}{name}".strip())
        if ing_lines:
            parts += ["", "**Ingredients:**", *ing_lines]

    # Instructions / steps — same JSON-ish field name varies; try both.
    steps = (
        getattr(recipe, "instructions", None)
        or getattr(recipe, "steps", None)
        or []
    )
    if isinstance(steps, list) and steps:
        step_lines: list[str] = []
        for i, step in enumerate(steps[:15], start=1):
            if isinstance(step, str):
                text = step.strip()
            elif isinstance(step, dict):
                text = (step.get("text") or step.get("description") or "").strip()
            else:
                text = ""
            if text:
                if len(text) > 200:
                    text = text[:200] + " […]"
                step_lines.append(f"{i}. {text}")
        if step_lines:
            parts += ["", "**Steps:**", *step_lines]

    return "\n".join(parts)


async def _format_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    document_id: uuid.UUID,
) -> str:
    from life_dashboard.domains.documents.models import Document
    from life_dashboard.core.visibility import apply_visibility_filter

    q = select(Document).where(
        Document.id == document_id,
        Document.household_id == household_id,
    )
    q = apply_visibility_filter(q, Document, user_id)
    doc = (await db.execute(q)).scalar_one_or_none()
    if doc is None:
        return ""

    parts = [f"**Document** — {(doc.title or 'Untitled').strip()}"]
    desc = (getattr(doc, "description", None) or "").strip()
    if desc:
        if len(desc) > 500:
            desc = desc[:500] + " […]"
        parts += ["", desc]

    # Document content_json is a BlockNote tree; surfacing that meaningfully
    # would require traversing the tree. Phase 1 of this feature ships with
    # title + description only; if a user wants the AI to discuss the body
    # they can paste the relevant snippet manually or we can extend this
    # formatter later.
    return "\n".join(parts)


async def _format_todo(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
) -> str:
    from life_dashboard.domains.todos.models import Todo
    from life_dashboard.core.visibility import apply_visibility_filter

    q = select(Todo).where(Todo.id == todo_id, Todo.household_id == household_id)
    q = apply_visibility_filter(q, Todo, user_id)
    todo = (await db.execute(q)).scalar_one_or_none()
    if todo is None:
        return ""

    parts = [f"**Todo** — {(todo.title or 'Untitled').strip()}"]
    meta_bits: list[str] = [f"Status: {todo.status}"]
    if getattr(todo, "priority", None):
        meta_bits.append(f"Priority: {todo.priority}")
    if getattr(todo, "due_date", None):
        meta_bits.append(f"Due: {todo.due_date.isoformat()}")
    parts.append(" · ".join(meta_bits))

    desc = (getattr(todo, "description", None) or "").strip()
    if desc:
        if len(desc) > 600:
            desc = desc[:600] + " […]"
        parts += ["", desc]
    return "\n".join(parts)


async def _format_goal(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    goal_id: uuid.UUID,
) -> str:
    from life_dashboard.domains.goals.models import Goal
    from life_dashboard.core.visibility import apply_visibility_filter

    q = select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    q = apply_visibility_filter(q, Goal, user_id)
    goal = (await db.execute(q)).scalar_one_or_none()
    if goal is None:
        return ""

    parts = [f"**Goal** — {(goal.title or 'Untitled').strip()}"]
    meta = [f"Status: {goal.status}"]
    if goal.target_value is not None and goal.current_value is not None:
        unit = f" {goal.unit}" if getattr(goal, "unit", None) else ""
        meta.append(f"Progress: {goal.current_value}/{goal.target_value}{unit}")
    parts.append(" · ".join(meta))
    desc = (getattr(goal, "description", None) or "").strip()
    if desc:
        if len(desc) > 500:
            desc = desc[:500] + " […]"
        parts += ["", desc]
    return "\n".join(parts)


async def _format_habit(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    habit_id: uuid.UUID,
) -> str:
    from life_dashboard.domains.habits.models import Habit
    from life_dashboard.core.visibility import apply_visibility_filter

    q = select(Habit).where(Habit.id == habit_id, Habit.household_id == household_id)
    q = apply_visibility_filter(q, Habit, user_id)
    habit = (await db.execute(q)).scalar_one_or_none()
    if habit is None:
        return ""

    parts = [f"**Habit** — {(habit.name or 'Untitled').strip()}"]
    meta = [f"Status: {habit.status}"]
    cadence = getattr(habit, "cadence", None) or getattr(habit, "frequency", None)
    if cadence:
        meta.append(f"Cadence: {cadence}")
    parts.append(" · ".join(meta))
    desc = (getattr(habit, "description", None) or "").strip()
    if desc:
        if len(desc) > 400:
            desc = desc[:400] + " […]"
        parts += ["", desc]
    return "\n".join(parts)


# ── Dispatch ──────────────────────────────────────────────────────────────────

_FORMATTERS = {
    "note": _format_note,
    "recipe": _format_recipe,
    "document": _format_document,
    "todo": _format_todo,
    "goal": _format_goal,
    "habit": _format_habit,
}


async def resolve_chat_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    ref: ChatContextRef | None,
) -> str:
    """Resolve a ChatContextRef to a markdown block, or "" if not accessible.

    Wrapped in a single try/except: a buggy formatter or a stale ref must
    NEVER break the chat flow. Visibility-failure is silent by design —
    same shape as "not accessible".
    """
    if ref is None:
        return ""
    formatter = _FORMATTERS.get(ref.type)
    if formatter is None:
        return ""
    try:
        body = await formatter(db, user_id, household_id, ref.id)
    except Exception:
        logger.exception(
            "Chat context resolver failed for ref %s/%s — proceeding without context",
            ref.type, ref.id,
        )
        return ""
    if not body.strip():
        return ""
    return (
        "## What the user is currently viewing\n\n"
        + "The user is in the app, looking at the resource below. When they "
        + "say 'this' or 'it' without context, they likely mean this resource.\n\n"
        + body
    )
