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
    {
        "name": "get_workout",
        "description": (
            "Fetch the full details of a single workout session, including all exercise entries "
            "with sets, reps, weight, and metrics. Use when asked what was lifted or done in a "
            "specific session. Requires a workout_id from list_workouts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "UUID of the workout to fetch.",
                },
            },
            "required": ["workout_id"],
        },
    },
    {
        "name": "update_workout",
        "description": (
            "Update an existing workout session's metadata (name, date, or notes). "
            "Use when the user wants to rename a workout, correct the date, or add notes. "
            "To add or modify exercises use add_grocery_items — or create_workout for a fresh session. "
            "Only send fields that need to change. Requires workout_id from list_workouts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_id": {"type": "string", "description": "UUID of the workout to update."},
                "name": {"type": "string", "description": "New workout name."},
                "workout_date": {"type": "string", "description": "Corrected date (YYYY-MM-DD)."},
                "notes": {"type": "string", "description": "Notes about the session."},
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
            "what needs to be done, or pending work. Filter by project_id to scope "
            "results to a specific project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "Filter by status. Omit to return all statuses.",
                },
                "project_id": {
                    "type": "string",
                    "description": "UUID of a project to filter by. Omit for all projects.",
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
        "name": "get_note",
        "description": (
            "Fetch the full content of a single note by its ID. "
            "Use after list_notes has returned matching note IDs and you need to read the body. "
            "Returns title and full markdown content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "UUID of the note to fetch."},
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "delete_note",
        "description": (
            "Archive (soft-delete) a note. Use only when the user explicitly asks to delete or "
            "remove a note. The note is archived, not permanently destroyed. "
            "Get the note_id from list_notes first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "UUID of the note to archive."},
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
        "name": "get_recipe",
        "description": (
            "Fetch the full details of a single recipe, including all ingredients and steps. "
            "Use when asked to display a recipe, read its instructions, or generate a grocery list from it. "
            "Requires a recipe_id from list_recipes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string", "description": "UUID of the recipe."},
            },
            "required": ["recipe_id"],
        },
    },
    {
        "name": "create_recipe",
        "description": (
            "Create a new recipe with optional ingredients and steps. "
            "Confirm the name before calling. "
            "Ingredients and steps are optional — omit them to create a recipe shell first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Recipe name (required)."},
                "description": {"type": "string"},
                "source_url": {"type": "string", "description": "URL this recipe came from."},
                "prep_time_minutes": {"type": "integer", "minimum": 0},
                "cook_time_minutes": {"type": "integer", "minimum": 0},
                "servings": {"type": "integer", "minimum": 1},
                "notes": {"type": "string"},
                "ingredients": {
                    "type": "array",
                    "description": "List of ingredients in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string", "description": "e.g. 'g', 'cup', 'tbsp'"},
                            "notes": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered cooking steps.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_number": {"type": "integer", "minimum": 1},
                            "instruction": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["step_number", "instruction"],
                    },
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_recipe",
        "description": (
            "Update an existing recipe. Only send fields that need to change. "
            "If ingredients or steps are provided they completely replace the existing list — "
            "always include the full list, not just the changes. "
            "Get recipe_id from list_recipes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string", "description": "UUID of the recipe to update."},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "source_url": {"type": "string"},
                "prep_time_minutes": {"type": "integer", "minimum": 0},
                "cook_time_minutes": {"type": "integer", "minimum": 0},
                "servings": {"type": "integer", "minimum": 1},
                "notes": {"type": "string"},
                "ingredients": {
                    "type": "array",
                    "description": "Replaces all existing ingredients. Include the full list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "steps": {
                    "type": "array",
                    "description": "Replaces all existing steps. Include the full list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_number": {"type": "integer", "minimum": 1},
                            "instruction": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["step_number", "instruction"],
                    },
                },
            },
            "required": ["recipe_id"],
        },
    },
    {
        "name": "delete_recipe",
        "description": (
            "Permanently delete a recipe. "
            "Only use when the user explicitly asks to remove it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string", "description": "UUID of the recipe to delete."},
            },
            "required": ["recipe_id"],
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
        "name": "create_contact",
        "description": (
            "Create a new contact in the household address book. "
            "At least one of given_name, family_name, or display_name is recommended. "
            "Emails, phones, and addresses are optional arrays."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "given_name": {"type": "string"},
                "family_name": {"type": "string"},
                "display_name": {"type": "string", "description": "Full name override if different from given+family."},
                "organization": {"type": "string"},
                "job_title": {"type": "string"},
                "birthday": {"type": "string", "description": "YYYY-MM-DD."},
                "anniversary": {"type": "string", "description": "YYYY-MM-DD."},
                "notes": {"type": "string"},
                "website": {"type": "string"},
                "emails": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "description": "Email address."},
                            "label": {"type": "string", "description": "e.g. 'home', 'work'"},
                            "is_primary": {"type": "boolean", "default": False},
                        },
                        "required": ["email"],
                    },
                },
                "phones": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "phone_number": {"type": "string"},
                            "label": {"type": "string", "description": "e.g. 'mobile', 'home'"},
                            "is_primary": {"type": "boolean", "default": False},
                        },
                        "required": ["phone_number"],
                    },
                },
                "addresses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "street": {"type": "string"},
                            "city": {"type": "string"},
                            "region": {"type": "string", "description": "State / province."},
                            "postal_code": {"type": "string"},
                            "country": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "update_contact",
        "description": (
            "Update an existing contact. Only send fields that need to change. "
            "If emails, phones, or addresses are provided they completely replace the existing list — "
            "always include the full list, not just the changes. "
            "Get contact_id from list_contacts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "UUID of the contact to update."},
                "given_name": {"type": "string"},
                "family_name": {"type": "string"},
                "display_name": {"type": "string"},
                "organization": {"type": "string"},
                "job_title": {"type": "string"},
                "birthday": {"type": "string", "description": "YYYY-MM-DD."},
                "anniversary": {"type": "string", "description": "YYYY-MM-DD."},
                "notes": {"type": "string"},
                "website": {"type": "string"},
                "emails": {
                    "type": "array",
                    "description": "Replaces all existing emails. Include the full list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string"},
                            "label": {"type": "string"},
                            "is_primary": {"type": "boolean"},
                        },
                        "required": ["email"],
                    },
                },
                "phones": {
                    "type": "array",
                    "description": "Replaces all existing phone numbers. Include the full list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "phone_number": {"type": "string"},
                            "label": {"type": "string"},
                            "is_primary": {"type": "boolean"},
                        },
                        "required": ["phone_number"],
                    },
                },
                "addresses": {
                    "type": "array",
                    "description": "Replaces all existing addresses. Include the full list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "street": {"type": "string"},
                            "city": {"type": "string"},
                            "region": {"type": "string"},
                            "postal_code": {"type": "string"},
                            "country": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "delete_contact",
        "description": (
            "Permanently delete a contact from the address book. "
            "Only use when the user explicitly asks to remove them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "UUID of the contact to delete."},
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "get_contact",
        "description": (
            "Fetch the full details of a single contact by ID, including all emails, "
            "phones, and addresses. Use when list_contacts has already returned the contact "
            "and you need complete details. Requires contact_id from list_contacts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "UUID of the contact to fetch."},
            },
            "required": ["contact_id"],
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
        "name": "create_grocery_list",
        "description": (
            "Create a new grocery list, optionally pre-populated with items. "
            "Use when the user wants a shopping list, wants to pull ingredients from a recipe, "
            "or asks to make a grocery list. Each item can have a name, quantity, unit, and category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "List name, e.g. 'Weekly Shop' or 'Pad Thai ingredients'."},
                "store": {"type": "string", "description": "Optional store name."},
                "items": {
                    "type": "array",
                    "description": "Items to add immediately. Each item must have a name.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string", "description": "e.g. 'g', 'cup', 'tbsp'"},
                            "category": {"type": "string", "description": "e.g. 'Produce', 'Dairy', 'Meat'"},
                            "notes": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_grocery_items",
        "description": (
            "Add one or more items to an existing grocery list. "
            "Use to append ingredients or items to a list that already exists. "
            "Requires the list_id from list_grocery_lists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "UUID of the grocery list."},
                "items": {
                    "type": "array",
                    "description": "Items to add. Each must have a name.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string"},
                            "category": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["list_id", "items"],
        },
    },
    {
        "name": "check_grocery_item",
        "description": (
            "Mark a grocery list item as checked (bought) or unchecked. "
            "Requires list_id and item_id from list_grocery_lists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "UUID of the grocery list."},
                "item_id": {"type": "string", "description": "UUID of the item."},
                "is_checked": {"type": "boolean", "description": "True to mark bought, false to uncheck."},
            },
            "required": ["list_id", "item_id", "is_checked"],
        },
    },
    {
        "name": "delete_grocery_list",
        "description": (
            "Delete a grocery list and all its items. "
            "Confirm with the user before deleting. Requires list_id from list_grocery_lists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "UUID of the list to delete."},
            },
            "required": ["list_id"],
        },
    },
    {
        "name": "update_grocery_list",
        "description": (
            "Rename a grocery list, change its store, or update its status (active → completed). "
            "Only send fields that need to change. To add items use add_grocery_items; "
            "to check off individual items use check_grocery_item or update_grocery_item. "
            "Requires list_id from list_grocery_lists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "UUID of the grocery list."},
                "name": {"type": "string", "description": "New list name."},
                "store": {"type": "string", "description": "Store name."},
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "archived"],
                    "description": "Set to 'completed' when shopping is done.",
                },
            },
            "required": ["list_id"],
        },
    },
    {
        "name": "update_grocery_item",
        "description": (
            "Update an individual grocery item — rename it, change the quantity, "
            "unit, category, or notes. Also use to uncheck an item. "
            "To simply check/uncheck use check_grocery_item. "
            "Requires list_id and item_id from list_grocery_lists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "UUID of the grocery list."},
                "item_id": {"type": "string", "description": "UUID of the item to update."},
                "name": {"type": "string"},
                "quantity": {"type": "number"},
                "unit": {"type": "string", "description": "e.g. 'g', 'cup', 'tbsp'"},
                "category": {"type": "string", "description": "e.g. 'Produce', 'Dairy'"},
                "notes": {"type": "string"},
                "is_checked": {"type": "boolean"},
            },
            "required": ["list_id", "item_id"],
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
    {
        "name": "create_document",
        "description": (
            "Create a new document (page) in the document library. "
            "Use when the user wants to save written content as a permanent document. "
            "Content is plain markdown passed in source_markdown. "
            "Optionally nest under a parent document via parent_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title (required)."},
                "source_markdown": {
                    "type": "string",
                    "description": "Document body in plain markdown.",
                },
                "description": {"type": "string", "description": "Short subtitle or summary."},
                "parent_id": {
                    "type": "string",
                    "description": "UUID of a parent document to nest this under.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_document",
        "description": (
            "Update an existing document's title or content. "
            "Only send fields that need to change. "
            "source_markdown replaces the entire document body. "
            "Get document_id from list_documents or search_documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "UUID of the document to update."},
                "title": {"type": "string"},
                "source_markdown": {
                    "type": "string",
                    "description": "New full body in plain markdown. Replaces existing content.",
                },
                "description": {"type": "string"},
                "parent_id": {
                    "type": "string",
                    "description": "UUID of a new parent document (moves the document).",
                },
            },
            "required": ["document_id"],
        },
    },
    {
        "name": "archive_document",
        "description": (
            "Archive (soft-delete) a document. Archived documents are hidden from normal views "
            "but not permanently destroyed. Use when the user wants to remove or retire a document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "UUID of the document to archive."},
            },
            "required": ["document_id"],
        },
    },
    # ── Collections ───────────────────────────────────────────────────────────
    {
        "name": "list_collections",
        "description": (
            "List the household's collections. Collections are named, user-defined views over "
            "notes or documents — for example a daily journal collection, a meeting notes collection, "
            "or a recipes collection. Use when the user asks about their collections, wants to know "
            "which collection to place a note in, or needs a collection_id for another operation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "ensure_today_collection",
        "description": (
            "For a collection with a daily auto-create rule, get or create today's entry. "
            "Use when the user says 'open my journal', 'start today's entry', or asks to write "
            "in a collection that creates entries automatically (e.g. daily journal). "
            "Returns the ID of today's note or document — existing if already created, new if not. "
            "Requires collection_id from list_collections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_id": {"type": "string", "description": "UUID of the collection."},
            },
            "required": ["collection_id"],
        },
    },
    {
        "name": "create_collection",
        "description": (
            "Create a new collection to organise notes or documents. "
            "Collections can have an auto_create_rule so that a new entry is created each day "
            "(useful for daily journals or log books). "
            "Confirm the name and domain ('notes' or 'documents') before calling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Collection name, e.g. 'Daily Journal'."},
                "icon": {"type": "string", "description": "Emoji or icon string."},
                "domain": {
                    "type": "string",
                    "enum": ["notes", "documents"],
                    "description": "Whether this collection holds notes or documents.",
                },
                "auto_create_daily": {
                    "type": "boolean",
                    "description": (
                        "If true, a new entry is automatically created each day using a "
                        "date-based title (e.g. 'May 14, 2026'). Ideal for journals and logs."
                    ),
                    "default": False,
                },
                "title_template": {
                    "type": "string",
                    "description": (
                        "strftime format string for the daily entry title. "
                        "Default is '%B %d, %Y' → 'May 14, 2026'. "
                        "Only relevant when auto_create_daily is true."
                    ),
                },
            },
            "required": ["name", "domain"],
        },
    },
    {
        "name": "update_collection",
        "description": (
            "Rename a collection, change its icon, or toggle the auto-create rule. "
            "Only send fields that need to change. Requires collection_id from list_collections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_id": {"type": "string", "description": "UUID of the collection to update."},
                "name": {"type": "string"},
                "icon": {"type": "string"},
                "auto_create_daily": {
                    "type": "boolean",
                    "description": "Enable or disable the daily auto-create rule.",
                },
                "title_template": {
                    "type": "string",
                    "description": "strftime title template for daily entries.",
                },
            },
            "required": ["collection_id"],
        },
    },
    {
        "name": "delete_collection",
        "description": (
            "Permanently delete a collection. This removes the collection itself but does NOT "
            "delete the notes or documents inside it — they remain accessible without a collection. "
            "Confirm with the user before calling. Requires collection_id from list_collections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_id": {"type": "string", "description": "UUID of the collection to delete."},
            },
            "required": ["collection_id"],
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
    {
        "name": "archive_project",
        "description": (
            "Archive a project (soft-delete). The project and its todos are hidden from active "
            "views but not permanently removed. Prefer this over delete_project. "
            "System projects cannot be archived. Requires project_id from list_projects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "UUID of the project to archive."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "delete_project",
        "description": (
            "PERMANENTLY delete a project and all of its todos. This action is irreversible. "
            "Only use when the user explicitly asks to delete (not archive) a project and "
            "understands that all associated todos will be lost. System projects cannot be deleted. "
            "Always confirm with the user before calling. Prefer archive_project instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "UUID of the project to delete."},
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
    # ── Habit management ──────────────────────────────────────────────────────
    {
        "name": "create_habit",
        "description": (
            "Create a new habit to track. Use when the user wants to start tracking a recurring "
            "behaviour. Confirm the name and frequency before calling. "
            "For specific days of the week (e.g. Mon/Wed/Fri), pass days_of_week as a list of "
            "integers where Mon=0 and Sun=6."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Habit name (required)."},
                "description": {"type": "string"},
                "frequency": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                    "description": "Default 'daily'.",
                },
                "days_of_week": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    "description": (
                        "For habits on specific days only. Integers 0–6 where Mon=0, Sun=6. "
                        "E.g. [0, 2, 4] for Mon/Wed/Fri."
                    ),
                },
                "times_per_period": {
                    "type": "integer",
                    "description": "For weekly/monthly habits without specific days: target completions per period.",
                },
                "start_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD date from which the habit is active. Defaults to today.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "archived"],
                    "description": "Default 'active'.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_habit",
        "description": (
            "Update an existing habit — rename it, change frequency, adjust which days it runs, "
            "or pause/archive it. Only send fields that need to change. "
            "Get the habit_id from list_habits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "habit_id": {"type": "string", "description": "UUID of the habit to update."},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "frequency": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                },
                "days_of_week": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    "description": "Replaces existing days_of_week. Pass [] to clear.",
                },
                "times_per_period": {"type": "integer"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD."},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "archived"],
                },
            },
            "required": ["habit_id"],
        },
    },
    {
        "name": "delete_habit",
        "description": (
            "Permanently delete a habit and all its history. "
            "Prefer update_habit with status='archived' when the user just wants to stop tracking. "
            "Only use delete when they explicitly ask to remove all record of the habit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "habit_id": {"type": "string", "description": "UUID of the habit to delete."},
            },
            "required": ["habit_id"],
        },
    },
    # ── Budget tools ─────────────────────────────────────────────────────────
    {
        "name": "get_budget_summary",
        "description": (
            "Return a high-level income / expense / net summary for a date range. "
            "Use for questions like 'how much did I spend last month?', 'what's my net "
            "for Q1?', or 'am I over or under budget this month?'. "
            "Excludes transfers. Returns totals broken out by income vs expense, "
            "plus the transaction count and date range actually covered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start of the period, inclusive (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End of the period, inclusive (YYYY-MM-DD).",
                },
                "account_id": {
                    "type": "string",
                    "description": "Optional UUID — restrict to one account.",
                },
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "list_budget_transactions",
        "description": (
            "List individual transactions with optional filters. "
            "Use when the user asks about specific purchases, wants to see what "
            "they spent at a merchant, or needs raw transaction data to answer "
            "a follow-up question. Returns date, amount, description, merchant, "
            "category name, and account name for each transaction. "
            "Default limit is 50; max 200."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date inclusive (YYYY-MM-DD). Defaults to 30 days ago.",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date inclusive (YYYY-MM-DD). Defaults to today.",
                },
                "account_id": {
                    "type": "string",
                    "description": "Optional UUID — restrict to one account.",
                },
                "category_id": {
                    "type": "string",
                    "description": "Optional UUID — restrict to one category.",
                },
                "search": {
                    "type": "string",
                    "description": "Optional text filter applied to description and merchant name.",
                },
                "include_transfers": {
                    "type": "boolean",
                    "description": "Include transfer transactions (default false).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 50, max 200).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_spending_by_category",
        "description": (
            "Break down spending by category for a date range. "
            "Use for questions like 'what are my biggest spending categories?', "
            "'how much did I spend on groceries vs restaurants?', or "
            "'show me my spending breakdown for March'. "
            "Returns each category with its total spend, transaction count, and "
            "percentage of total spending. Expenses only (income excluded)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start of the period, inclusive (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "End of the period, inclusive (YYYY-MM-DD).",
                },
                "account_id": {
                    "type": "string",
                    "description": "Optional UUID — restrict to one account.",
                },
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "get_account_balances",
        "description": (
            "List all budget accounts with their current balances. "
            "Use when the user asks about their current balance, net worth across "
            "accounts, or which accounts are linked to Teller. "
            "Returns account name, type, current balance, and when the balance "
            "was last updated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "set_category_budget",
        "description": (
            "Set the ongoing monthly spending target for a budget category. "
            "Use when the user asks to update, set, or change a budget target or "
            "spending limit — e.g. 'set my dining budget to $500', 'change groceries "
            "to $300 a month', 'update my transport budget'. "
            "Matches the category by name (case-insensitive). Always confirm the "
            "category name and amount with the user before calling. "
            "Sets the default monthly amount that applies to every future month. "
            "Returns the updated category name and new target."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category_name": {
                    "type": "string",
                    "description": "Name of the budget category to update (case-insensitive match).",
                },
                "amount": {
                    "type": "number",
                    "description": "New monthly spending target in the household currency. Must be a positive number.",
                },
            },
            "required": ["category_name", "amount"],
        },
    },
    {
        "name": "update_profile",
        "description": (
            "Silently update the user's long-term profile that the coach and "
            "chatbot read on every interaction. Call this WITHOUT asking the "
            "user for permission whenever they tell you what they want you to "
            "focus on, mention a habit or topic they want recurring attention "
            "to, share a stable value or preference, or describe something "
            "they've decided about themselves. Examples that should trigger a "
            "call: 'I want to focus more on consistency moving forward,' "
            "'I've been drinking too much lately, please help me with that,' "
            "'I'm working on being kinder to myself,' 'stop bringing up the "
            "old job, I'm done with that chapter.' "
            ""
            "How to use: read the user's current profile carefully (it is in "
            "the system prompt under 'What you know about this person'). "
            "Produce a REVISED profile, in the SAME H2-section format, that "
            "integrates the new fact. Add to or modify existing sections "
            "rather than starting from scratch. Do NOT remove unrelated "
            "content. Keep the total under ~3000 characters. Output the FULL "
            "revised profile in content_md (not a diff). "
            ""
            "Do NOT use this tool for: one-off events, today's mood, a single "
            "bad day, transient details. Profile updates are for durable, "
            "ongoing things. After calling, briefly acknowledge to the user "
            "in plain language ('Got it, I'll keep that in mind') without "
            "mentioning the tool or the profile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content_md": {
                    "type": "string",
                    "description": (
                        "The FULL revised profile as markdown, sectioned by H2 "
                        "headers (## Current focuses, ## Values & non-negotiables, "
                        "## Recurring patterns, ## What drains me, ## What works "
                        "for me, ## Things to not bring up unless I do). Use the "
                        "same structure as the existing profile."
                    ),
                },
                "diff_summary": {
                    "type": "string",
                    "description": (
                        "Optional one-line description of what changed and why "
                        "(e.g. 'Added focus on drinking less'). For audit only — "
                        "the user never sees this."
                    ),
                },
            },
            "required": ["content_md"],
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


# ── Habit management input models ────────────────────────────────────────────

_HabitFrequency = Literal["daily", "weekly", "monthly"]
_HabitStatus = Literal["active", "paused", "archived"]


def _validate_days_of_week(v: Any) -> list[int] | None:
    """Coerce and validate a days_of_week list; returns sorted deduplicated ints."""
    if v is None:
        return None
    if not isinstance(v, list):
        raise ValueError("days_of_week must be a list of integers 0–6")
    result = []
    for d in v:
        try:
            d_int = int(d)
        except (TypeError, ValueError):
            raise ValueError(f"{d!r} is not a valid weekday integer")
        if not (0 <= d_int <= 6):
            raise ValueError(f"Day {d_int} out of range; must be 0 (Mon) to 6 (Sun)")
        result.append(d_int)
    return sorted(set(result))


class _CreateHabitInput(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    frequency: _HabitFrequency = "daily"
    days_of_week: list[int] | None = None
    times_per_period: int | None = None
    start_date: date | None = None
    status: _HabitStatus = "active"

    @field_validator("days_of_week", mode="before")
    @classmethod
    def parse_days(cls, v: Any) -> list[int] | None:
        return _validate_days_of_week(v)

    @field_validator("start_date", mode="before")
    @classmethod
    def parse_start_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")


class _UpdateHabitInput(BaseModel):
    habit_id: uuid.UUID
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    frequency: _HabitFrequency | None = None
    days_of_week: list[int] | None = None
    times_per_period: int | None = None
    start_date: date | None = None
    status: _HabitStatus | None = None

    @field_validator("habit_id", mode="before")
    @classmethod
    def parse_habit_id(cls, v: Any) -> uuid.UUID:
        return _parse_uuid_field(v)

    @field_validator("days_of_week", mode="before")
    @classmethod
    def parse_days(cls, v: Any) -> list[int] | None:
        return _validate_days_of_week(v)

    @field_validator("start_date", mode="before")
    @classmethod
    def parse_start_date(cls, v: Any) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError(f"Expected YYYY-MM-DD, got {v!r}")


# ── Budget input schemas ──────────────────────────────────────────────────────

def _parse_date_field(v: Any, field: str) -> date:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        raise ValueError(f"{field}: expected YYYY-MM-DD, got {v!r}")


class _GetBudgetSummaryInput(BaseModel):
    date_from: date
    date_to: date
    account_id: uuid.UUID | None = None

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_dates(cls, v: Any) -> date:
        return _parse_date_field(v, "date")

    @field_validator("account_id", mode="before")
    @classmethod
    def parse_account_id(cls, v: Any) -> uuid.UUID | None:
        if v is None:
            return None
        try:
            return uuid.UUID(str(v))
        except ValueError:
            raise ValueError(f"account_id must be a valid UUID, got {v!r}")


class _ListBudgetTransactionsInput(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    search: str | None = None
    include_transfers: bool = False
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_dates(cls, v: Any) -> date | None:
        if v is None:
            return None
        return _parse_date_field(v, "date")

    @field_validator("account_id", "category_id", mode="before")
    @classmethod
    def parse_uuids(cls, v: Any) -> uuid.UUID | None:
        if v is None:
            return None
        try:
            return uuid.UUID(str(v))
        except ValueError:
            raise ValueError(f"Expected a valid UUID, got {v!r}")


class _GetSpendingByCategoryInput(BaseModel):
    date_from: date
    date_to: date
    account_id: uuid.UUID | None = None

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def parse_dates(cls, v: Any) -> date:
        return _parse_date_field(v, "date")

    @field_validator("account_id", mode="before")
    @classmethod
    def parse_account_id(cls, v: Any) -> uuid.UUID | None:
        if v is None:
            return None
        try:
            return uuid.UUID(str(v))
        except ValueError:
            raise ValueError(f"account_id must be a valid UUID, got {v!r}")


class _SetCategoryBudgetInput(BaseModel):
    category_name: str = Field(min_length=1)
    amount: float = Field(gt=0)


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
        if tool_name == "update_workout":
            return await _update_workout(db, tool_input, household_id)
        if tool_name == "delete_workout":
            return await _delete_workout(db, tool_input, household_id)
        if tool_name == "get_workout":
            return await _get_workout(db, tool_input, household_id)
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
        if tool_name == "get_note":
            return await _get_note(db, tool_input, household_id)
        if tool_name == "delete_note":
            return await _delete_note(db, tool_input, household_id)
        if tool_name == "list_calendar_events":
            return await _list_calendar_events(db, tool_input, household_id)
        if tool_name == "list_recipes":
            return await _list_recipes(db, tool_input, household_id)
        if tool_name == "get_recipe":
            return await _get_recipe(db, tool_input, household_id)
        if tool_name == "create_recipe":
            return await _create_recipe(db, tool_input, household_id, user_id)
        if tool_name == "update_recipe":
            return await _update_recipe(db, tool_input, household_id)
        if tool_name == "delete_recipe":
            return await _delete_recipe(db, tool_input, household_id)
        if tool_name == "list_contacts":
            return await _list_contacts(db, tool_input, household_id)
        if tool_name == "get_contact":
            return await _get_contact(db, tool_input, household_id)
        if tool_name == "create_contact":
            return await _create_contact(db, tool_input, household_id, user_id)
        if tool_name == "update_contact":
            return await _update_contact(db, tool_input, household_id)
        if tool_name == "delete_contact":
            return await _delete_contact(db, tool_input, household_id)
        if tool_name == "list_grocery_lists":
            return await _list_grocery_lists(db, tool_input, household_id)
        if tool_name == "create_grocery_list":
            return await _create_grocery_list(db, tool_input, household_id, user_id)
        if tool_name == "add_grocery_items":
            return await _add_grocery_items(db, tool_input, household_id)
        if tool_name == "check_grocery_item":
            return await _check_grocery_item(db, tool_input, household_id)
        if tool_name == "delete_grocery_list":
            return await _delete_grocery_list(db, tool_input, household_id)
        if tool_name == "update_grocery_list":
            return await _update_grocery_list(db, tool_input, household_id)
        if tool_name == "update_grocery_item":
            return await _update_grocery_item(db, tool_input, household_id)
        if tool_name == "get_documents":
            return await _get_documents(db, tool_input, household_id)
        if tool_name == "list_documents":
            return await _list_documents(db, tool_input, household_id)
        if tool_name == "search_documents":
            return await _search_documents(db, tool_input, household_id)
        if tool_name == "create_document":
            return await _create_document(db, tool_input, household_id, user_id)
        if tool_name == "update_document":
            return await _update_document(db, tool_input, household_id)
        if tool_name == "archive_document":
            return await _archive_document(db, tool_input, household_id)
        # ── Collections ───────────────────────────────────────────────────────
        if tool_name == "list_collections":
            return await _list_collections(db, tool_input, household_id)
        if tool_name == "ensure_today_collection":
            return await _ensure_today_collection(db, tool_input, household_id, user_id)
        if tool_name == "create_collection":
            return await _create_collection(db, tool_input, household_id, user_id)
        if tool_name == "update_collection":
            return await _update_collection(db, tool_input, household_id)
        if tool_name == "delete_collection":
            return await _delete_collection(db, tool_input, household_id)
        # ── Projects ──────────────────────────────────────────────────────────
        if tool_name == "list_projects":
            return await _list_projects(db, tool_input, household_id)
        if tool_name == "create_project":
            return await _create_project(db, tool_input, household_id, user_id)
        if tool_name == "update_project":
            return await _update_project(db, tool_input, household_id)
        if tool_name == "archive_project":
            return await _archive_project(db, tool_input, household_id)
        if tool_name == "delete_project":
            return await _delete_project(db, tool_input, household_id)
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
        if tool_name == "create_habit":
            return await _create_habit(db, tool_input, household_id, user_id)
        if tool_name == "update_habit":
            return await _update_habit(db, tool_input, household_id)
        if tool_name == "delete_habit":
            return await _delete_habit(db, tool_input, household_id)
        # ── Budget ────────────────────────────────────────────────────────────
        if tool_name == "get_budget_summary":
            return await _get_budget_summary(db, tool_input, household_id)
        if tool_name == "list_budget_transactions":
            return await _list_budget_transactions(db, tool_input, household_id)
        if tool_name == "get_spending_by_category":
            return await _get_spending_by_category(db, tool_input, household_id)
        if tool_name == "get_account_balances":
            return await _get_account_balances(db, household_id)
        if tool_name == "set_category_budget":
            return await _set_category_budget(db, tool_input, household_id)
        if tool_name == "update_profile":
            return await _update_profile(db, tool_input, user_id)
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
    project_id: uuid.UUID | None = None
    raw_project_id = inp.get("project_id")
    if raw_project_id:
        try:
            project_id = uuid.UUID(str(raw_project_id))
        except (ValueError, AttributeError):
            return {"error": f"project_id {raw_project_id!r} is not a valid UUID."}

    result = await svc.list_todos(db, household_id, status=status, project_id=project_id, limit=limit)
    return {
        "total": result.total,
        "todos": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status,
                "due_date": str(t.due_date) if t.due_date else None,
                "priority": t.priority,
                "project_id": str(t.project_id) if t.project_id else None,
                "description": _truncate(t.description, 200),
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
    from life_dashboard.domains.habits.models import HabitOccurrence
    from sqlalchemy import select as sa_select

    status = inp.get("status", "active")
    limit = min(int(inp.get("limit", 20)), 50)

    result = await svc.list_habits(db, household_id, status=status, limit=limit)

    # Batch-load today's occurrence status for all returned habits in one query.
    today = date.today()
    today_statuses: dict[uuid.UUID, str] = {}
    if result.items:
        habit_ids = [h.id for h in result.items]
        occ_result = await db.execute(
            sa_select(HabitOccurrence.habit_id, HabitOccurrence.status)
            .where(
                HabitOccurrence.habit_id.in_(habit_ids),
                HabitOccurrence.scheduled_date == today,
            )
        )
        for habit_id, occ_status in occ_result.all():
            today_statuses[habit_id] = occ_status

    return {
        "total": result.total,
        "habits": [
            {
                "id": str(h.id),
                "name": h.name,
                "description": _truncate(h.description, 150),
                "frequency": h.frequency,
                "cadence": h.cadence,
                "status": h.status,
                "streak": h.current_streak,
                "completion_rate_7d": h.completion_rate_7d,
                "today_status": today_statuses.get(h.id),  # None = no occurrence logged yet
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
                "priority": g.priority,
                "target_value": float(g.target_value) if g.target_value is not None else None,
                "current_value": float(g.current_value) if g.current_value is not None else None,
                "unit": g.unit,
                "due_date": str(g.due_date) if g.due_date else None,
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
                "emails": [{"label": e.label, "email": e.email} for e in c.emails],
                "phones": [{"label": p.label, "phone_number": p.phone_number} for p in c.phones],
                "addresses": [
                    {
                        "label": a.label,
                        "street": a.street,
                        "city": a.city,
                        "region": a.region,
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
                        "id": str(item.id),
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
        occurrence = await svc.update_occurrence(
            db, validated.habit_id, occurrence_row.id, household_id, data
        )
        action = "updated"
    else:
        data = OccurrenceCreate(
            scheduled_date=validated.scheduled_date,
            status=validated.status,
            notes=validated.notes,
        )
        occurrence = await svc.create_occurrence(db, validated.habit_id, household_id, data)
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


# ── Recipe handlers ───────────────────────────────────────────────────────────

def _parse_ingredient(raw: dict, index: int) -> "IngredientData":
    """Coerce a raw dict into an IngredientData; converts float quantity to Decimal."""
    from decimal import Decimal, InvalidOperation
    from life_dashboard.domains.recipes.schemas import IngredientData

    qty = raw.get("quantity")
    try:
        qty = Decimal(str(qty)) if qty is not None else None
    except (InvalidOperation, TypeError):
        qty = None

    return IngredientData(
        name=raw["name"],
        quantity=qty,
        unit=raw.get("unit"),
        notes=raw.get("notes"),
        sort_order=index,
    )


def _parse_step(raw: dict) -> "StepData":
    from life_dashboard.domains.recipes.schemas import StepData
    return StepData(
        step_number=int(raw["step_number"]),
        instruction=raw["instruction"],
        notes=raw.get("notes"),
    )


async def _get_recipe(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.recipes import service as svc

    try:
        recipe_id = uuid.UUID(str(inp.get("recipe_id", "")))
    except (ValueError, AttributeError):
        return {"error": "recipe_id is not a valid UUID.", "hint": "Use list_recipes to find the correct ID."}

    result = await svc.get_recipe(db, recipe_id, household_id)
    if result is None:
        return {"error": "Recipe not found.", "hint": "Confirm the recipe_id via list_recipes."}

    return {
        "id": str(result.id),
        "name": result.name,
        "description": result.description,
        "source_url": result.source_url,
        "prep_time_minutes": result.prep_time_minutes,
        "cook_time_minutes": result.cook_time_minutes,
        "servings": result.servings,
        "notes": result.notes,
        "ingredients": [
            {
                "name": i.name,
                "quantity": float(i.quantity) if i.quantity is not None else None,
                "unit": i.unit,
                "notes": i.notes,
            }
            for i in result.ingredients
        ],
        "steps": [
            {
                "step_number": s.step_number,
                "instruction": s.instruction,
                "notes": s.notes,
            }
            for s in result.steps
        ],
    }


async def _create_recipe(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.recipes import service as svc
    from life_dashboard.domains.recipes.schemas import RecipeCreate

    raw_ings = inp.get("ingredients") or []
    raw_steps = inp.get("steps") or []

    try:
        ingredients = [_parse_ingredient(i, idx) for idx, i in enumerate(raw_ings)]
        steps = [_parse_step(s) for s in raw_steps]
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid ingredient or step data: {exc}", "hint": "Check ingredient names and step numbers."}

    data = RecipeCreate(
        name=inp["name"],
        description=inp.get("description"),
        source_url=inp.get("source_url"),
        prep_time_minutes=inp.get("prep_time_minutes"),
        cook_time_minutes=inp.get("cook_time_minutes"),
        servings=inp.get("servings"),
        notes=inp.get("notes"),
        ingredients=ingredients,
        steps=steps,
    )
    result = await svc.create_recipe(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(result.id),
        "name": result.name,
        "ingredients_created": len(result.ingredients),
        "steps_created": len(result.steps),
    }


async def _update_recipe(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.recipes import service as svc
    from life_dashboard.domains.recipes.schemas import RecipeUpdate

    try:
        recipe_id = uuid.UUID(str(inp.get("recipe_id", "")))
    except (ValueError, AttributeError):
        return {"error": "recipe_id is not a valid UUID.", "hint": "Use list_recipes to find the correct ID."}

    update_kwargs: dict[str, Any] = {}
    for field in ("name", "description", "source_url", "prep_time_minutes",
                  "cook_time_minutes", "servings", "notes"):
        if field in inp:
            update_kwargs[field] = inp[field]

    if "ingredients" in inp:
        try:
            update_kwargs["ingredients"] = [
                _parse_ingredient(i, idx) for idx, i in enumerate(inp["ingredients"] or [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            return {"error": f"Invalid ingredient data: {exc}"}

    if "steps" in inp:
        try:
            update_kwargs["steps"] = [_parse_step(s) for s in (inp["steps"] or [])]
        except (KeyError, TypeError, ValueError) as exc:
            return {"error": f"Invalid step data: {exc}"}

    data = RecipeUpdate(**update_kwargs)
    result = await svc.update_recipe(db, recipe_id, household_id, data)
    if result is None:
        return {"error": "Recipe not found.", "hint": "Confirm the recipe_id via list_recipes."}
    return {
        "ok": True,
        "id": str(result.id),
        "name": result.name,
        "ingredients_count": len(result.ingredients),
        "steps_count": len(result.steps),
    }


async def _delete_recipe(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.recipes import service as svc

    try:
        recipe_id = uuid.UUID(str(inp.get("recipe_id", "")))
    except (ValueError, AttributeError):
        return {"error": "recipe_id is not a valid UUID.", "hint": "Use list_recipes to find the correct ID."}

    deleted = await svc.delete_recipe(db, recipe_id, household_id)
    if not deleted:
        return {"error": "Recipe not found.", "hint": "Confirm the recipe_id via list_recipes."}
    return {"ok": True, "deleted_id": str(recipe_id)}


# ── Contact write handlers ────────────────────────────────────────────────────

def _parse_contact_date(value: Any) -> "date | None":
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _build_contact_sub_lists(inp: dict) -> dict:
    """Parse emails, phones, and addresses from raw tool input into schema objects."""
    from life_dashboard.domains.contacts.schemas import AddressData, EmailData, PhoneData

    result: dict = {}
    if "emails" in inp:
        result["emails"] = [
            EmailData(
                email=e["email"],
                label=e.get("label"),
                is_primary=bool(e.get("is_primary", False)),
            )
            for e in (inp["emails"] or [])
        ]
    if "phones" in inp:
        result["phones"] = [
            PhoneData(
                phone_number=p["phone_number"],
                label=p.get("label"),
                is_primary=bool(p.get("is_primary", False)),
            )
            for p in (inp["phones"] or [])
        ]
    if "addresses" in inp:
        result["addresses"] = [
            AddressData(
                label=a.get("label"),
                street=a.get("street"),
                city=a.get("city"),
                region=a.get("region"),
                postal_code=a.get("postal_code"),
                country=a.get("country"),
            )
            for a in (inp["addresses"] or [])
        ]
    return result


def _contact_response_dict(c: "ContactResponse") -> dict:
    name = c.display_name or " ".join(filter(None, [c.given_name, c.family_name]))
    return {
        "ok": True,
        "id": str(c.id),
        "name": name,
        "organization": c.organization,
        "emails_count": len(c.emails),
        "phones_count": len(c.phones),
    }


async def _create_contact(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.contacts import service as svc
    from life_dashboard.domains.contacts.schemas import ContactCreate

    try:
        sub = _build_contact_sub_lists(inp)
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid contact data: {exc}"}

    data = ContactCreate(
        given_name=inp.get("given_name"),
        family_name=inp.get("family_name"),
        display_name=inp.get("display_name"),
        organization=inp.get("organization"),
        job_title=inp.get("job_title"),
        birthday=_parse_contact_date(inp.get("birthday")),
        anniversary=_parse_contact_date(inp.get("anniversary")),
        notes=inp.get("notes"),
        website=inp.get("website"),
        emails=sub.get("emails", []),
        phones=sub.get("phones", []),
        addresses=sub.get("addresses", []),
    )
    result = await svc.create_contact(db, household_id, user_id, data)
    return _contact_response_dict(result)


async def _update_contact(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.contacts import service as svc
    from life_dashboard.domains.contacts.schemas import ContactUpdate

    try:
        contact_id = uuid.UUID(str(inp.get("contact_id", "")))
    except (ValueError, AttributeError):
        return {"error": "contact_id is not a valid UUID.", "hint": "Use list_contacts to find the correct ID."}

    try:
        sub = _build_contact_sub_lists(inp)
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Invalid contact data: {exc}"}

    scalar_fields = ("given_name", "family_name", "display_name", "organization",
                     "job_title", "notes", "website")
    update_kwargs: dict[str, Any] = {f: inp[f] for f in scalar_fields if f in inp}

    for date_field in ("birthday", "anniversary"):
        if date_field in inp:
            update_kwargs[date_field] = _parse_contact_date(inp[date_field])

    update_kwargs.update(sub)

    data = ContactUpdate(**update_kwargs)
    result = await svc.update_contact(db, contact_id, household_id, data)
    if result is None:
        return {"error": "Contact not found.", "hint": "Confirm the contact_id via list_contacts."}
    return _contact_response_dict(result)


async def _delete_contact(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.contacts import service as svc

    try:
        contact_id = uuid.UUID(str(inp.get("contact_id", "")))
    except (ValueError, AttributeError):
        return {"error": "contact_id is not a valid UUID.", "hint": "Use list_contacts to find the correct ID."}

    deleted = await svc.delete_contact(db, contact_id, household_id)
    if not deleted:
        return {"error": "Contact not found.", "hint": "Confirm the contact_id via list_contacts."}
    return {"ok": True, "deleted_id": str(contact_id)}


# ── Document write handlers ───────────────────────────────────────────────────

async def _create_document(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.documents import service as svc
    from life_dashboard.domains.documents.schemas import DocumentCreate

    parent_id: uuid.UUID | None = None
    if inp.get("parent_id"):
        try:
            parent_id = uuid.UUID(str(inp["parent_id"]))
        except (ValueError, AttributeError):
            return {"error": "parent_id is not a valid UUID."}

    data = DocumentCreate(
        title=inp["title"],
        description=inp.get("description"),
        parent_id=parent_id,
        source_markdown=inp.get("source_markdown"),
    )
    result = await svc.create_document(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(result.id),
        "title": result.title,
        "slug": result.slug,
    }


async def _update_document(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.documents import service as svc
    from life_dashboard.domains.documents.schemas import DocumentUpdate

    try:
        doc_id = uuid.UUID(str(inp.get("document_id", "")))
    except (ValueError, AttributeError):
        return {"error": "document_id is not a valid UUID.", "hint": "Use list_documents or search_documents to find the correct ID."}

    update_kwargs: dict[str, Any] = {}
    for field in ("title", "description", "source_markdown"):
        if field in inp:
            update_kwargs[field] = inp[field]

    if "parent_id" in inp:
        try:
            update_kwargs["parent_id"] = uuid.UUID(str(inp["parent_id"])) if inp["parent_id"] else None
        except (ValueError, AttributeError):
            return {"error": "parent_id is not a valid UUID."}

    data = DocumentUpdate(**update_kwargs)
    result = await svc.update_document(db, doc_id, household_id, data)
    if result is None:
        return {"error": "Document not found.", "hint": "Confirm the document_id via list_documents."}
    return {
        "ok": True,
        "id": str(result.id),
        "title": result.title,
        "slug": result.slug,
    }


async def _archive_document(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.documents import service as svc

    try:
        doc_id = uuid.UUID(str(inp.get("document_id", "")))
    except (ValueError, AttributeError):
        return {"error": "document_id is not a valid UUID.", "hint": "Use list_documents or search_documents to find the correct ID."}

    result = await svc.archive_document(db, doc_id, household_id)
    if result is None:
        return {"error": "Document not found.", "hint": "Confirm the document_id via list_documents."}
    return {"ok": True, "archived_id": str(doc_id), "title": result.title}


# ── Workout detail handler ────────────────────────────────────────────────────

async def _get_workout(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.workouts import service as svc

    try:
        workout_id = uuid.UUID(str(inp.get("workout_id", "")))
    except (ValueError, AttributeError):
        return {"error": "workout_id is not a valid UUID.", "hint": "Use list_workouts to find the correct ID."}

    result = await svc.get_workout_with_entries(db, workout_id, household_id)
    if result is None:
        return {
            "error": "Workout not found.",
            "hint": "Confirm the workout_id via list_workouts.",
        }
    return {
        "id": str(result.id),
        "date": str(result.workout_date),
        "name": result.name,
        "notes": result.notes,
        "entries": [
            {
                "id": str(e.id),
                "name": e.name,
                "type": e.type,
                "metrics": e.metrics,
                "notes": e.notes,
            }
            for e in result.entries
        ],
    }


# ── Note detail + delete handlers ─────────────────────────────────────────────

async def _get_note(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.notes import service as svc

    try:
        note_id = uuid.UUID(str(inp.get("note_id", "")))
    except (ValueError, AttributeError):
        return {"error": "note_id is not a valid UUID.", "hint": "Use list_notes to find the correct ID."}

    result = await svc.get_note(db, note_id, household_id)
    if result is None:
        return {
            "error": "Note not found.",
            "hint": "Confirm the note_id via list_notes.",
        }
    return {
        "id": str(result.id),
        "title": result.title,
        "content_md": result.content_md,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
    }


async def _delete_note(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.notes import service as svc

    try:
        note_id = uuid.UUID(str(inp.get("note_id", "")))
    except (ValueError, AttributeError):
        return {"error": "note_id is not a valid UUID.", "hint": "Use list_notes to find the correct ID."}

    archived = await svc.archive_note(db, note_id, household_id)
    if not archived:
        return {
            "error": "Note not found.",
            "hint": "Confirm the note_id via list_notes.",
        }
    return {"ok": True, "archived_id": str(note_id)}


# ── Habit management handlers ─────────────────────────────────────────────────

async def _create_habit(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.habits import service as svc
    from life_dashboard.domains.habits.schemas import HabitCreate

    validated = _CreateHabitInput.model_validate(inp)

    # Build the cadence JSONB from the discrete tool fields.
    cadence: dict | None = None
    cadence_parts: dict = {}
    if validated.days_of_week is not None:
        cadence_parts["days_of_week"] = validated.days_of_week
    if validated.times_per_period is not None:
        cadence_parts["times_per_period"] = validated.times_per_period
    if validated.start_date is not None:
        cadence_parts["start_date"] = validated.start_date.isoformat()
    if cadence_parts:
        cadence = cadence_parts

    data = HabitCreate(
        name=validated.name,
        description=validated.description,
        frequency=validated.frequency,
        cadence=cadence,
        status=validated.status,
    )
    result = await svc.create_habit(db, household_id, user_id, data)
    return {
        "ok": True,
        "id": str(result.id),
        "name": result.name,
        "frequency": result.frequency,
        "status": result.status,
    }


async def _update_habit(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.habits import service as svc
    from life_dashboard.domains.habits.models import Habit
    from life_dashboard.domains.habits.schemas import HabitUpdate
    from sqlalchemy import select as sa_select

    validated = _UpdateHabitInput.model_validate(inp)

    update_kwargs: dict = {}
    for field in ("name", "description", "frequency", "status"):
        if field in inp:
            update_kwargs[field] = getattr(validated, field)

    # Merge cadence sub-fields if any were supplied.
    cadence_fields = {"days_of_week", "times_per_period", "start_date"}
    if cadence_fields & inp.keys():
        # Fetch current cadence to preserve untouched sub-fields.
        row = (await db.execute(
            sa_select(Habit.cadence).where(
                Habit.id == validated.habit_id,
                Habit.household_id == household_id,
            )
        )).scalar_one_or_none()
        current_cadence: dict = dict(row) if row else {}

        if "days_of_week" in inp:
            # Empty list clears the days_of_week sub-field.
            if validated.days_of_week:
                current_cadence["days_of_week"] = validated.days_of_week
            else:
                current_cadence.pop("days_of_week", None)
        if "times_per_period" in inp:
            if validated.times_per_period is not None:
                current_cadence["times_per_period"] = validated.times_per_period
            else:
                current_cadence.pop("times_per_period", None)
        if "start_date" in inp:
            if validated.start_date is not None:
                current_cadence["start_date"] = validated.start_date.isoformat()
            else:
                current_cadence.pop("start_date", None)

        update_kwargs["cadence"] = current_cadence or None

    data = HabitUpdate(**update_kwargs)
    result = await svc.update_habit(db, validated.habit_id, household_id, data)
    if result is None:
        return {
            "error": "Habit not found.",
            "hint": "Confirm the habit_id via list_habits.",
        }
    return {
        "ok": True,
        "id": str(result.id),
        "name": result.name,
        "frequency": result.frequency,
        "status": result.status,
    }


async def _delete_habit(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.habits import service as svc

    try:
        habit_id = uuid.UUID(str(inp.get("habit_id", "")))
    except (ValueError, AttributeError):
        return {"error": "habit_id is not a valid UUID.", "hint": "Use list_habits to find the correct ID."}

    deleted = await svc.delete_habit(db, habit_id, household_id)
    if not deleted:
        return {
            "error": "Habit not found.",
            "hint": "Confirm the habit_id via list_habits.",
        }
    return {"ok": True, "deleted_id": str(habit_id)}


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


# ── Grocery list write handlers ────────────────────────────────────────────────

def _parse_grocery_item(raw: dict) -> "GroceryItemData":
    from decimal import Decimal, InvalidOperation
    from life_dashboard.domains.grocery_lists.schemas import GroceryItemData

    qty = raw.get("quantity")
    try:
        qty = Decimal(str(qty)) if qty is not None else None
    except (InvalidOperation, TypeError):
        qty = None

    return GroceryItemData(
        name=raw["name"],
        quantity=qty,
        unit=raw.get("unit"),
        category=raw.get("category"),
        notes=raw.get("notes"),
    )


async def _create_grocery_list(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc
    from life_dashboard.domains.grocery_lists.schemas import GroceryListCreate

    raw_items = inp.get("items") or []
    items = [_parse_grocery_item(i) for i in raw_items]

    data = GroceryListCreate(
        name=inp["name"],
        store=inp.get("store"),
        items=items,
    )
    result = await svc.create_grocery_list(db, household_id, user_id, data)
    return {
        "id": str(result.id),
        "name": result.name,
        "store": result.store,
        "status": result.status,
        "item_count": len(result.items),
        "items": [
            {
                "id": str(item.id),
                "name": item.name,
                "quantity": str(item.quantity) if item.quantity is not None else None,
                "unit": item.unit,
                "category": item.category,
            }
            for item in result.items
        ],
    }


async def _add_grocery_items(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc
    from life_dashboard.domains.grocery_lists.schemas import GroceryListUpdate

    list_id = uuid.UUID(inp["list_id"])

    # Fetch current list so we can append without destroying existing items.
    existing = await svc.get_grocery_list(db, list_id, household_id)
    if existing is None:
        return {"error": f"Grocery list {list_id} not found."}

    from life_dashboard.domains.grocery_lists.schemas import GroceryItemData

    kept = [
        GroceryItemData(
            name=i.name,
            quantity=i.quantity,
            unit=i.unit,
            category=i.category,
            is_checked=i.is_checked,
            notes=i.notes,
        )
        for i in existing.items
    ]
    new_items = [_parse_grocery_item(i) for i in (inp.get("items") or [])]
    all_items = kept + new_items

    data = GroceryListUpdate(items=all_items)
    result = await svc.update_grocery_list(db, list_id, household_id, data)
    if result is None:
        return {"error": "Failed to update grocery list."}

    return {
        "id": str(result.id),
        "name": result.name,
        "item_count": len(result.items),
        "added": len(new_items),
    }


async def _check_grocery_item(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc
    from life_dashboard.domains.grocery_lists.schemas import GroceryItemUpdate

    list_id = uuid.UUID(inp["list_id"])
    item_id = uuid.UUID(inp["item_id"])
    is_checked = bool(inp["is_checked"])

    result = await svc.update_grocery_item(
        db, list_id, item_id, household_id, GroceryItemUpdate(is_checked=is_checked)
    )
    if result is None:
        return {"error": f"Item {item_id} not found in list {list_id}."}

    return {
        "id": str(result.id),
        "name": result.name,
        "is_checked": result.is_checked,
    }


async def _delete_grocery_list(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc

    list_id = uuid.UUID(inp["list_id"])
    deleted = await svc.delete_grocery_list(db, list_id, household_id)
    if not deleted:
        return {"error": f"Grocery list {list_id} not found."}
    return {"deleted": True, "list_id": str(list_id)}


async def _update_grocery_list(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc
    from life_dashboard.domains.grocery_lists.schemas import GroceryListUpdate

    list_id = uuid.UUID(inp["list_id"])
    data = GroceryListUpdate(
        **{k: v for k, v in inp.items() if k != "list_id" and k in {"name", "store", "status"}}
    )
    result = await svc.update_grocery_list(db, list_id, household_id, data)
    if result is None:
        return {"error": f"Grocery list {list_id} not found."}
    return {
        "id": str(result.id),
        "name": result.name,
        "store": result.store,
        "status": result.status,
        "item_count": len(result.items),
    }


async def _update_grocery_item(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.grocery_lists import service as svc
    from life_dashboard.domains.grocery_lists.schemas import GroceryItemUpdate

    list_id = uuid.UUID(inp["list_id"])
    item_id = uuid.UUID(inp["item_id"])
    data = GroceryItemUpdate(
        **{k: v for k, v in inp.items() if k not in {"list_id", "item_id"}}
    )
    result = await svc.update_grocery_item(db, list_id, item_id, household_id, data)
    if result is None:
        return {"error": f"Item {item_id} not found in list {list_id}."}
    return {
        "id": str(result.id),
        "name": result.name,
        "quantity": str(result.quantity) if result.quantity is not None else None,
        "unit": result.unit,
        "category": result.category,
        "is_checked": result.is_checked,
        "notes": result.notes,
    }


async def _update_workout(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.workouts import service as svc
    from life_dashboard.domains.workouts.schemas import WorkoutUpdate

    try:
        workout_id = uuid.UUID(inp["workout_id"])
    except (KeyError, ValueError):
        return {"error": "workout_id is required and must be a valid UUID."}

    update_kwargs: dict = {}
    if "name" in inp:
        update_kwargs["name"] = inp["name"]
    if "workout_date" in inp:
        try:
            update_kwargs["workout_date"] = date.fromisoformat(inp["workout_date"])
        except ValueError:
            return {"error": "workout_date must be YYYY-MM-DD."}
    if "notes" in inp:
        update_kwargs["notes"] = inp["notes"]

    if not update_kwargs:
        return {"error": "No fields provided to update.", "hint": "Send at least one of: name, workout_date, notes."}

    data = WorkoutUpdate(**update_kwargs)
    result = await svc.update_workout(db, workout_id, household_id, data)
    if result is None:
        return {"error": f"Workout {workout_id} not found."}
    return {
        "id": str(result.id),
        "name": result.name,
        "workout_date": str(result.workout_date),
        "notes": result.notes,
    }


async def _get_contact(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.contacts import service as svc

    try:
        contact_id = uuid.UUID(inp["contact_id"])
    except (KeyError, ValueError):
        return {"error": "contact_id is required and must be a valid UUID."}

    result = await svc.get_contact(db, contact_id, household_id)
    if result is None:
        return {"error": f"Contact {contact_id} not found.", "hint": "Use list_contacts to find the correct ID."}

    return {
        "id": str(result.id),
        "name": result.display_name or " ".join(filter(None, [result.given_name, result.family_name])),
        "given_name": result.given_name,
        "family_name": result.family_name,
        "middle_name": result.middle_name,
        "prefix": result.prefix,
        "suffix": result.suffix,
        "organization": result.organization,
        "job_title": result.job_title,
        "birthday": str(result.birthday) if result.birthday else None,
        "anniversary": str(result.anniversary) if result.anniversary else None,
        "notes": result.notes,
        "website": result.website,
        "emails": [{"label": e.label, "email": e.email, "is_primary": e.is_primary} for e in result.emails],
        "phones": [{"label": p.label, "phone_number": p.phone_number, "is_primary": p.is_primary} for p in result.phones],
        "addresses": [
            {
                "label": a.label,
                "street": a.street,
                "city": a.city,
                "region": a.region,
                "postal_code": a.postal_code,
                "country": a.country,
            }
            for a in result.addresses
        ],
    }


# ── Collection handlers ───────────────────────────────────────────────────────

def _collection_to_dict(col) -> dict:
    return {
        "id": str(col.id),
        "name": col.name,
        "icon": col.icon,
        "domain": col.domain,
        "sort_order": col.sort_order,
        "auto_create_rule": col.auto_create_rule.model_dump() if col.auto_create_rule else None,
        "default_tags": [str(t) for t in col.default_tags],
    }


async def _list_collections(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.collections import service as svc

    result = await svc.list_collections(db, household_id)
    return {
        "total": result.total,
        "collections": [_collection_to_dict(c) for c in result.items],
    }


async def _ensure_today_collection(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.collections import service as svc

    try:
        collection_id = uuid.UUID(inp["collection_id"])
    except (KeyError, ValueError):
        return {"error": "collection_id is required and must be a valid UUID."}

    result = await svc.ensure_today_entry(db, collection_id, household_id, user_id)
    if result is None:
        return {
            "error": "Collection not found or has no auto_create_rule.",
            "hint": "Use list_collections to find a collection with auto_create_rule set.",
        }
    return {
        "created": result.created,
        "item_id": str(result.item_id),
        "item_domain": result.item_domain,
    }


async def _create_collection(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.collections import service as svc
    from life_dashboard.domains.collections.schemas import AutoCreateRule, CollectionCreate

    auto_create_rule = None
    if inp.get("auto_create_daily"):
        title_template = inp.get("title_template", "%B %d, %Y")
        auto_create_rule = AutoCreateRule(frequency="daily", title_template=title_template)

    data = CollectionCreate(
        name=inp["name"],
        icon=inp.get("icon"),
        domain=inp["domain"],
        auto_create_rule=auto_create_rule,
    )
    result = await svc.create_collection(db, household_id, user_id, data)
    return _collection_to_dict(result)


async def _update_collection(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.collections import service as svc
    from life_dashboard.domains.collections.schemas import AutoCreateRule, CollectionUpdate

    try:
        collection_id = uuid.UUID(inp["collection_id"])
    except (KeyError, ValueError):
        return {"error": "collection_id is required and must be a valid UUID."}

    update_kwargs: dict = {}
    if "name" in inp:
        update_kwargs["name"] = inp["name"]
    if "icon" in inp:
        update_kwargs["icon"] = inp["icon"]

    # Handle auto_create_daily toggle
    if "auto_create_daily" in inp:
        if inp["auto_create_daily"]:
            title_template = inp.get("title_template", "%B %d, %Y")
            update_kwargs["auto_create_rule"] = AutoCreateRule(
                frequency="daily", title_template=title_template
            )
        else:
            update_kwargs["auto_create_rule"] = None
    elif "title_template" in inp:
        # template change only — need to fetch existing rule to preserve frequency
        existing = await svc.get_collection(db, collection_id, household_id)
        if existing and existing.auto_create_rule:
            update_kwargs["auto_create_rule"] = AutoCreateRule(
                frequency=existing.auto_create_rule.frequency,
                title_template=inp["title_template"],
            )

    if not update_kwargs:
        return {"error": "No fields provided to update.", "hint": "Send at least one of: name, icon, auto_create_daily, title_template."}

    data = CollectionUpdate(**update_kwargs)
    result = await svc.update_collection(db, collection_id, household_id, data)
    if result is None:
        return {"error": f"Collection {collection_id} not found."}
    return _collection_to_dict(result)


async def _delete_collection(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.collections import service as svc

    try:
        collection_id = uuid.UUID(inp["collection_id"])
    except (KeyError, ValueError):
        return {"error": "collection_id is required and must be a valid UUID."}

    deleted = await svc.delete_collection(db, collection_id, household_id)
    if not deleted:
        return {"error": f"Collection {collection_id} not found."}
    return {"deleted": True, "collection_id": str(collection_id)}


# ── Project lifecycle handlers ────────────────────────────────────────────────

async def _archive_project(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.projects import service as svc

    try:
        project_id = uuid.UUID(inp["project_id"])
    except (KeyError, ValueError):
        return {"error": "project_id is required and must be a valid UUID."}

    result, err = await svc.archive_project(db, project_id, household_id)
    if err == "not_found":
        return {"error": f"Project {project_id} not found.", "hint": "Use list_projects to find the correct ID."}
    if err == "system_protected":
        return {"error": "System projects cannot be archived."}
    return {
        "archived": True,
        "id": str(result.id),
        "name": result.name,
        "status": result.status,
    }


async def _delete_project(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from life_dashboard.domains.projects import service as svc

    try:
        project_id = uuid.UUID(inp["project_id"])
    except (KeyError, ValueError):
        return {"error": "project_id is required and must be a valid UUID."}

    deleted, err = await svc.delete_project(db, project_id, household_id)
    if err == "not_found":
        return {"error": f"Project {project_id} not found.", "hint": "Use list_projects to find the correct ID."}
    if err == "system_protected":
        return {"error": "System projects cannot be deleted."}
    return {"deleted": True, "project_id": str(project_id)}


# ── Budget tool handlers ──────────────────────────────────────────────────────

async def _get_budget_summary(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from sqlalchemy import select, func as sa_func
    from life_dashboard.domains.budget.models import BudgetTransaction

    validated = _GetBudgetSummaryInput.model_validate(inp)

    filters = [
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.date >= validated.date_from,
        BudgetTransaction.date <= validated.date_to,
        BudgetTransaction.archived_at.is_(None),
        BudgetTransaction.is_transfer.is_(False),
    ]
    if validated.account_id:
        filters.append(BudgetTransaction.account_id == validated.account_id)

    stmt = select(
        sa_func.sum(BudgetTransaction.amount).label("net"),
        sa_func.count(BudgetTransaction.id).label("count"),
    ).where(*filters)

    # Income = positive amounts; expenses = negative amounts
    income_stmt = select(
        sa_func.coalesce(sa_func.sum(BudgetTransaction.amount), 0).label("total")
    ).where(*filters, BudgetTransaction.amount > 0)

    expense_stmt = select(
        sa_func.coalesce(sa_func.sum(BudgetTransaction.amount), 0).label("total")
    ).where(*filters, BudgetTransaction.amount < 0)

    summary_row = (await db.execute(stmt)).one()
    income_row = (await db.execute(income_stmt)).one()
    expense_row = (await db.execute(expense_stmt)).one()

    total_income = float(income_row.total or 0)
    total_expenses = float(expense_row.total or 0)  # negative number
    net = float(summary_row.net or 0)

    return {
        "date_from": validated.date_from.isoformat(),
        "date_to": validated.date_to.isoformat(),
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),          # negative = money out
        "total_expenses_abs": round(abs(total_expenses), 2), # positive for readability
        "net": round(net, 2),
        "transaction_count": summary_row.count or 0,
    }


async def _list_budget_transactions(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from datetime import timedelta
    from sqlalchemy import select, or_
    from life_dashboard.domains.budget.models import (
        BudgetTransaction, BudgetCategory, BudgetAccount,
    )

    validated = _ListBudgetTransactionsInput.model_validate(inp)

    today = date.today()
    date_from = validated.date_from or (today - timedelta(days=30))
    date_to = validated.date_to or today

    filters = [
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.date >= date_from,
        BudgetTransaction.date <= date_to,
        BudgetTransaction.archived_at.is_(None),
    ]
    if not validated.include_transfers:
        filters.append(BudgetTransaction.is_transfer.is_(False))
    if validated.account_id:
        filters.append(BudgetTransaction.account_id == validated.account_id)
    if validated.category_id:
        filters.append(BudgetTransaction.category_id == validated.category_id)
    if validated.search:
        q = f"%{validated.search.lower()}%"
        filters.append(
            or_(
                BudgetTransaction.description.ilike(q),
                BudgetTransaction.merchant_name.ilike(q),
            )
        )

    stmt = (
        select(
            BudgetTransaction.id,
            BudgetTransaction.date,
            BudgetTransaction.amount,
            BudgetTransaction.description,
            BudgetTransaction.merchant_name,
            BudgetTransaction.is_transfer,
            BudgetTransaction.category_id,
            BudgetTransaction.account_id,
        )
        .where(*filters)
        .order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())
        .limit(validated.limit)
    )

    rows = (await db.execute(stmt)).all()

    # Batch-fetch category and account names to avoid N+1
    cat_ids = {r.category_id for r in rows if r.category_id}
    acct_ids = {r.account_id for r in rows}

    cat_names: dict[uuid.UUID, str] = {}
    if cat_ids:
        cat_rows = (await db.execute(
            select(BudgetCategory.id, BudgetCategory.name).where(
                BudgetCategory.id.in_(cat_ids)
            )
        )).all()
        cat_names = {r.id: r.name for r in cat_rows}

    acct_names: dict[uuid.UUID, str] = {}
    if acct_ids:
        acct_rows = (await db.execute(
            select(BudgetAccount.id, BudgetAccount.name).where(
                BudgetAccount.id.in_(acct_ids)
            )
        )).all()
        acct_names = {r.id: r.name for r in acct_rows}

    transactions = [
        {
            "id": str(r.id),
            "date": r.date.isoformat(),
            "amount": float(r.amount),
            "description": r.description,
            "merchant": r.merchant_name,
            "category": cat_names.get(r.category_id) if r.category_id else None,
            "account": acct_names.get(r.account_id),
            "is_transfer": r.is_transfer,
        }
        for r in rows
    ]

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "count": len(transactions),
        "transactions": transactions,
    }


async def _get_spending_by_category(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from sqlalchemy import select, func as sa_func
    from life_dashboard.domains.budget.models import BudgetTransaction, BudgetCategory

    validated = _GetSpendingByCategoryInput.model_validate(inp)

    filters = [
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.date >= validated.date_from,
        BudgetTransaction.date <= validated.date_to,
        BudgetTransaction.archived_at.is_(None),
        BudgetTransaction.is_transfer.is_(False),
        BudgetTransaction.amount < 0,  # expenses only
    ]
    if validated.account_id:
        filters.append(BudgetTransaction.account_id == validated.account_id)

    stmt = (
        select(
            BudgetTransaction.category_id,
            sa_func.sum(BudgetTransaction.amount).label("total"),
            sa_func.count(BudgetTransaction.id).label("count"),
        )
        .where(*filters)
        .group_by(BudgetTransaction.category_id)
        .order_by(sa_func.sum(BudgetTransaction.amount))  # most negative first = biggest spend
    )

    rows = (await db.execute(stmt)).all()

    # Fetch category names
    cat_ids = {r.category_id for r in rows if r.category_id}
    cat_names: dict[uuid.UUID, str] = {}
    if cat_ids:
        cat_rows = (await db.execute(
            select(BudgetCategory.id, BudgetCategory.name).where(
                BudgetCategory.id.in_(cat_ids)
            )
        )).all()
        cat_names = {r.id: r.name for r in cat_rows}

    grand_total_abs = sum(abs(float(r.total)) for r in rows) or 1.0

    categories = [
        {
            "category_id": str(r.category_id) if r.category_id else None,
            "category": cat_names.get(r.category_id, "Uncategorized") if r.category_id else "Uncategorized",
            "total": round(float(r.total), 2),           # negative
            "total_abs": round(abs(float(r.total)), 2),  # positive for readability
            "transaction_count": r.count,
            "percentage": round(abs(float(r.total)) / grand_total_abs * 100, 1),
        }
        for r in rows
    ]

    return {
        "date_from": validated.date_from.isoformat(),
        "date_to": validated.date_to.isoformat(),
        "total_spending_abs": round(grand_total_abs, 2),
        "categories": categories,
    }


async def _get_account_balances(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> dict:
    from sqlalchemy import select
    from life_dashboard.domains.budget.models import BudgetAccount

    stmt = select(BudgetAccount).where(
        BudgetAccount.household_id == household_id,
        BudgetAccount.archived_at.is_(None),
    ).order_by(BudgetAccount.name)

    rows = (await db.execute(stmt)).scalars().all()

    accounts = [
        {
            "id": str(a.id),
            "name": a.name,
            "type": a.account_type,
            "scope": a.scope,
            "current_balance": float(a.current_balance) if a.current_balance is not None else None,
            "balance_updated_at": a.balance_updated_at.isoformat() if a.balance_updated_at else None,
            "teller_linked": bool(a.teller_account_id),
            "teller_institution": a.teller_institution_name,
            "teller_last_synced_at": a.teller_last_synced_at.isoformat() if a.teller_last_synced_at else None,
        }
        for a in rows
    ]

    total_balance = sum(
        a["current_balance"] for a in accounts if a["current_balance"] is not None
    )

    return {
        "accounts": accounts,
        "total_balance": round(total_balance, 2),
    }


async def _set_category_budget(
    db: AsyncSession,
    inp: dict,
    household_id: uuid.UUID,
) -> dict:
    from sqlalchemy import select
    from life_dashboard.domains.budget.models import BudgetCategory

    validated = _SetCategoryBudgetInput.model_validate(inp)

    # Case-insensitive name match within this household
    stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.archived_at.is_(None),
    )
    rows = (await db.execute(stmt)).scalars().all()
    search = validated.category_name.strip().lower()
    matches = [c for c in rows if c.name.lower() == search]

    if not matches:
        # Fuzzy fallback: partial match
        matches = [c for c in rows if search in c.name.lower()]

    if not matches:
        available = sorted(c.name for c in rows)
        return {
            "error": f"No category found matching '{validated.category_name}'.",
            "hint": "Use one of the exact category names.",
            "available_categories": available,
        }

    if len(matches) > 1:
        return {
            "error": f"'{validated.category_name}' matched multiple categories.",
            "hint": "Use the exact category name from the list.",
            "matches": [c.name for c in matches],
        }

    category = matches[0]
    old_amount = float(category.default_monthly_amount) if category.default_monthly_amount is not None else None
    category.default_monthly_amount = validated.amount
    category.updated_at = datetime.now(timezone.utc)

    # Keep any spending_cap goals linked to this category in sync
    from life_dashboard.domains.goals.models import Goal
    goals_stmt = select(Goal).where(
        Goal.household_id == household_id,
        Goal.financial_link.isnot(None),
    )
    linked_goals = (await db.execute(goals_stmt)).scalars().all()
    category_id_str = str(category.id)
    for goal in linked_goals:
        link = goal.financial_link or {}
        if link.get("type") == "spending_cap" and link.get("category_id") == category_id_str:
            updated_link = dict(link)
            updated_link["monthly_limit"] = validated.amount
            goal.financial_link = updated_link

    await db.commit()

    return {
        "updated": True,
        "category_id": str(category.id),
        "category_name": category.name,
        "previous_target": old_amount,
        "new_target": validated.amount,
    }


async def _update_profile(
    db: AsyncSession,
    tool_input: dict,
    user_id: uuid.UUID,
) -> dict:
    """Apply a chat-driven profile revision.

    Mirrors the silent-learning path used by the bootstrap pass and the
    notes-driven proposer: write directly to member_ai_memory.memory_text
    and record an audit row (status='accepted'). The user never sees a
    pending-updates queue.
    """
    from life_dashboard.ai.models import UserProfileUpdate
    from life_dashboard.ai.profile_service import (
        PROFILE_HARD_CAP_CHARS,
        get_or_create_memory,
        _apply_profile_update,
    )

    content_md = (tool_input.get("content_md") or "").strip()
    if not content_md:
        return {
            "error": "content_md is required and must be non-empty.",
            "hint": (
                "Pass the FULL revised profile as markdown sectioned by H2 "
                "headers. See the tool description for the expected sections."
            ),
        }
    if len(content_md) > PROFILE_HARD_CAP_CHARS:
        # Trim defensively rather than rejecting — the model often slightly
        # overshoots when integrating a change.
        content_md = content_md[:PROFILE_HARD_CAP_CHARS]

    diff_summary = (tool_input.get("diff_summary") or "").strip() or None

    memory = await get_or_create_memory(db, user_id)
    # Phase 4: snapshots previous content into user_profile_versions.
    now = await _apply_profile_update(db, memory, content_md, source="manual")

    audit = UserProfileUpdate(
        user_id=user_id,
        proposed_content_md=content_md,
        diff_summary=diff_summary or "Chat-driven profile revision",
        source="manual",
        status="accepted",
        resolved_at=now,
    )
    db.add(audit)
    await db.commit()

    return {
        "updated": True,
        "applied_at": now.isoformat(),
        "summary": diff_summary,
    }
