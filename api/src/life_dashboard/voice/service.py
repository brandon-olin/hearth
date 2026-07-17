"""Alexa intent dispatch for Hearth (voice-002).

Turns a parsed Alexa envelope into a spoken response. The four custom intents —
AddGroceryItem, CreateTodo, CheckInHabit, QueryTodos — each authorize the
account-linking PAT (scope ∩ member ceiling) and then call the *same* domain
service functions the MCP write tools use, so idempotency and the visibility
model come for free and there is no second copy of the rules. A genuine write
records a ``source="voice"`` audit row, attributed to the acting token (and, for
a personal token, its owning member) exactly like the MCP path.

Everything a voice user could plausibly say maps to a short, natural reply;
missing slots, unknown habits, and empty lists all get a spoken explanation
rather than an error, because there is no screen to fall back to.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.audit import service as audit_service
from life_dashboard.audit.schemas import AuditSource
from life_dashboard.domains.grocery_lists import service as grocery_service
from life_dashboard.domains.grocery_lists.schemas import GroceryItemAdd
from life_dashboard.domains.habits import service as habits_service
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.schemas import TodoCreate
from life_dashboard.mcp.auth import PatIdentity
from life_dashboard.voice import auth as voice_auth
from life_dashboard.voice import schemas
from life_dashboard.voice.auth import INVALID_TOKEN, UNAUTHENTICATED, VoiceAuthError

_WELCOME = (
    "Welcome to Hearth. You can add to your shopping list, create a to-do, "
    "check off a habit, or ask how many to-dos you have today. What would you like?"
)
_HELP = (
    "You can say: add milk to my shopping list; create a to-do to call the dentist; "
    "check off flossing; or, how many to-dos do I have today?"
)
_REPROMPT = "What would you like to do?"
_FALLBACK = "Sorry, I didn't catch that. Say 'help' to hear what Hearth can do."

#: Membership role of the household-agent pseudo-member; its writes are
#: attributed to the token, not a person (mirrors mcp.audit_hook).
_AGENT_ROLE = "agent"


# ── Audit ──────────────────────────────────────────────────────────────────────

async def _record_write(
    db: AsyncSession,
    identity: PatIdentity,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict,
) -> None:
    """Log one genuine voice write. A household-agent (shared-device) token has
    no person behind it, so ``actor_user_id`` is null and only the token is on
    record. The entity write already committed in its service call, so the audit
    row is the only pending change — commit it here or it rolls back."""
    actor_user_id = None if identity.role == _AGENT_ROLE else identity.user_id
    await audit_service.record(
        db,
        household_id=identity.household_id,
        actor_user_id=actor_user_id,
        token_id=identity.pat_id,
        source=AuditSource.voice,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    await db.commit()


# ── Intent handlers ─────────────────────────────────────────────────────────────

async def _default_grocery_list_id(db: AsyncSession, identity: PatIdentity) -> uuid.UUID | None:
    """The caller's most recent visible active grocery list, or None — lets a
    user say "add milk" without naming a list. Mirrors the MCP tool."""
    lists = await grocery_service.list_grocery_lists(
        db, identity.household_id, identity.user_id, status="active", limit=1
    )
    return lists.items[0].id if lists.items else None


async def _add_grocery_item(db: AsyncSession, identity: PatIdentity, slots: dict[str, str]) -> str:
    item = slots.get("item")
    if not item:
        return "I didn't catch what to add to your shopping list."
    list_id = await _default_grocery_list_id(db, identity)
    if list_id is None:
        return "You don't have a shopping list yet. Create one in the Hearth app first."
    result, created = await grocery_service.add_grocery_item_idempotent(
        db, list_id, identity.household_id, identity.user_id, GroceryItemAdd(name=item)
    )
    if result is None:
        return "I couldn't find your shopping list."
    if created:
        await _record_write(
            db, identity, action="create", entity_type="grocery_item",
            entity_id=result.id, payload={"name": result.name, "list_id": str(list_id)},
        )
        return f"Added {result.name} to your shopping list."
    return f"{result.name} is already on your shopping list."


async def _create_todo(db: AsyncSession, identity: PatIdentity, slots: dict[str, str]) -> str:
    task = slots.get("task")
    if not task:
        return "I didn't catch the to-do."
    # Voice, like MCP, only ever creates shared household to-dos — never personal.
    todo, created = await todos_service.create_todo_idempotent(
        db, identity.household_id, identity.user_id,
        TodoCreate(title=task, visibility="household"),
    )
    if created:
        await _record_write(
            db, identity, action="create", entity_type="todo",
            entity_id=todo.id, payload={"title": todo.title},
        )
        return f"I've added a to-do: {todo.title}."
    return f"You already have a to-do for {todo.title}."


async def _check_in_habit(db: AsyncSession, identity: PatIdentity, slots: dict[str, str]) -> str:
    name = slots.get("habit")
    if not name:
        return "Which habit did you want to check off?"
    habit = await habits_service.get_habit_by_name(
        db, identity.household_id, identity.user_id, name
    )
    if habit is None:
        return f"I couldn't find a habit called {name}."
    occ, created = await habits_service.check_in_habit(
        db, habit.id, identity.household_id, identity.user_id, date.today()
    )
    if occ is None:
        return f"I couldn't check off {habit.name}."
    if created:
        await _record_write(
            db, identity, action="check_in", entity_type="habit_occurrence",
            entity_id=occ.id, payload={"habit_id": str(habit.id), "date": date.today().isoformat()},
        )
        return f"Nice work. I've checked off {habit.name} for today."
    return f"You've already checked off {habit.name} today."


async def _query_todos(db: AsyncSession, identity: PatIdentity, slots: dict[str, str]) -> str:
    today = date.today()
    result = await todos_service.list_todos(
        db, identity.household_id, identity.user_id,
        status="pending", due_date_from=today, due_date_to=today, limit=1,
    )
    n = result.total
    if n == 0:
        return "You have no to-dos due today."
    if n == 1:
        return "You have one to-do due today."
    return f"You have {n} to-dos due today."


#: intent name → (token scope domain, required action, handler).
_INTENTS = {
    "AddGroceryItem": ("grocery", "write", _add_grocery_item),
    "CreateTodo": ("todos", "write", _create_todo),
    "CheckInHabit": ("habits", "write", _check_in_habit),
    "QueryTodos": ("todos", "read", _query_todos),
}


# ── Dispatch ─────────────────────────────────────────────────────────────────

def _auth_error_response(exc: VoiceAuthError) -> dict:
    """Turn an authorization failure into speech. Missing or dead tokens get a
    LinkAccount card so the user can recover from the Alexa app; a scope/ceiling
    refusal is a plain 'no permission'."""
    if exc.reason == UNAUTHENTICATED:
        return schemas.link_account(
            "To use Hearth, link your account in the Alexa app, then try again."
        )
    if exc.reason == INVALID_TOKEN:
        return schemas.link_account(
            "I'm having trouble connecting to your Hearth account. "
            "Try re-linking it in the Alexa app."
        )
    return schemas.speak("Sorry, your account doesn't have permission to do that.")


async def dispatch(db: AsyncSession, envelope: schemas.AlexaEnvelope) -> dict:
    """Route a parsed Alexa request to a spoken response."""
    req = envelope.request

    if req.type == "LaunchRequest":
        return schemas.speak(_WELCOME, end_session=False, reprompt=_REPROMPT)
    if req.type == "SessionEndedRequest":
        # Alexa ignores the response to a session-end; acknowledge with an empty one.
        return {"version": "1.0", "response": {}}
    if req.type != "IntentRequest" or req.intent is None:
        return schemas.speak(_FALLBACK)

    name = req.intent.name
    if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
        return schemas.speak("Goodbye.")
    if name == "AMAZON.HelpIntent":
        return schemas.speak(_HELP, end_session=False, reprompt=_REPROMPT)

    entry = _INTENTS.get(name)
    if entry is None:
        # AMAZON.FallbackIntent and anything unmapped.
        return schemas.speak(_FALLBACK)

    scope_domain, action, handler = entry
    try:
        _pat, identity = await voice_auth.authorize(
            db, envelope.access_token, scope_domain, action
        )
    except VoiceAuthError as exc:
        return _auth_error_response(exc)

    slots = {
        slot_name: slot.value.strip()
        for slot_name, slot in (req.intent.slots or {}).items()
        if slot.value and slot.value.strip()
    }
    text = await handler(db, identity, slots)
    return schemas.speak(text)
