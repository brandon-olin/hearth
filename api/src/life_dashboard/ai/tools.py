"""AI tool definitions and execution.

Each tool corresponds to a database query the AI can trigger. Tools are
household-scoped — the AI can only see data the requesting user can see.

Adding a new tool:
  1. Add an entry to TOOL_DEFINITIONS (Anthropic tool schema).
  2. Add a Pydantic input model (ToolInput subclass) below the definitions.
  3. Add a matching branch in execute_tool().

Input validation pattern
------------------------
Each write tool (and any read tool with non-trivial inputs) has a Pydantic
model that validates the raw dict Claude sends.  On ValidationError the
handler returns a structured error dict that tells the model exactly what
was wrong and how to fix it — the model can then retry with correct inputs
rather than silently failing.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Input validation helpers ──────────────────────────────────────────────────

def _validation_error_response(exc: PydanticValidationError, tool_name: str) -> dict:
    """Convert a Pydantic ValidationError into a structured error dict that
    gives the model enough context to retry with corrected inputs."""
    errors = []
    for e in exc.errors():
        loc = " → ".join(str(p) for p in e["loc"]) if e["loc"] else "(root)"
        errors.append({"field": loc, "problem": e["msg"], "input": e.get("input")})
    return {
        "error": f"Input validation failed for tool '{tool_name}'",
        "fields": errors,
        "hint": "Fix the listed fields and retry the tool call.",
    }

# ── Tool definitions (Anthropic format) ──────────────────────────────────────

TOOL_DEFINITIONS: list[dict] = [
    # ── Write tools ───────────────────────────────────────────────────────────
    {
        "name": "create_workout",
        "description": (
            "Create a new workout session with optional exercise entries. "
            "Use when the user asks to log a workout, add exercise data, or migrate "
            "workout history from documents. Include all exercises for a single session "
            "in one call. Always confirm the date, name, and entry count before calling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_date": {
                    "type": "string",
                    "description": "Date of the workout (YYYY-MM-DD).",
                },
                "name": {
                    "type": "string",
                    "description": "Optional session name (e.g. 'Upper A', 'HIT', 'Long run').",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional free-text notes about the session.",
                },
                "entries": {
                    "type": "array",
                    "description": "Exercise entries for this session.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Exercise name.",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["strength", "cardio", "hiit", "flexibility", "other"],
                                "description": "Exercise category.",
                            },
                            "metrics": {
                                "type": "object",
                                "description": (
                                    "Performance data. Shape depends on exercise type:\n"
                                    "  strength → {\"sets\": [{\"weight_lbs\": 135, \"reps\": 8}, {\"weight_lbs\": 145, \"reps\": 6}]}\n"
                                    "    Each set is its own object with its own weight and rep count — never average or flatten.\n"
                                    "  cardio   → {\"duration_minutes\": 30, \"distance_km\": 5.0}\n"
                                    "  hiit     → {\"duration_minutes\": 20}\n"
                                    "  flexibility / other → omit metrics or pass {}\n"
                                    "All weights must be in lbs. Convert kg → lbs by multiplying by 2.205."
                                ),
                            },
                            "notes": {
                                "type": "string",
                                "description": "Optional notes for this exercise.",
                            },
                        },
                        "required": ["name", "type"],
                    },
                },
            },
            "required": ["workout_date"],
        },
    },
    {
        "name": "delete_workout",
        "description": (
            "Permanently delete a workout session and all its exercise entries. "
            "Use only when the user explicitly asks to remove a workout, "
            "or to undo a workout that was just created incorrectly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "UUID of the workout to delete.",
                },
            },
            "required": ["workout_id"],
        },
    },
    # ── Read tools ────────────────────────────────────────────────────────────
    {
        "name": "list_workouts",
        "description": (
            "List the user's workout sessions. Use when asked about exercise history, "
            "recent workouts, fitness activity, or training logs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD). Defaults to 30 days ago if omitted.",
                },
                "to_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD). Defaults to today if omitted.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of workouts to return (default 10, max 50).",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "list_todos",
        "description": (
            "List the user's tasks and to-dos. Use when asked about tasks, chores, "
            "what needs to be done, or pending work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "Filter by status. Omit to return all statuses.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of todos to return (default 20).",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "list_habits",
        "description": (
            "List the user's tracked habits. Use when asked about habits, routines, "
            "streaks, or recurring behaviours."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "archived"],
                    "description": "Filter by status. Omit to return active habits only.",
                },
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "list_goals",
        "description": (
            "List the user's goals. Use when asked about goals, objectives, "
            "milestones, or what they are working towards."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_notes",
        "description": (
            "Search or list the user's notes. Use when asked about notes, journal "
            "entries, or written content. Provide a query to search by keyword."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search across note titles and content.",
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "create_note",
        "description": (
            "Create a new note. Use when the user wants to capture an idea, write a "
            "journal entry, or save a piece of text as a note. Confirm the title before calling. "
            "Content can be provided as plain markdown text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Note title (required)."},
                "content_md": {
                    "type": "string",
                    "description": "Note body as plain markdown text.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_note",
        "description": (
            "Update an existing note's title or content. Use when the user wants to "
            "edit, append to, or rename a note. Only send fields that need to change. "
            "Get the note_id from list_notes first if you don't have it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "UUID of the note to update."},
                "title": {"type": "string", "description": "New title for the note."},
                "content_md": {
                    "type": "string",
                    "description": "New body content as plain markdown. Replaces existing content.",
                },
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": (
            "List the user's calendar events. Use when asked about upcoming events, "
            "schedule, appointments, or what is planned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD). Defaults to today if omitted.",
                },
                "to_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD). Defaults to 30 days from now if omitted.",
                },
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_recipes",
        "description": (
            "Search or list the user's saved recipes. Use when asked about recipes, "
            "meal ideas, or cooking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search by recipe name.",
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "list_contacts",
        "description": (
            "Search or list the household's contacts. Use when asked about people, "
            "addresses, phone numbers, birthdays, or any person in the contacts list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search by name or organisation.",
                },
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "list_grocery_lists",
        "description": (
            "List the household's grocery lists and their items. Use when asked about "
            "shopping lists, groceries, what needs to be bought, or store runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "archived"],
                    "description": "Filter by status. Omit to return active lists.",
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "get_documents",
        "description": (
            "Fetch the full content of one or more documents by their IDs. "
            "Use this after list_documents or search_documents has given you document IDs "
            "and you need to read the actual body text. Accepts up to 5 IDs at once."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of document UUIDs to fetch (max 5).",
                },
            },
            "required": ["ids"],
        },
    },
    {
        "name": "list_documents",
        "description": (
            "Browse the user's document library. Returns document titles and structure. "
            "Use when asked to find a document by name or explore what documents exist. "
            "For searching document *content*, use search_documents instead. "
            "Documents are organised in a tree via parent_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional filter by title keyword.",
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "search_documents",
        "description": (
            "Full-text search across document titles and content. Use when asked for "
            "specific information that might be written in a document — health notes, "
            "workout logs, journal entries, reference material, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in document titles and body text.",
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    # ── Projects ──────────────────────────────────────────────────────────────
    {
        "name": "list_projects",
        "description": (
            "List the household's projects. Use when asked about projects, areas of focus, "
            "initiatives, or what the user is currently working on. "
            "Returns name, status, due date, and whether the project is pinned to the nav."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["backlog", "active", "on_deck", "in_progress", "complete", "archived"],
                    "description": "Filter by status. Omit to return all non-archived projects.",
                },
                "root_only": {
                    "type": "boolean",
                    "description": "If true, return only top-level projects (no sub-projects). Default false.",
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "create_project",
        "description": (
            "Create a new project. Use when the user wants to set up a new project, "
            "area of focus, or initiative. Confirm the name and status before calling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name (required)."},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["backlog", "active", "on_deck", "in_progress", "complete", "archived"],
                    "description": "Default 'active'.",
                },
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
                "parent_id": {
                    "type": "string",
                    "description": "UUID of a parent project if this is a sub-project.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_project",
        "description": (
            "Update an existing project. Use to rename it, change its status, set a due date, "
            "or move it to a different parent. Only send fields that need to change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "UUID of the project to update."},
                "name": {"type": "string", "description": "New project name."},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["backlog", "active", "on_deck", "in_progress", "complete", "archived"],
                },
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
            },
            "required": ["project_id"],
        },
    },
    # ── Todos ─────────────────────────────────────────────────────────────────
    {
        "name": "create_todo",
        "description": (
            "Create a new to-do item. Use when the user wants to add a task, chore, "
            "or reminder. Confirm the title before calling. "
            "Defaults: the task is automatically assigned to the current user and placed "
            "in the household's default To-dos project unless project_id is explicitly provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title (required)."},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "Default 'pending'.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
                "project_id": {
                    "type": "string",
                    "description": (
                        "UUID of a specific project. Omit to use the default To-dos project."
                    ),
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_todo",
        "description": (
            "Update an existing to-do item. Use to mark it done, change its priority, "
            "update its due date, or move it to a different project. "
            "Only send fields that need to change. "
            "To mark a task complete, set status to 'done'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to update."},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
                "project_id": {"type": "string", "description": "UUID of the project."},
            },
            "required": ["todo_id"],
        },
    },
    {
        "name": "delete_todo",
        "description": (
            "Permanently delete a to-do item. "
            "Only use when the user explicitly asks to delete (not just complete) a task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to delete."},
            },
            "required": ["todo_id"],
        },
    },
    # ── Goals ─────────────────────────────────────────────────────────────────
    {
        "name": "create_goal",
        "description": (
            "Create a new goal. Use when the user wants to set a target or objective "
            "they are working towards. Confirm the title before calling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Goal title (required)."},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "paused", "archived"],
                    "description": "Default 'active'.",
                },
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "target_value": {
                    "type": "number",
                    "description": "Numeric target (e.g. 100 for '100 pushups a day').",
                },
                "current_value": {"type": "number", "description": "Current progress value."},
                "unit": {"type": "string", "description": "Unit of measure (e.g. 'kg', 'km', 'sessions')."},
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_goal",
        "description": (
            "Update an existing goal. Use to mark it complete, update progress, "
            "change its status or due date. Only send fields that need to change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string", "description": "UUID of the goal to update."},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "paused", "archived"],
                },
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "target_value": {"type": "number"},
                "current_value": {"type": "number"},
                "unit": {"type": "string"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
            },
            "required": ["goal_id"],
        },
    },
    {
        "name": "delete_goal",
        "description": (
            "Permanently delete a goal. "
            "Only use when the user explicitly asks to delete (not just complete or archive) a goal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string", "description": "UUID of the goal to delete."},
            },
            "required": ["goal_id"],
        },
    },
    # ── Calendar events ───────────────────────────────────────────────────────
    {
        "name": "create_calendar_event",
        "description": (
            "Create a new calendar event. Use when the user wants to schedule something. "
            "Confirm the title, date, and time before calling. "
            "starts_at is required; ends_at is optional but recommended."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title (required)."},
                "starts_at": {
                    "type": "string",
                    "description": "ISO 8601 datetime string (e.g. '2026-05-15T14:00:00'). Required.",
                },
                "ends_at": {
                    "type": "string",
                    "description": "ISO 8601 datetime string. Must be after starts_at.",
                },
                "all_day": {
                    "type": "boolean",
                    "description": "True for all-day events. Default false.",
                },
                "description": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title", "starts_at"],
        },
    },
    {
        "name": "update_calendar_event",
        "description": (
            "Update an existing calendar event. Use to reschedule, rename, or add details. "
            "Only send fields that need to change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "UUID of the event to update."},
                "title": {"type": "string"},
                "starts_at": {"type": "string", "description": "ISO 8601 datetime string."},
                "ends_at": {"type": "string", "description": "ISO 8601 datetime string."},
                "all_day": {"type": "boolean"},
                "description": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": (
            "Delete a calendar event. "
            "Only use when the user explicitly asks to remove or cancel an event."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "UUID of the event to delete."},
            },
            "required": ["event_id"],
        },
    },
    # ── Habits ────────────────────────────────────────────────────────────────
    {
        "name": "log_habit_occurrence",
        "description": (
            "Log a habit occurrence for a specific date — marking it completed, skipped, "
            "or resetting it to pending. This is the primary way to record daily habit activity. "
            "If an occurrence already exists for that date it will be updated; otherwise one is created. "
            "Use when the user says they did (or didn't do) a habit on a given day."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "habit_id": {
                    "type": "string",
                    "description": "UUID of the habit. Use list_habits to find the ID.",
                },
                "scheduled_date": {
                    "type": "string",
                    "description": "Date to log the occurrence for (YYYY-MM-DD). Defaults to today if omitted.",
                },
                "status": {
                    "type": "string",
                    "enum": ["completed", "skipped", "pending"],
                    "description": "Default 'completed'.",
                },
                "notes": {"type": "string", "description": "Optional notes about this occurrence."},
            },
            "required": ["habit_id"],
        },
    },
]


# ── Tool input schemas ────────────────────────────────────────────────────────
# Pydantic models for write tools (and any read tool with non-trivial inputs).
# These are validated before any DB work happens, so errors are caught at the
# tool boundary and returned as structured hints rather than cryptic exceptions.

class _ExerciseEntryInput(BaseModel):
    name: str = Field(min_length=1)
    type: str = Field(pattern=r"^(strength|cardio|hiit|flexibility|other)$")
    metrics: dict[str, Any] | None = None
    notes: str | None = None

    @field_validator("type")
    @classmethod
    def normalise_type(cls, v: str) -> str:
        return v.lower().strip()


class _CreateWorkoutInput(BaseModel):
    workout_date: date
    name: str | None = None
    notes: str | None = None
    entries: list[_ExerciseEntryInput] = []

    @field_validator("workout_date", mode="before")
    @classmethod
    def parse_date(cls, v: Any) -> date:
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")
        raise ValueError(f"Expected a date string (YYYY-MM-DD), got {type(v).__name__}")


class _DeleteWorkoutInput(BaseModel):
    workout_id: uuid.UUID

    @field_validator("workout_id", mode="before")
    @classmethod
    def parse_uuid(cls, v: Any) -> uuid.UUID:
        try:
            return uuid.UUID(str(v))
        except (ValueError, AttributeError):
            raise ValueError(f"Expected a valid UUID, got {v!r}")


def _parse_uuid_field(v: Any) -> uuid.UUID:
    """Reusable UUID coercer for field_validator(mode='before')."""
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        raise ValueError(f"Expected a valid UUID, got {v!r}")


class _GetDocumentsInput(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5)

    @field_validator("ids", mode="before")
    @classmethod
    def coerce_ids(cls, v: Any) -> list[uuid.UUID]:
        if not isinstance(v, list):
            raise ValueError("ids must be an array of UUID strings")
        result = []
        for i, item in enumerate(v):
            try:
                result.append(uuid.UUID(str(item)))
            except (ValueError, AttributeError):
                raise ValueError(f"ids[{i}]: {item!r} is not a valid UUID")
        return result


# ── Project input models ──────────────────────────────────────────────────────

_ProjectStatus = Literal["backlog", "active", "on_deck", "in_progress", "complete", "archived"]


class _CreateProjectInput(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    status: _ProjectStatus = "active"
    due_date: date | None = None
    parent_id: uuid.UUID | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")

    @field_validator("parent_id", mode="before")
    @classmethod
    def parse_parent_id(cls, v: Any) -> uuid.UUID | None:
        return None if v is None else _parse_uuid_field(v)


class _UpdateProjectInput(BaseModel):
    project_id: uuid.UUID
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: _ProjectStatus | None = None
    due_date: date | None = None

    @field_validator("project_id", mode="before")
    @classmethod
    def parse_project_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")


# ── Todo input models ─────────────────────────────────────────────────────────

_TodoStatus = Literal["pending", "in_progress", "done", "cancelled"]
_TodoPriority = Literal["low", "medium", "high"]


class _CreateTodoInput(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    status: _TodoStatus = "pending"
    priority: _TodoPriority | None = None
    due_date: date | None = None
    project_id: uuid.UUID | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")

    @field_validator("project_id", mode="before")
    @classmethod
    def parse_project_id(cls, v: Any) -> uuid.UUID | None:
        return None if v is None else _parse_uuid_field(v)


class _UpdateTodoInput(BaseModel):
    todo_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: _TodoStatus | None = None
    priority: _TodoPriority | None = None
    due_date: date | None = None
    project_id: uuid.UUID | None = None

    @field_validator("todo_id", mode="before")
    @classmethod
    def parse_todo_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")

    @field_validator("project_id", mode="before")
    @classmethod
    def parse_project_id(cls, v: Any) -> uuid.UUID | None:
        return None if v is None else _parse_uuid_field(v)


class _DeleteTodoInput(BaseModel):
    todo_id: uuid.UUID

    @field_validator("todo_id", mode="before")
    @classmethod
    def parse_todo_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)


# ── Goal input models ─────────────────────────────────────────────────────────

_GoalStatus = Literal["active", "completed", "paused", "archived"]
_GoalPriority = Literal["low", "medium", "high"]


class _CreateGoalInput(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    status: _GoalStatus = "active"
    priority: _GoalPriority | None = None
    target_value: float | None = None
    current_value: float | None = None
    unit: str | None = None
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")


class _UpdateGoalInput(BaseModel):
    goal_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: _GoalStatus | None = None
    priority: _GoalPriority | None = None
    target_value: float | None = None
    current_value: float | None = None
    unit: str | None = None
    due_date: date | None = None

    @field_validator("goal_id", mode="before")
    @classmethod
    def parse_goal_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")


class _DeleteGoalInput(BaseModel):
    goal_id: uuid.UUID

    @field_validator("goal_id", mode="before")
    @classmethod
    def parse_goal_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)


# ── Calendar event input models ───────────────────────────────────────────────

def _parse_datetime_field(v: Any) -> datetime:
    """Coerce a string to an aware datetime (UTC if no tz supplied)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError(f"Expected ISO 8601 datetime string, got {v!r}")
    raise ValueError(f"Expected a datetime string, got {type(v).__name__}")


class _CreateCalendarEventInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    description: str | None = None
    location: str | None = None

    @field_validator("starts_at", mode="before")
    @classmethod
    def parse_starts_at(cls, v: Any) -> datetime:
        return _parse_datetime_field(v)

    @field_validator("ends_at", mode="before")
    @classmethod
    def parse_ends_at(cls, v: Any) -> datetime | None:
        return None if v is None else _parse_datetime_field(v)

    @model_validator(mode="after")
    def ends_after_starts(self) -> "_CreateCalendarEventInput":
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class _UpdateCalendarEventInput(BaseModel):
    event_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=500)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    description: str | None = None
    location: str | None = None

    @field_validator("event_id", mode="before")
    @classmethod
    def parse_event_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)

    @field_validator("starts_at", mode="before")
    @classmethod
    def parse_starts_at(cls, v: Any) -> datetime | None:
        return None if v is None else _parse_datetime_field(v)

    @field_validator("ends_at", mode="before")
    @classmethod
    def parse_ends_at(cls, v: Any) -> datetime | None:
        return None if v is None else _parse_datetime_field(v)


class _DeleteCalendarEventInput(BaseModel):
    event_id: uuid.UUID

    @field_validator("event_id", mode="before")
    @classmethod
    def parse_event_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)


# ── Habit occurrence input model ──────────────────────────────────────────────

_OccurrenceStatus = Literal["completed", "skipped", "pending"]


class _LogHabitOccurrenceInput(BaseModel):
    habit_id: uuid.UUID
    scheduled_date: date = Field(default_factory=date.today)
    status: _OccurrenceStatus = "completed"
    notes: str | None = None

    @field_validator("habit_id", mode="before")
    @classmethod
    def parse_habit_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)

    @field_validator("scheduled_date", mode="before")
    @classmethod
    def parse_date(cls, v: Any) -> date:
        if v is None:
            return date.today()
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")


# ── Note input models ─────────────────────────────────────────────────────────

class _CreateNoteInput(BaseModel):
    title: str = Field(min_length=1)
    content_md: str | None = None


class _UpdateNoteInput(BaseModel):
    note_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1)
    content_md: str | None = None

    @field_validator("note_id", mode="before")
    @classmethod
    def parse_note_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)


# ── Tool execution ────────────────────────────────────────────────────────────

async def execute_tool(
    db: AsyncSession,
    tool_name: str,
    tool_input: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    """Dispatch a tool call to the appropriate service and return a JSON-safe dict.

    Results are serialised with json.dumps() and returned to Claude as tool_result.
    Write tools require user_id in addition to household_id.

    Validation errors from Pydantic input models are returned as structured
    error dicts so the model can retry with corrected inputs.
    """
    try:
        # ── Write tools ───────────────────────────────────────────────────────
        if tool_name == "create_workout":
            return await _create_workout(db, tool_input, household_id, user_id)
        if tool_name == "delete_workout":
            return await _delete_workout(db, tool_input, household_id)
        # ── Read tools ────────────────────────────────────────────────────────
        if tool_name == "list_workouts":
            return await _list_workouts(db, tool_input, household_id)
        if tool_name == "list_todos":
            return await _list_todos(db, tool_input, household_id)
        if tool_name == "list_habits":
            return await _list_habits(db, tool_input, household_id)
        if tool_name == "list_goals":
            return await _list_goals(db, tool_input, household_id)
        if tool_name == "list_notes":
            return await _list_notes(db, tool_input, household_id)
        # ── Notes ─────────────────────────────────────────────────────────────
        if tool_name == "create_note":
            return await _create_note(db, tool_input, household_id, user_id)
        if tool_name == "update_note":
            return await _update_note(db, tool_input, household_id)
        if tool_name == "list_calendar_events":
            return await _list_calendar_events(db, tool_input, household_id)
        if tool_name == "list_recipes":
            return await _list_recipes(db, tool_input, household_id)
        if tool_name == "list_contacts":
            return await _list_contacts(db, tool_input, household_id)
        if tool_name == "list_grocery_lists":
            return await _list_grocery_lists(db, tool_input, household_id)
        if tool_name == "get_documents":
            return await _get_documents(db, tool_input, household_id)
        if tool_name == "list_documents":
            return await _list_documents(db, tool_input, household_id)
        if tool_name == "search_documents":
            return await _search_documents(db, tool_input, household_id)
        # ── Projects ──────────────────────────────────────────────────────────
        if tool_name == "list_projects":
            return await _list_projects(db, tool_input, household_id)
        if tool_name == "create_project":
            return await _create_project(db, tool_input, household_id, user_id)
        if tool_name == "update_project":
            return await _update_project(db, tool_input, household_id)
        # ── Todos ─────────────────────────────────────────────────────────────
        if tool_name == "create_todo":
            return await _create_todo(db, tool_input, household_id, user_id)
        if tool_name == "update_todo":
            return await _update_todo(db, tool_input, household_id)
        if tool_name == "delete_todo":
            return await _delete_todo(db, tool_input, household_id)
        # ── Goals ─────────────────────────────────────────────────────────────
        if tool_name == "create_goal":
            return await _create_goal(db, tool_input, household_id, user_id)
        if tool_name == "update_goal":
            return await _update_goal(db, tool_input, household_id)
        if tool_name == "delete_goal":
            return await _delete_goal(db, tool_input, household_id)
        # ── Calendar events ───────────────────────────────────────────────────
        if tool_name == "create_calendar_event":
            return await _create_calendar_event(db, tool_input, household_id, user_id)
        if tool_name == "update_calendar_event":
            return await _update_calendar_event(db, tool_input, household_id)
        if tool_name == "delete_calendar_event":
            return await _delete_calendar_event(db, tool_input, household_id)
        # ── Habits ────────────────────────────────────────────────────────────
        if tool_name == "log_habit_occurrence":
            return await _log_habit_occurrence(db, tool_input, household_id)
        return {
            "error": f"Unknown tool: {tool_name!r}",
            "hint": "Only call tools that are listed in the tools array.",
        }
    except PydanticValidationError as exc:
        # Validation errors are already structured — return them directly so
        # the model can see exactly which field was wrong and retry.
        return _validation_error_response(exc, tool_name)
    except Exception:
        logger.exception("Tool execution failed: %s", tool_name)
        return {
            "error": f"Tool '{tool_name}' raised an unexpected error.",
            "hint": "Check that all required fields are present and correctly typed.",
        }


# ── Individual tool handlers ──────────────────────────────────────────────────

async def _create_workout(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.workouts import service as svc
    from life_dashboard.domains.workouts.schemas import ExerciseEntryCreate, WorkoutCreate

    # Validate with Pydantic — raises PydanticValidationError on bad input,
    # which execute_tool catches and returns as a structured error.
    validated = _CreateWorkoutInput.model_validate(inp)

    entries = [
        ExerciseEntryCreate(
            name=e.name,
            type=e.type,
            sort_order=i,
            metrics=e.metrics,
            notes=e.notes,
        )
        for i, e in enumerate(validated.entries)
    ]

    data = WorkoutCreate(
        workout_date=validated.workout_date,
        name=validated.name,
        notes=validated.notes,
        entries=entries,
    )

    result = await svc.create_workout(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(result.id),
        "workout_date": str(result.workout_date),
        "name": result.name,
        "entries_created": len(result.entries),
    }


async def _delete_workout(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.workouts import service as svc

    validated = _DeleteWorkoutInput.model_validate(inp)

    deleted = await svc.delete_workout(db, validated.workout_id, household_id)
    if not deleted:
        return {
            "error": "Workout not found or already deleted.",
            "hint": f"Confirm the workout_id {str(validated.workout_id)!r} exists via list_workouts.",
        }
    return {"ok": True, "deleted_id": str(validated.workout_id)}


async def _list_workouts(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.workouts import service as svc
    from datetime import timedelta

    today = date.today()
    from_date = _parse_date(inp.get("from_date")) or (today - timedelta(days=30))
    to_date = _parse_date(inp.get("to_date")) or today
    limit = min(int(inp.get("limit", 10)), 25)

    result = await svc.list_workouts(
        db, household_id, from_date=from_date, to_date=to_date, limit=limit
    )
    return {
        "total": result.total,
        "workouts": [
            {
                "id": str(w.id),
                "date": str(w.workout_date),
                "name": w.name,
                "notes": _truncate(w.notes, 300),
            }
            for w in result.items
        ],
    }


async def _list_todos(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.todos import service as svc

    status = inp.get("status")
    limit = min(int(inp.get("limit", 20)), 50)

    result = await svc.list_todos(db, household_id, status=status, limit=limit)
    return {
        "total": result.total,
        "todos": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status,
                "due_date": str(t.due_date) if t.due_date else None,
                "priority": t.priority,
                "notes": _truncate(t.notes, 200),
            }
            for t in result.items
        ],
    }


async def _list_habits(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.habits import service as svc

    status = inp.get("status", "active")
    limit = min(int(inp.get("limit", 20)), 50)

    result = await svc.list_habits(db, household_id, status=status, limit=limit)
    return {
        "total": result.total,
        "habits": [
            {
                "id": str(h.id),
                "name": h.name,
                "description": _truncate(h.description, 150),
                "frequency": h.frequency,
                "status": h.status,
                "streak": getattr(h, "streak", None),
            }
            for h in result.items
        ],
    }


async def _list_goals(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.goals import service as svc

    limit = min(int(inp.get("limit", 20)), 50)

    result = await svc.list_goals(db, household_id, limit=limit)
    return {
        "total": result.total,
        "goals": [
            {
                "id": str(g.id),
                "title": g.title,
                "description": _truncate(g.description, 200),
                "status": g.status,
                "target_date": str(g.target_date) if g.target_date else None,
            }
            for g in result.items
        ],
    }


async def _list_notes(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.notes import service as svc

    query = inp.get("query") or None
    limit = min(int(inp.get("limit", 10)), 25)

    result = await svc.list_notes(db, household_id, q=query, limit=limit)
    return {
        "total": result.total,
        "notes": [
            {
                "id": str(n.id),
                "title": n.title,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in result.items
        ],
    }


async def _list_calendar_events(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.calendar_events import service as svc
    from datetime import timedelta

    today = date.today()
    from_dt = _parse_datetime(inp.get("from_date")) or datetime(
        today.year, today.month, today.day, tzinfo=timezone.utc
    )
    to_dt = _parse_datetime(inp.get("to_date")) or (from_dt + timedelta(days=30))
    limit = min(int(inp.get("limit", 20)), 100)

    result = await svc.list_events(
        db, household_id, starts_after=from_dt, starts_before=to_dt, limit=limit
    )
    return {
        "total": result.total,
        "events": [
            {
                "id": str(e.id),
                "title": e.title,
                "starts_at": e.starts_at.isoformat() if e.starts_at else None,
                "ends_at": e.ends_at.isoformat() if e.ends_at else None,
                "all_day": e.all_day,
                "location": getattr(e, "location", None),
                "description": getattr(e, "description", None),
            }
            for e in result.items
        ],
    }


async def _list_recipes(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.recipes import service as svc

    query = inp.get("query") or None
    limit = min(int(inp.get("limit", 10)), 50)

    result = await svc.list_recipes(db, household_id, search=query, limit=limit)
    return {
        "total": result.total,
        "recipes": [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "servings": r.servings,
                "prep_time_minutes": getattr(r, "prep_time_minutes", None),
                "cook_time_minutes": getattr(r, "cook_time_minutes", None),
            }
            for r in result.items
        ],
    }


async def _list_contacts(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.contacts import service as svc

    query = inp.get("query") or None
    limit = min(int(inp.get("limit", 20)), 100)

    result = await svc.list_contacts(db, household_id, search=query, limit=limit)
    return {
        "total": result.total,
        "contacts": [
            {
                "id": str(c.id),
                "name": c.display_name or " ".join(filter(None, [c.given_name, c.family_name])),
                "given_name": c.given_name,
                "family_name": c.family_name,
                "organization": c.organization,
                "job_title": c.job_title,
                "birthday": str(c.birthday) if c.birthday else None,
                "anniversary": str(c.anniversary) if c.anniversary else None,
                "notes": _truncate(c.notes, 200),
                "website": c.website,
                "emails": [{"label": e.label, "address": e.address} for e in c.emails],
                "phones": [{"label": p.label, "number": p.number} for p in c.phones],
                "addresses": [
                    {
                        "label": a.label,
                        "street": a.street,
                        "city": a.city,
                        "state": a.state,
                        "postal_code": a.postal_code,
                        "country": a.country,
                    }
                    for a in c.addresses
                ],
            }
            for c in result.items
        ],
    }


async def _list_grocery_lists(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc

    status = inp.get("status", "active")
    limit = min(int(inp.get("limit", 10)), 50)

    result = await svc.list_grocery_lists(db, household_id, status=status, limit=limit)
    return {
        "total": result.total,
        "grocery_lists": [
            {
                "id": str(gl.id),
                "name": gl.name,
                "store": gl.store,
                "status": gl.status,
                "items": [
                    {
                        "name": item.name,
                        "quantity": str(item.quantity) if item.quantity is not None else None,
                        "unit": item.unit,
                        "category": item.category,
                        "is_checked": item.is_checked,
                        "notes": item.notes,
                    }
                    for item in gl.items
                ],
            }
            for gl in result.items
        ],
    }


async def _get_documents(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.documents import service as svc

    # Validate UUIDs up-front; raises PydanticValidationError on bad input.
    validated = _GetDocumentsInput.model_validate(inp)

    results = []
    for doc_id in validated.ids:
        doc = await svc.get_document(db, doc_id, household_id)
        if doc is None:
            results.append({
                "id": str(doc_id),
                "error": "not found",
                "hint": "Confirm the document ID via list_documents or search_documents.",
            })
        else:
            # Prefer source_markdown; fall back to extracting text from editor_json.
            content = doc.source_markdown or _extract_editor_text(doc.editor_json)
            results.append({
                "id": str(doc.id),
                "title": doc.title,
                "kind": doc.kind if isinstance(doc.kind, str) else doc.kind.value,
                "content": content,
            })

    return {"documents": results}


async def _list_documents(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.documents import service as svc

    query = inp.get("query") or None
    limit = min(int(inp.get("limit", 50)), 200)

    result = await svc.list_documents(db, household_id)

    docs = result.items
    if query:
        q_lower = query.lower()
        docs = [d for d in docs if q_lower in d.title.lower()]
    docs = docs[:limit]

    return {
        "total": len(docs),
        "documents": [
            {
                "id": str(d.id),
                "title": d.title,
                "kind": d.kind if isinstance(d.kind, str) else d.kind.value,
                "parent_id": str(d.parent_id) if d.parent_id else None,
                "description": d.description,
            }
            for d in docs
        ],
    }


async def _search_documents(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.documents import service as svc

    query = inp.get("query", "").strip()
    if not query:
        return {"error": "query is required"}
    limit = min(int(inp.get("limit", 10)), 50)

    result = await svc.search_documents(db, household_id, query, limit=limit)
    return {
        "total": result.total,
        "results": [
            {
                "id": str(r.id),
                "title": r.title,
                "kind": r.kind if isinstance(r.kind, str) else r.kind.value,
                "snippet": r.snippet,
            }
            for r in result.items
        ],
    }


# ── Project handlers ──────────────────────────────────────────────────────────

async def _list_projects(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.projects import service as svc

    status_filter = inp.get("status")
    root_only = bool(inp.get("root_only", False))
    limit = min(int(inp.get("limit", 50)), 200)

    result = await svc.list_projects(
        db,
        household_id,
        root_only=root_only,
        include_archived=(status_filter == "archived"),
    )
    items = result.items
    if status_filter and status_filter != "archived":
        items = [p for p in items if p.status == status_filter]
    items = items[:limit]

    return {
        "total": len(items),
        "projects": [
            {
                "id": str(p.id),
                "name": p.name,
                "description": _truncate(p.description, 200),
                "status": p.status,
                "due_date": str(p.due_date) if p.due_date else None,
                "parent_id": str(p.parent_id) if p.parent_id else None,
                "show_in_nav": p.show_in_nav,
                "is_system": p.is_system,
            }
            for p in items
        ],
    }


async def _create_project(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.projects import service as svc
    from life_dashboard.domains.projects.schemas import ProjectCreate

    validated = _CreateProjectInput.model_validate(inp)
    data = ProjectCreate(
        name=validated.name,
        description=validated.description,
        status=validated.status,
        due_date=validated.due_date,
        parent_id=validated.parent_id,
    )
    project, error = await svc.create_project(db, household_id, user_id, data)
    if error:
        return {"error": error, "hint": "Check that parent_id exists and depth < 7."}
    return {
        "ok": True,
        "id": str(project.id),
        "name": project.name,
        "status": project.status,
    }


async def _update_project(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.projects import service as svc
    from life_dashboard.domains.projects.schemas import ProjectUpdate

    validated = _UpdateProjectInput.model_validate(inp)

    # Only pass fields that were explicitly provided in the input dict.
    update_fields = {
        k: v for k, v in {
            "name": validated.name,
            "description": validated.description,
            "status": validated.status,
            "due_date": validated.due_date,
        }.items()
        if k in inp
    }
    data = ProjectUpdate(**update_fields)
    project, error = await svc.update_project(db, validated.project_id, household_id, data)
    if error == "not_found":
        return {
            "error": "Project not found.",
            "hint": f"Confirm the project_id via list_projects.",
        }
    if error:
        return {"error": error}
    return {
        "ok": True,
        "id": str(project.id),
        "name": project.name,
        "status": project.status,
    }


# ── Todo handlers ─────────────────────────────────────────────────────────────

async def _create_todo(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.todos import service as svc
    from life_dashboard.domains.todos.schemas import TodoCreate
    from life_dashboard.domains.projects.models import Project
    from sqlalchemy import select

    validated = _CreateTodoInput.model_validate(inp)

    # Default: assign to the current user.
    assigned_to = user_id

    # Default: place in the household's system project (To-dos) when no
    # project_id is explicitly provided.
    project_id = validated.project_id
    if project_id is None:
        result = await db.execute(
            select(Project.id).where(
                Project.household_id == household_id,
                Project.is_system.is_(True),
            )
        )
        project_id = result.scalar_one_or_none()

    data = TodoCreate(
        title=validated.title,
        description=validated.description,
        status=validated.status,
        priority=validated.priority,
        due_date=validated.due_date,
        project_id=project_id,
        assigned_to_user_id=assigned_to,
    )
    todo = await svc.create_todo(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(todo.id),
        "title": todo.title,
        "status": todo.status,
        "due_date": str(todo.due_date) if todo.due_date else None,
        "project_id": str(todo.project_id) if todo.project_id else None,
        "assigned_to_user_id": str(todo.assigned_to_user_id) if todo.assigned_to_user_id else None,
    }


async def _update_todo(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.todos import service as svc
    from life_dashboard.domains.todos.schemas import TodoUpdate

    validated = _UpdateTodoInput.model_validate(inp)

    update_fields = {
        k: v for k, v in {
            "title": validated.title,
            "description": validated.description,
            "status": validated.status,
            "priority": validated.priority,
            "due_date": validated.due_date,
            "project_id": validated.project_id,
        }.items()
        if k in inp
    }
    data = TodoUpdate(**update_fields)
    todo = await svc.update_todo(db, validated.todo_id, household_id, data)
    if todo is None:
        return {
            "error": "Todo not found.",
            "hint": "Confirm the todo_id via list_todos.",
        }
    return {
        "ok": True,
        "id": str(todo.id),
        "title": todo.title,
        "status": todo.status,
    }


async def _delete_todo(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.todos import service as svc

    validated = _DeleteTodoInput.model_validate(inp)
    deleted = await svc.delete_todo(db, validated.todo_id, household_id)
    if not deleted:
        return {
            "error": "Todo not found or already deleted.",
            "hint": "Confirm the todo_id via list_todos.",
        }
    return {"ok": True, "deleted_id": str(validated.todo_id)}


# ── Goal handlers ─────────────────────────────────────────────────────────────

async def _create_goal(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.goals import service as svc
    from life_dashboard.domains.goals.schemas import GoalCreate
    from decimal import Decimal

    validated = _CreateGoalInput.model_validate(inp)
    data = GoalCreate(
        title=validated.title,
        description=validated.description,
        status=validated.status,
        priority=validated.priority,
        target_value=Decimal(str(validated.target_value)) if validated.target_value is not None else None,
        current_value=Decimal(str(validated.current_value)) if validated.current_value is not None else None,
        unit=validated.unit,
        due_date=validated.due_date,
    )
    goal = await svc.create_goal(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(goal.id),
        "title": goal.title,
        "status": goal.status,
    }


async def _update_goal(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.goals import service as svc
    from life_dashboard.domains.goals.schemas import GoalUpdate
    from decimal import Decimal

    validated = _UpdateGoalInput.model_validate(inp)

    update_fields: dict[str, Any] = {}
    for field in ("title", "description", "status", "priority", "unit", "due_date"):
        if field in inp:
            update_fields[field] = getattr(validated, field)
    for num_field in ("target_value", "current_value"):
        if num_field in inp:
            raw = getattr(validated, num_field)
            update_fields[num_field] = Decimal(str(raw)) if raw is not None else None

    data = GoalUpdate(**update_fields)
    goal = await svc.update_goal(db, validated.goal_id, household_id, data)
    if goal is None:
        return {
            "error": "Goal not found.",
            "hint": "Confirm the goal_id via list_goals.",
        }
    return {
        "ok": True,
        "id": str(goal.id),
        "title": goal.title,
        "status": goal.status,
    }


async def _delete_goal(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.goals import service as svc

    validated = _DeleteGoalInput.model_validate(inp)
    deleted = await svc.delete_goal(db, validated.goal_id, household_id)
    if not deleted:
        return {
            "error": "Goal not found or already deleted.",
            "hint": "Confirm the goal_id via list_goals.",
        }
    return {"ok": True, "deleted_id": str(validated.goal_id)}


# ── Calendar event handlers ───────────────────────────────────────────────────

async def _create_calendar_event(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.calendar_events import service as svc
    from life_dashboard.domains.calendar_events.schemas import CalendarEventCreate

    validated = _CreateCalendarEventInput.model_validate(inp)
    data = CalendarEventCreate(
        title=validated.title,
        starts_at=validated.starts_at,
        ends_at=validated.ends_at,
        all_day=validated.all_day,
        description=validated.description,
        location=validated.location,
    )
    event = await svc.create_event(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(event.id),
        "title": event.title,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
    }


async def _update_calendar_event(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.calendar_events import service as svc
    from life_dashboard.domains.calendar_events.schemas import CalendarEventUpdate

    validated = _UpdateCalendarEventInput.model_validate(inp)

    update_fields: dict[str, Any] = {}
    for field in ("title", "starts_at", "ends_at", "all_day", "description", "location"):
        if field in inp:
            update_fields[field] = getattr(validated, field)

    data = CalendarEventUpdate(**update_fields)
    event = await svc.update_event(db, validated.event_id, household_id, data)
    if event is None:
        return {
            "error": "Calendar event not found.",
            "hint": "Confirm the event_id via list_calendar_events.",
        }
    return {
        "ok": True,
        "id": str(event.id),
        "title": event.title,
        "starts_at": event.starts_at.isoformat(),
    }


async def _delete_calendar_event(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.calendar_events import service as svc

    validated = _DeleteCalendarEventInput.model_validate(inp)
    deleted = await svc.delete_event(db, validated.event_id, household_id)
    if not deleted:
        return {
            "error": "Calendar event not found or already deleted.",
            "hint": "Confirm the event_id via list_calendar_events.",
        }
    return {"ok": True, "deleted_id": str(validated.event_id)}


# ── Habit occurrence handler ──────────────────────────────────────────────────

async def _log_habit_occurrence(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    """Idempotent: creates an occurrence if none exists for the date, updates if one does."""
    from life_dashboard.domains.habits import service as svc
    from life_dashboard.domains.habits.schemas import OccurrenceCreate, OccurrenceUpdate
    from sqlalchemy import select
    from life_dashboard.domains.habits.models import HabitOccurrence, Habit

    validated = _LogHabitOccurrenceInput.model_validate(inp)

    # Verify the habit belongs to this household.
    habit_check = await db.execute(
        select(Habit.id).where(
            Habit.id == validated.habit_id,
            Habit.household_id == household_id,
        )
    )
    if habit_check.scalar_one_or_none() is None:
        return {
            "error": "Habit not found.",
            "hint": "Confirm the habit_id via list_habits.",
        }

    # Check for an existing occurrence on this date.
    existing = await db.execute(
        select(HabitOccurrence).where(
            HabitOccurrence.habit_id == validated.habit_id,
            HabitOccurrence.scheduled_date == validated.scheduled_date,
        )
    )
    occurrence_row = existing.scalar_one_or_none()

    if occurrence_row is not None:
        data = OccurrenceUpdate(status=validated.status, notes=validated.notes)
        occurrence = await svc.update_occurrence(db, occurrence_row.id, validated.habit_id, data)
        action = "updated"
    else:
        data = OccurrenceCreate(
            scheduled_date=validated.scheduled_date,
            status=validated.status,
            notes=validated.notes,
        )
        occurrence = await svc.create_occurrence(db, validated.habit_id, data)
        action = "created"

    return {
        "ok": True,
        "action": action,
        "id": str(occurrence.id),
        "habit_id": str(validated.habit_id),
        "scheduled_date": str(validated.scheduled_date),
        "status": occurrence.status,
    }


# ── Note handlers ────────────────────────────────────────────────────────────

async def _create_note(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.notes import service as svc
    from life_dashboard.domains.notes.schemas import NoteCreate

    validated = _CreateNoteInput.model_validate(inp)
    data = NoteCreate(
        title=validated.title,
        content_md=validated.content_md,
    )
    note = await svc.create_note(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(note.id),
        "title": note.title,
        "created_at": note.created_at.isoformat(),
    }


async def _update_note(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.notes import service as svc
    from life_dashboard.domains.notes.schemas import NoteUpdate

    validated = _UpdateNoteInput.model_validate(inp)

    # Only pass fields that were explicitly provided in the tool call.
    update_fields: dict[str, Any] = {}
    if "title" in inp:
        update_fields["title"] = validated.title
    if "content_md" in inp:
        update_fields["content_md"] = validated.content_md

    data = NoteUpdate(**update_fields)
    note = await svc.update_note(db, validated.note_id, household_id, data)
    if note is None:
        return {
            "error": "Note not found.",
            "hint": "Confirm the note_id via list_notes.",
        }
    return {
        "ok": True,
        "id": str(note.id),
        "title": note.title,
        "updated_at": note.updated_at.isoformat(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_editor_text(editor_json: dict | list | None) -> str:
    """Extract plain text from BlockNote / ProseMirror editor JSON.

    BlockNote stores documents as a JSON array of block objects.  Each block
    has a ``content`` list of inline nodes (type "text") and a ``children``
    list of nested blocks.  This function walks the tree recursively and
    returns a newline-joined plain-text representation suitable for passing to
    the AI.

    Handles two common top-level shapes:
      - list  — direct BlockNote block array
      - dict  — ProseMirror doc node with a ``content`` key (or similar wrapper)
    """
    if not editor_json:
        return ""

    def _inline_text(inline: dict) -> str:
        if not isinstance(inline, dict):
            return ""
        itype = inline.get("type", "")
        if itype == "text":
            return inline.get("text", "")
        if itype == "link":
            # Link nodes wrap their label in a nested content array.
            return "".join(_inline_text(i) for i in inline.get("content", []))
        return ""

    def _block_lines(block: dict) -> list[str]:
        """Return one or more text lines for a block and its children."""
        if not isinstance(block, dict):
            return []
        btype = block.get("type", "")

        # Inline text for this block
        inline_parts = [_inline_text(i) for i in block.get("content", [])]
        line = "".join(inline_parts).strip()

        # Add a simple prefix for known block types so the AI has structure cues.
        if btype == "heading":
            level = block.get("props", {}).get("level", 1)
            prefix = "#" * int(level) + " "
            line = prefix + line if line else ""
        elif btype in ("bulletListItem", "checkListItem"):
            line = "- " + line if line else ""
        elif btype == "numberedListItem":
            line = "• " + line if line else ""
        elif btype == "table":
            # Tables: render row-by-row; content is a list of tableRow blocks.
            rows = []
            for row in block.get("content", []):
                if isinstance(row, dict) and row.get("type") == "tableRow":
                    cells = []
                    for cell in row.get("content", []):
                        if isinstance(cell, dict):
                            cell_text = "".join(
                                _inline_text(i) for i in cell.get("content", [])
                            )
                            cells.append(cell_text.strip())
                    rows.append(" | ".join(cells))
            return rows

        lines: list[str] = []
        if line:
            lines.append(line)

        # Recurse into children (nested list items, etc.)
        for child in block.get("children", []):
            lines.extend(_block_lines(child))

        return lines

    # Normalise top-level shape.
    if isinstance(editor_json, list):
        blocks = editor_json
    elif isinstance(editor_json, dict):
        blocks = editor_json.get("content") or editor_json.get("blocks") or []
    else:
        return ""

    all_lines: list[str] = []
    for block in blocks:
        all_lines.extend(_block_lines(block))

    return "\n".join(all_lines)


def _truncate(value: str | None, max_chars: int) -> str | None:
    """Trim a free-text field to keep tool results token-efficient."""
    if not value:
        return value
    return value[:max_chars] + "…" if len(value) > max_chars else value


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    d = _parse_date(value)
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
