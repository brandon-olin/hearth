"""AI domain service layer.

All business logic for conversations, messages, memory, settings, and streaming.
No FastAPI imports here — only SQLAlchemy, Pydantic schemas, and the provider
abstraction.
"""
from __future__ import annotations

import json
import logging
import uuid
from asyncio import shield
from datetime import date, datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai.models import (
    AiConversation,
    AiMessage,
    AiMessageRole,
    AiProvider,
    AiSettings,
    AiUsage,
    MemberAiMemory,
)
from life_dashboard.ai.provider import AIProvider, AnthropicProvider
from life_dashboard.ai.tools import TOOL_DEFINITIONS, execute_tool
from life_dashboard.ai.schemas import (
    AiSettingsResponse,
    AiSettingsUpdate,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    MessageResponse,
    MessageSearchItem,
    MessageSearchResponse,
    UsageModelBreakdown,
    UsageSummaryResponse,
)
from life_dashboard.auth.models import User
from life_dashboard.core.settings import settings as app_settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Refresh user memory after this many new conversations since the last refresh.
_MEMORY_REFRESH_THRESHOLD = 5

# Hard cap on memory text length in characters (~600 tokens).
_MEMORY_MAX_CHARS = 2_400

# Number of recent messages loaded into context for each chat turn.
_CONTEXT_MESSAGE_LIMIT = 20

# Number of recent messages (across all conversations) used to refresh memory.
_MEMORY_SOURCE_MESSAGE_LIMIT = 150

# Maximum characters shown as a snippet in search results.
_SNIPPET_MAX_CHARS = 300


# ── Provider factory ──────────────────────────────────────────────────────────

def get_provider(user_settings: AiSettings) -> AIProvider | None:
    """Return the appropriate AI provider for this user's settings.

    Resolution order:
      1. User's BYOK key (api_key_encrypted) if present.
      2. System-level ANTHROPIC_API_KEY env var.
      3. None — caller should return 503.

    """
    api_key: str | None = None

    if user_settings.api_key_encrypted:
        api_key = user_settings.api_key_encrypted  # decrypted transparently by EncryptedText
    elif app_settings.anthropic_api_key:
        api_key = app_settings.anthropic_api_key

    if not api_key:
        return None

    if user_settings.provider == AiProvider.anthropic:
        return AnthropicProvider(api_key)

    # TODO: return OpenAIProvider / OllamaProvider when implemented
    logger.warning("Provider %s not yet implemented; falling back to None", user_settings.provider)
    return None


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_or_create_settings(db: AsyncSession, user_id: uuid.UUID) -> AiSettings:
    result = await db.execute(
        select(AiSettings).where(AiSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = AiSettings(user_id=user_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


def _settings_to_response(s: AiSettings) -> AiSettingsResponse:
    return AiSettingsResponse(
        provider=s.provider.value,
        retention_days=s.retention_days,
        has_custom_key=s.api_key_encrypted is not None,
        ai_journal_extraction_enabled=s.ai_journal_extraction_enabled,
    )


async def get_settings(db: AsyncSession, user_id: uuid.UUID) -> AiSettingsResponse:
    s = await get_or_create_settings(db, user_id)
    return _settings_to_response(s)


async def update_settings(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: AiSettingsUpdate,
) -> AiSettingsResponse:
    s = await get_or_create_settings(db, user_id)
    sent = data.model_fields_set

    if "provider" in sent and data.provider is not None:
        s.provider = AiProvider(data.provider)

    if "retention_days" in sent:
        # Explicit None means "keep forever"; integer means that many days.
        s.retention_days = data.retention_days

    if data.clear_api_key:
        s.api_key_encrypted = None
    elif data.api_key is not None:
        s.api_key_encrypted = data.api_key  # encrypted transparently by EncryptedText

    if "ai_journal_extraction_enabled" in sent and data.ai_journal_extraction_enabled is not None:
        s.ai_journal_extraction_enabled = data.ai_journal_extraction_enabled

    await db.commit()
    await db.refresh(s)
    return _settings_to_response(s)


# ── Memory ────────────────────────────────────────────────────────────────────

async def get_or_create_memory(db: AsyncSession, user_id: uuid.UUID) -> MemberAiMemory:
    result = await db.execute(
        select(MemberAiMemory).where(MemberAiMemory.user_id == user_id)
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        memory = MemberAiMemory(user_id=user_id)
        db.add(memory)
        await db.commit()
        await db.refresh(memory)
    return memory


def _memory_refresh_system_prompt(display_name: str, current_memory: str) -> str:
    parts = [
        f"You are updating a personal memory profile for {display_name}'s household AI assistant.",
        "Based on the conversation history provided, produce a concise memory document that captures:",
        "- Preferences, habits, and patterns",
        "- Ongoing projects, goals, or recurring responsibilities",
        "- Useful household context (people, routines, notable setups)",
        "- Anything that would help an AI assistant give better, more personalised responses",
        "",
        "Rules:",
        "- Write as bullet points, present tense",
        "- Stay under 2400 characters total",
        "- Omit one-off details; focus on stable facts and patterns",
        "- Do NOT include dates, timestamps, or conversation metadata",
        "- Output ONLY the updated memory text — no preamble, no commentary",
    ]
    if current_memory.strip():
        parts += ["", "Current memory (update or replace as needed):", current_memory.strip()]
    return "\n".join(parts)


async def maybe_refresh_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    display_name: str,
    provider: AIProvider,
) -> None:
    """Lazily refresh user memory if enough new conversations have accumulated.

    Called after each chat turn completes. Does nothing if the threshold has
    not been reached. Failures are logged and swallowed — memory refresh is
    non-critical and should never disrupt the chat flow.
    """
    try:
        memory = await get_or_create_memory(db, user_id)
        total_count = await _get_conversation_count(db, user_id)

        new_since_refresh = total_count - memory.conversation_count_at_last_update
        if new_since_refresh < _MEMORY_REFRESH_THRESHOLD:
            return

        # Fetch recent message content to feed into the refresh prompt.
        recent_text = await _get_recent_message_text_for_memory(db, user_id)
        if not recent_text.strip():
            return

        updated, mem_input_tok, mem_output_tok, mem_model = await provider.complete(
            messages=[{"role": "user", "content": recent_text}],
            system=_memory_refresh_system_prompt(display_name, memory.memory_text),
            max_tokens=1024,
        )

        if updated.strip():
            memory.memory_text = updated.strip()[:_MEMORY_MAX_CHARS]
            memory.last_updated_at = datetime.now(tz=timezone.utc)
            memory.conversation_count_at_last_update = total_count

            # Record usage for the background memory-refresh call.
            if mem_input_tok > 0 or mem_output_tok > 0:
                try:
                    await record_usage(
                        db,
                        user_id=user_id,
                        conversation_id=None,
                        input_tokens=mem_input_tok,
                        output_tokens=mem_output_tok,
                        model=mem_model,
                        turn_kind="memory_refresh",
                    )
                except Exception:
                    logger.exception("Usage recording failed during memory refresh — ignoring")

            await db.commit()
            logger.info("Memory refreshed for user %s (total conversations: %d)", user_id, total_count)

    except Exception:
        logger.exception("Memory refresh failed for user %s — skipping", user_id)


async def _get_conversation_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(AiConversation).where(
            AiConversation.user_id == user_id
        )
    )
    return result.scalar_one() or 0


async def _get_recent_message_text_for_memory(
    db: AsyncSession, user_id: uuid.UUID
) -> str:
    """Return a concatenated string of recent messages for use in the memory prompt."""
    stmt = (
        select(AiMessage.role, AiMessage.content)
        .join(AiConversation, AiMessage.conversation_id == AiConversation.id)
        .where(
            AiConversation.user_id == user_id,
            AiMessage.role.in_([AiMessageRole.user, AiMessageRole.assistant]),
        )
        .order_by(AiMessage.created_at.desc())
        .limit(_MEMORY_SOURCE_MESSAGE_LIMIT)
    )
    rows = (await db.execute(stmt)).all()
    lines = [f"{row.role}: {row.content}" for row in reversed(rows)]
    return "\n\n".join(lines)


# ── Conversations ─────────────────────────────────────────────────────────────

def _auto_title(first_message: str) -> str:
    """Generate a short title from the first user message."""
    text = first_message.strip().replace("\n", " ")
    if len(text) <= 60:
        return text
    truncated = text[:57]
    last_space = truncated.rfind(" ")
    if last_space > 30:
        truncated = truncated[:last_space]
    return truncated + "…"


async def create_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    first_message: str,
) -> AiConversation:
    conv = AiConversation(
        user_id=user_id,
        household_id=household_id,
        title=_auto_title(first_message),
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> AiConversation | None:
    result = await db.execute(
        select(AiConversation).where(
            AiConversation.id == conversation_id,
            AiConversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> ConversationListResponse:
    count_result = await db.execute(
        select(func.count()).select_from(AiConversation).where(
            AiConversation.user_id == user_id
        )
    )
    total = count_result.scalar_one() or 0

    rows = list((await db.execute(
        select(AiConversation)
        .where(AiConversation.user_id == user_id)
        .order_by(AiConversation.last_message_at.desc())
        .limit(limit)
        .offset(offset)
    )).scalars().all())

    return ConversationListResponse(
        items=[ConversationResponse.model_validate(c) for c in rows],
        total=total,
    )


async def get_conversation_detail(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ConversationDetailResponse | None:
    conv = await get_conversation(db, conversation_id, user_id)
    if conv is None:
        return None

    messages = await get_recent_messages(
        db, conversation_id, limit=_CONTEXT_MESSAGE_LIMIT * 5
    )
    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        last_message_at=conv.last_message_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


async def delete_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Delete a conversation and all its messages. Returns True if it existed."""
    conv = await get_conversation(db, conversation_id, user_id)
    if conv is None:
        return False
    await db.execute(
        delete(AiConversation).where(AiConversation.id == conversation_id)
    )
    await db.commit()
    return True


async def _touch_conversation(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    """Update last_message_at to now."""
    await db.execute(
        update(AiConversation)
        .where(AiConversation.id == conversation_id)
        .values(last_message_at=datetime.now(tz=timezone.utc))
    )


# ── Messages ──────────────────────────────────────────────────────────────────

async def append_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    role: AiMessageRole,
    content: str,
) -> AiMessage:
    msg = AiMessage(conversation_id=conversation_id, role=role, content=content)
    db.add(msg)
    await db.flush()   # populate msg.id without committing yet
    return msg


async def get_recent_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int = _CONTEXT_MESSAGE_LIMIT,
) -> list[AiMessage]:
    """Return the most recent messages in chronological order."""
    # Fetch latest N then reverse so the result is oldest-first (correct for
    # passing to the AI as a conversation history).
    subq = (
        select(AiMessage)
        .where(AiMessage.conversation_id == conversation_id)
        .order_by(AiMessage.created_at.desc())
        .limit(limit)
    ).subquery()

    rows = list((await db.execute(
        select(AiMessage)
        .where(AiMessage.id == subq.c.id)
        .order_by(AiMessage.created_at.asc())
    )).scalars().all())
    return rows


async def search_messages(
    db: AsyncSession,
    user_id: uuid.UUID,
    q: str,
    *,
    limit: int = 20,
) -> MessageSearchResponse:
    """Full-text search across all messages belonging to this user.

    On Postgres: uses the GIN index on ai_messages.search_vector via
    plainto_tsquery for accurate multi-word phrase matching.
    On SQLite: falls back to a simple LIKE search (no FTS index).
    """
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    q_like = f"%{q}%"

    base = (
        select(
            AiMessage.id,
            AiMessage.conversation_id,
            AiMessage.role,
            AiMessage.content,
            AiMessage.created_at,
            AiConversation.title.label("conversation_title"),
        )
        .join(AiConversation, AiMessage.conversation_id == AiConversation.id)
        .where(AiConversation.user_id == user_id)
        .order_by(AiMessage.created_at.desc())
        .limit(limit)
    )

    if dialect == "sqlite":
        stmt = base.where(AiMessage.content.ilike(q_like))
    else:
        # Postgres: use tsvector GIN index via raw SQL predicate.
        stmt = base.where(
            text("ai_messages.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
    rows = (await db.execute(stmt)).all()

    items = []
    for row in rows:
        # Simple snippet: first _SNIPPET_MAX_CHARS chars of the message content.
        snippet = row.content[:_SNIPPET_MAX_CHARS]
        if len(row.content) > _SNIPPET_MAX_CHARS:
            snippet += "…"
        items.append(MessageSearchItem(
            message_id=row.id,
            conversation_id=row.conversation_id,
            conversation_title=row.conversation_title,
            role=row.role.value,
            snippet=snippet,
            created_at=row.created_at,
        ))

    return MessageSearchResponse(items=items, total=len(items))


# ── Retention cleanup ─────────────────────────────────────────────────────────

async def apply_retention_policy(
    db: AsyncSession,
    user_id: uuid.UUID,
    retention_days: int,
) -> int:
    """Delete conversations (and their messages, via CASCADE) older than retention_days.

    Returns the number of conversations deleted. Called lazily at the start of
    each chat session — not on a cron schedule — which is sufficient for a
    small household install.
    """
    cutoff = text(
        "NOW() - (interval '1 day' * :days)"
    ).bindparams(days=retention_days)

    # First collect IDs so we can count them, then delete.
    old_ids = list((await db.execute(
        select(AiConversation.id).where(
            AiConversation.user_id == user_id,
            AiConversation.last_message_at < cutoff,
        )
    )).scalars().all())

    if old_ids:
        await db.execute(
            delete(AiConversation).where(AiConversation.id.in_(old_ids))
        )
        await db.commit()
        logger.info(
            "Retention cleanup: deleted %d conversation(s) for user %s (retention=%d days)",
            len(old_ids), user_id, retention_days,
        )

    return len(old_ids)


# ── Token usage ───────────────────────────────────────────────────────────────

async def record_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    input_tokens: int,
    output_tokens: int,
    model: str,
    turn_kind: str = "chat",
) -> None:
    """Persist a single token-usage record.  Failures are non-critical — the
    caller is responsible for catching and logging any exceptions."""
    row = AiUsage(
        user_id=user_id,
        conversation_id=conversation_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        turn_kind=turn_kind,
    )
    db.add(row)
    # Callers commit as part of their own transaction; we only flush here so
    # the row is visible within the same session if needed.
    await db.flush()


async def get_usage_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> UsageSummaryResponse:
    """Return token usage totals for the current calendar month, broken down
    by model.  Also includes a lifetime total for reference."""
    from sqlalchemy import case, literal_column

    # Current month totals grouped by model.
    monthly_stmt = (
        select(
            AiUsage.model,
            func.sum(AiUsage.input_tokens).label("input_tokens"),
            func.sum(AiUsage.output_tokens).label("output_tokens"),
        )
        .where(
            AiUsage.user_id == user_id,
            func.date_trunc("month", AiUsage.created_at)
            == func.date_trunc("month", func.now()),
        )
        .group_by(AiUsage.model)
        .order_by(AiUsage.model)
    )
    monthly_rows = (await db.execute(monthly_stmt)).all()

    breakdown = [
        UsageModelBreakdown(
            model=row.model,
            input_tokens=row.input_tokens or 0,
            output_tokens=row.output_tokens or 0,
        )
        for row in monthly_rows
    ]

    month_input = sum(b.input_tokens for b in breakdown)
    month_output = sum(b.output_tokens for b in breakdown)

    # Lifetime totals.
    lifetime_stmt = select(
        func.coalesce(func.sum(AiUsage.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(AiUsage.output_tokens), 0).label("output_tokens"),
    ).where(AiUsage.user_id == user_id)
    lt = (await db.execute(lifetime_stmt)).one()

    return UsageSummaryResponse(
        this_month_input_tokens=month_input,
        this_month_output_tokens=month_output,
        this_month_total_tokens=month_input + month_output,
        lifetime_input_tokens=lt.input_tokens,
        lifetime_output_tokens=lt.output_tokens,
        lifetime_total_tokens=lt.input_tokens + lt.output_tokens,
        by_model=breakdown,
    )


# ── Context assembly ──────────────────────────────────────────────────────────

def _build_system_prompt(user: User, memory_text: str) -> str:
    name = user.display_name or user.email
    today = date.today().strftime("%B %d, %Y")

    parts = [
        f"You are a helpful household assistant for {name}'s life dashboard.",
        f"Today's date is {today}.",
        "",
        "You can read and write household data: tasks, habits, goals, "
        "documents, notes, recipes, workouts, and calendar events.",
        "",
        "Guidelines:",
        "- Before creating data, briefly state what you're about to save "
        "(date, name, entry count) and wait for the user to confirm. "
        "For bulk imports, show a short plan first — e.g. '23 workouts from Jan–Dec 2026'.",
        "- **Before suggesting that the user CREATE or SET UP a habit, "
        "goal, project, recipe, or any other tracked entity, FIRST call "
        "the relevant list_* tool (list_habits, list_goals, list_projects, "
        "list_recipes, etc.) to see what already exists.** If something "
        "related is already there, REFERENCE it instead of suggesting a "
        "duplicate. Phrase it as 'I see you already have an X — want to "
        "talk about how that's been going?' rather than 'Want to set up X?' "
        "Only suggest creating something new when nothing related exists. "
        "This rule applies even when the user's message contains language "
        "that suggests new setup (e.g. 'I want to focus on drinking less' "
        "should trigger list_habits/list_goals before any setup suggestion).",
        "- When migrating data from a document, process in batches of 3 items. "
        "After each batch report what was saved (e.g. '✓ 2026-03-14 Upper A, ✓ 2026-03-16 Lower B, ✓ 2026-03-18 Upper A') "
        "and confirm with the user before continuing. Stop immediately if anything looks wrong.",
        "- If a tool call returns an error with a 'hint' field, read the hint and fix the input before retrying.",
        "- If a write fails, report the error clearly and ask how to proceed.",
        "- For read-only questions, answer directly without unnecessary caveats.",
        "- Be concise. This is a personal dashboard, not a general-purpose chatbot.",
        "",
        "Shorthand you should understand:",
        f"- 'me', 'my', 'I', or no person specified → {name} (the current user).",
        "- 'my todos' / 'the inbox' / no project specified → the default To-dos project.",
        "- When creating a todo, omit project_id and assigned_to — the tool assigns them automatically.",
        "",
        "Profile maintenance:",
        "- You have access to an `update_profile` tool that updates the "
        "user's long-term profile (the same one in '## What you know about "
        f"{name}' below, if any). Call it SILENTLY — do not ask permission, "
        "do not mention the tool or the profile — whenever the user tells "
        "you what they want you to focus on, mentions a habit or topic they "
        "want ongoing attention to, shares a stable value or preference, "
        "or makes a durable decision about themselves. Examples: 'focus "
        "more on consistency,' 'I've been drinking too much, help me with "
        "that,' 'stop bringing up the old job.' "
        "After calling, acknowledge in plain language ('Got it, I'll keep "
        "that in mind') without revealing that anything was saved.",
        "- Do NOT use update_profile for one-off events, today's mood, a "
        "single bad day, or transient details.",
    ]

    if memory_text.strip():
        parts += ["", f"## What you know about {name}", memory_text.strip()]

    return "\n".join(parts)


def _build_journal_system_prompt(user: User, memory_text: str) -> str:
    """journal-001: system prompt for guided journal sessions.

    Differs from the regular chat prompt in:
      - Adaptive register (rant mode vs reflective mode — read user's energy)
      - Never start with a question; open warmly
      - Never give advice unsolicited
      - Point at humans when the topic is interpersonal
      - Explicit role-clarity: not a therapist, not a friend, not a substitute
      - Only the update_profile tool is available (no read/write tools —
        this is a working space, not a task interface)
      - Short responses (1-3 sentences usually) — user does most of the talking
    """
    name = user.display_name or user.email
    today = date.today().strftime("%B %d, %Y")

    parts = [
        f"You are a journaling companion for {name}. Today is {today}.",
        "",
        "## What you are (and what you are not)",
        f"You are a tool that helps {name} think and feel. You are NOT a "
        "therapist, NOT a friend, and NOT a substitute for the people in "
        f"{name}'s life. {name} has friends, family, and relationships of "
        "their own — your job is to help them reflect, not to be company. "
        "Behave that way without ever needing to say it.",
        "",
        "## How to be",
        "- Open warmly, WITHOUT a question. Examples: 'How's today landing?', "
        "'I'm here — what's up?', 'Take your time.' Never lead with an interrogation.",
        f"- After the opening, READ {name}'s energy and MATCH it:",
        "  * If they're VENTING or RANTING — match them. Brief acknowledgements "
        "('yeah, that sounds rough', 'I hear you'). NO questions unless they "
        "ask. NO advice. NO reframes. Just hold space. They keep going until "
        "they wind down naturally — that IS the point.",
        "  * If they're REFLECTIVE or PLANNING — match them too. One focused "
        "question at a time. Help them stay on the thread. Don't pile on; let "
        f"{name} lead.",
        "- NEVER give advice unsolicited. If they ask for input, give it; "
        "otherwise stay out of the steering.",
        "- Keep responses SHORT — 1-3 sentences most of the time. You are not "
        f"the main voice here, {name} is.",
        "- Notice the wind-down (messages get shorter, less heated, they start "
        "summarising for themselves). When that happens, OFFER to wrap — don't "
        "push: 'Want me to pull together what came out of this? Or keep going?'",
        "",
        "## When humans are the answer, point at humans",
        f"If {name} is wrestling with anything interpersonal — a hard "
        "conversation that's pending, a relationship strain, missing someone, "
        "feeling like they hurt someone, feeling isolated — gently mention that "
        "talking to the person (or someone trusted in their life) is what "
        "actually moves the needle, not talking to you. Phrase it naturally, "
        "NOT as a disclaimer. Examples:",
        "- 'That sounds like something to talk to them about directly when "
        "you're ready.'",
        "- 'Worth bringing this to someone who knows you in real life.'",
        "- 'You don't have to figure this out alone — is there someone you "
        "could call?'",
        "Do this lightly. Once per session is plenty. Don't lecture.",
        "",
        "## Tools",
        "- You have ONE tool: update_profile. Use it SILENTLY (no permission "
        f"asks, no mention of the tool or profile) when {name} makes a "
        "durable statement about themselves they want carried forward — "
        "'I want to focus more on X moving forward', 'I'm done apologising for "
        "Y', etc. After calling, just acknowledge in plain language ('got it, "
        "I'll keep that in mind'). Do NOT use it for transient moods or "
        "one-off events.",
        "- You do NOT have access to read/write tools for tasks, habits, "
        "goals, recipes, etc. This is not the place to track things. If "
        f"{name} wants to set something up, suggest they do it after the "
        "session.",
    ]

    if memory_text.strip():
        parts += [
            "",
            f"## What you know about {name}",
            memory_text.strip(),
            "",
            "Let this profile inform your tone and what you reference. "
            "Do NOT name-drop it ('I see from your profile that...'). "
            f"If the profile mentions valuing relationships, family, or "
            "specific people, naturally surface that where it fits the "
            "moment.",
        ]

    return "\n".join(parts)


# journal-001: synthesis prompt used by POST /ai/journal/finish to produce
# the first-person summary that's saved as the journal entry.
_JOURNAL_SYNTHESIS_PROMPT = """You are synthesizing a journal session into a first-person summary the
user will save as their journal entry for today.

Read the transcript and write a markdown summary in 'I' voice that captures:
- The emotional arc of the session (where they started, where they landed)
- The main things they worked through
- Any decisions or commitments they came to
- Things they want to remember about today

Rules:
- First person ('I felt X', 'I noticed', 'I want to remember'). NEVER
  third person ('the user', 'they').
- 1-2 paragraphs. Dense. No filler. This is THEIR voice, distilled.
- Do NOT add what they did not say. If they didn't reach a conclusion,
  don't manufacture one — capture the unresolved-ness honestly.
- Do NOT summarize what YOU said in the session. The summary is about
  THEIR experience, not the back-and-forth.
- If there's a clear thing to carry into tomorrow (a phrase, an
  intention, a thing to remember), end on it. Otherwise end on the
  emotional truth of where they landed.
- Output ONLY the summary markdown. NO preamble like 'Here is your
  summary' or 'Today you...'."""


# journal-001 Phase B: opener prompt. Kept separate from the in-session
# journal prompt because openers have different constraints — must be
# short, must NOT end with a sharp question, must NOT direct the user.
_JOURNAL_OPENER_PROMPT = """You are writing the OPENING MESSAGE for a journaling session. The user
just opened the journal and hasn't said anything yet. Your job is to
greet them warmly and OPEN THE SPACE without directing it.

Rules:
- 1-2 sentences. Brief. Warm. Unhurried.
- DO NOT end with a sharp question that demands a specific answer.
  Open-ended invitations are fine ("Take your time", "I'm here") but
  not interrogations ("How was your meeting?").
- DO NOT name-drop the profile. Never say 'I see from your profile…'.
- If the recent narrative shows they've been struggling (harsh self-talk
  streak, low sentiment), be gentler ("Hey. How are you holding up?",
  "I'm here — no rush."). If it's neutral or positive, be neutral
  ("How's today landing?", "What's on your mind?").
- If a dominant recent theme stands out AND it feels natural to
  reference (without sounding like a homework checkpoint), you may.
  Examples: "You've been chewing on consistency lately — anything come
  up there?" but NOT "Did you exercise today like you said you would?"
- Honor the time of day. Morning openers feel like setting up;
  afternoon feels like checking in mid-stream; evening feels like
  winding down.
- Output ONLY the message text. No preamble. No 'Here is your opener'.
- DO NOT include the user's name. The chrome already shows whose
  journal this is."""


def _resolve_time_of_day_label(now_local: datetime | None = None) -> str:
    """Categorical bucket — 'morning' (4-11), 'afternoon' (11-17),
    'evening' (17-22), or 'late night' (22-4). Used in opener prompts.

    Falls back to the server's UTC clock when now_local is None — caller
    can pass the user's locale-adjusted time when we want to be precise.
    """
    if now_local is None:
        now_local = datetime.now(tz=timezone.utc)
    hour = now_local.hour
    if 4 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "late night"


async def generate_journal_opener(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    display_name: str,
) -> str:
    """journal-001 Phase B: write the AI's opening message for a brand-new
    journal session, personalized by profile + recent narrative + time
    of day.

    Always returns a usable string — on failure, falls back to a generic
    'I'm here. Take your time.' so the UI never has a blank opener.
    Caller is responsible for persisting the message as the first
    assistant turn.
    """
    try:
        from life_dashboard.ai.profile_service import load_profile_context
        from life_dashboard.ai.journal_signal_service import (
            sentiment_trend,
            harsh_self_talk_streak,
            dominant_themes_recent,
        )

        today = date.today()
        profile = await load_profile_context(db, user_id)

        sentiment: dict = {"avg_7d": None, "avg_30d": None, "delta": None}
        try:
            sentiment = await sentiment_trend(db, user_id, today)
        except Exception:
            pass

        harsh_streak = 0
        try:
            harsh_streak = await harsh_self_talk_streak(db, user_id, today)
        except Exception:
            pass

        themes: list[tuple[str, int]] = []
        try:
            themes = await dominant_themes_recent(
                db, user_id, today, window_days=14, top_n=3
            )
        except Exception:
            pass

        time_label = _resolve_time_of_day_label()

        # Compose a compact user message for the opener prompt.
        bits: list[str] = [f"Time of day: {time_label}."]
        if sentiment.get("avg_7d") is not None:
            bits.append(
                f"Recent journal sentiment (7d avg): {sentiment['avg_7d']:+.2f} "
                f"on a [-1,+1] scale."
            )
        if harsh_streak >= 2:
            bits.append(
                f"Self-talk: {harsh_streak} consecutive days of harsh self-talk "
                f"in their journal."
            )
        if themes:
            bits.append(
                "Dominant journal themes (last 14 days): "
                + ", ".join(f"{t} (×{c})" for t, c in themes)
            )
        if not profile:
            bits.append("Profile: empty (new user).")

        user_msg_lines = [
            "Compose the opening message for this user's journal session.",
            "",
            *bits,
        ]
        if profile:
            user_msg_lines += ["", profile]

        text, input_tok, output_tok, model = await provider.complete(
            messages=[{"role": "user", "content": "\n".join(user_msg_lines)}],
            system=_JOURNAL_OPENER_PROMPT,
            max_tokens=120,
        )

        if input_tok > 0 or output_tok > 0:
            try:
                await record_usage(
                    db,
                    user_id=user_id,
                    conversation_id=None,
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    model=model,
                    turn_kind="journal_opener",
                )
            except Exception:
                logger.exception("Usage recording failed for journal opener")

        cleaned = text.strip().strip('"').strip("'")
        # Defence: never return empty. Fall back to a known-good opener if
        # the model returned something unusable.
        if not cleaned or len(cleaned) > 400:
            return _fallback_opener(time_label, harsh_streak)
        return cleaned

    except Exception:
        logger.exception("generate_journal_opener failed — using fallback")
        return _fallback_opener(_resolve_time_of_day_label(), 0)


def _fallback_opener(time_label: str, harsh_streak: int) -> str:
    """Static fallback openers — used when the model call fails or returns
    something unusable. Kept warm + open, never a sharp question."""
    if harsh_streak >= 3:
        return "Hey. No rush — I'm here when you're ready."
    if time_label == "morning":
        return "Good morning. Take your time."
    if time_label == "evening":
        return "Welcome back. How's today landing?"
    if time_label == "late night":
        return "I'm here. Whatever's on your mind."
    return "I'm here. Take your time."


async def synthesize_journal_summary(
    db: AsyncSession,
    provider: AIProvider,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    display_name: str,
) -> tuple[str, str]:
    """Generate the first-person summary for a finished journal session.

    Returns (summary_md, transcript_md). The transcript is formatted for
    optional inclusion in the saved entry when the user toggles
    'Save with transcript'.
    """
    recent = await get_recent_messages(
        db, conversation_id, limit=_CONTEXT_MESSAGE_LIMIT * 4
    )
    if not recent:
        return "", ""

    # Build a readable transcript (the working artifact, only persisted
    # when the user opts in).
    transcript_lines: list[str] = []
    role_label = {
        AiMessageRole.user: "You",
        AiMessageRole.assistant: "Coach",
    }
    for msg in recent:
        label = role_label.get(msg.role, str(msg.role.value).title())
        transcript_lines.append(f"**{label}:** {msg.content.strip()}")
        transcript_lines.append("")
    transcript_md = "\n".join(transcript_lines).strip()

    # Build a flat textual rendering of the transcript for the model.
    flat = "\n".join(
        f"{role_label.get(m.role, str(m.role.value).title())}: {m.content.strip()}"
        for m in recent
    )
    user_msg = (
        f"Display name: {display_name}\n\n"
        f"Transcript of today's journal session:\n\n{flat}"
    )

    text, input_tok, output_tok, model = await provider.complete(
        messages=[{"role": "user", "content": user_msg}],
        system=_JOURNAL_SYNTHESIS_PROMPT,
        max_tokens=1024,
    )

    if input_tok > 0 or output_tok > 0:
        try:
            await record_usage(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                input_tokens=input_tok,
                output_tokens=output_tok,
                model=model,
                turn_kind="journal_synthesis",
            )
        except Exception:
            logger.exception("Usage recording failed for journal synthesis")

    return text.strip(), transcript_md


async def build_chat_context(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user: User,
    memory: MemberAiMemory,
) -> tuple[str, list[dict[str, str]]]:
    """Return (system_prompt, messages) ready to send to the provider.

    messages is a list of {"role": ..., "content": ...} dicts containing the
    last _CONTEXT_MESSAGE_LIMIT turns from this conversation, oldest first.

    journal-001: when the conversation's kind is 'journal', uses the
    journal-mode system prompt instead of the regular chat prompt. Caller
    (the /ai/chat endpoint) also restricts the tools array to update_profile
    in that case — see generate_stream's `tools` parameter.
    """
    # Branch by conversation kind. We look it up here rather than threading
    # it through every caller — the lookup is cheap and lives next to the
    # prompt selection it informs.
    conv = await db.get(AiConversation, conversation_id)
    is_journal = conv is not None and getattr(conv, "kind", "chat") == "journal"

    if is_journal:
        system = _build_journal_system_prompt(user, memory.memory_text)
    else:
        system = _build_system_prompt(user, memory.memory_text)

    recent = await get_recent_messages(db, conversation_id, limit=_CONTEXT_MESSAGE_LIMIT)
    messages = [{"role": msg.role.value, "content": msg.content} for msg in recent]

    return system, messages


# ── Streaming generator ───────────────────────────────────────────────────────

async def generate_stream(
    db: AsyncSession,
    provider: AIProvider,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    display_name: str,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Async generator that streams SSE events to the client.

    Runs the full tool-use loop: Claude may call database tools zero or more
    times before producing a final text response. Each tool call is announced
    to the client via a "tool_use" event so the UI can show progress.

    Event shapes:
      {"type": "delta",    "content": "<text chunk>"}
      {"type": "tool_use", "tool": "<tool_name>"}
      {"type": "done",     "conversation_id": "<uuid>", "message_id": "<uuid>"}
      {"type": "error",    "message": "<user-facing error text>"}

    The assistant's final text is saved to the DB after streaming completes.
    Memory refresh runs after the done event — non-critical, failure is ignored.
    """
    # Working copy of the message list — grows as tool turns are added.
    turn_messages: list[dict] = list(messages)
    # Only the final user-visible text is saved to DB / used for memory.
    final_text_parts: list[str] = []

    # journal-001: callers can restrict the available tools (journal-mode
    # passes [update_profile_def] only). Default = full toolset.
    active_tools: list[dict] = tools if tools is not None else TOOL_DEFINITIONS

    # Accumulated token counts across all rounds (each round is one API call).
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    response_model: str = ""

    # Safety cap: prevent runaway tool-use loops.
    _MAX_TOOL_ROUNDS = 5

    try:
        for _round in range(_MAX_TOOL_ROUNDS + 1):
            round_text: list[str] = []
            called_tools = False

            async for event_type, payload in provider.stream_chat(
                turn_messages, system, tools=active_tools
            ):
                if event_type == "text":
                    round_text.append(payload)
                    yield f"data: {json.dumps({'type': 'delta', 'content': payload})}\n\n"

                elif event_type == "rate_limited":
                    wait_secs = int(payload)
                    yield f"data: {json.dumps({'type': 'tool_use', 'tool': f'rate_limited_{wait_secs}s'})}\n\n"

                elif event_type == "done":
                    final_msg = payload

                    # ── Capture token usage from this round ───────────────────
                    usage = getattr(final_msg, "usage", None)
                    if usage is not None:
                        total_input_tokens += getattr(usage, "input_tokens", 0)
                        total_output_tokens += getattr(usage, "output_tokens", 0)
                    if not response_model:
                        response_model = getattr(final_msg, "model", "") or ""

                    tool_uses = [
                        blk for blk in final_msg.content
                        if getattr(blk, "type", None) == "tool_use"
                    ]

                    if not tool_uses:
                        # No tool calls — this is the final text response.
                        final_text_parts.extend(round_text)
                        # Inner loop ends naturally; called_tools stays False.
                        break

                    if _round == _MAX_TOOL_ROUNDS:
                        # Hit the safety cap; use whatever text we have.
                        final_text_parts.extend(round_text)
                        logger.warning(
                            "Tool-use loop hit %d-round cap for conversation %s",
                            _MAX_TOOL_ROUNDS, conversation_id,
                        )
                        break

                    # ── Execute tool calls ────────────────────────────────────
                    assistant_content: list[dict] = []
                    if round_text:
                        assistant_content.append({"type": "text", "text": "".join(round_text)})
                    for tu in tool_uses:
                        assistant_content.append({
                            "type": "tool_use",
                            "id": tu.id,
                            "name": tu.name,
                            "input": tu.input,
                        })
                    turn_messages.append({"role": "assistant", "content": assistant_content})

                    tool_results: list[dict] = []
                    for tu in tool_uses:
                        yield f"data: {json.dumps({'type': 'tool_use', 'tool': tu.name})}\n\n"
                        result = await execute_tool(db, tu.name, tu.input, household_id, user_id)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": json.dumps(result),
                        })

                    turn_messages.append({"role": "user", "content": tool_results})
                    called_tools = True
                    # Inner async for ends; outer loop continues to next round.

            # Break the outer loop when Claude gave a final answer (no tools called).
            if not called_tools:
                break

        # ── Save the final assistant response ─────────────────────────────────
        full_content = "".join(final_text_parts)
        if full_content:
            msg = await append_message(
                db, conversation_id, AiMessageRole.assistant, full_content
            )
            await _touch_conversation(db, conversation_id)

            # ── Persist token usage ────────────────────────────────────────────
            if total_input_tokens > 0 or total_output_tokens > 0:
                try:
                    await record_usage(
                        db,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        model=response_model,
                        turn_kind="chat",
                    )
                except Exception:
                    logger.exception(
                        "Usage recording failed for conversation %s — ignoring", conversation_id
                    )

            await db.commit()

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation_id), 'message_id': str(msg.id)})}\n\n"

            # Lazy memory refresh — non-critical, runs after done is sent.
            try:
                await maybe_refresh_memory(db, user_id, display_name, provider)
            except Exception:
                logger.exception("Post-stream memory refresh failed — ignoring")
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': 'The AI returned an empty response. Please try again.'})}\n\n"

    except Exception:
        logger.exception("Stream error for conversation %s", conversation_id)
        if final_text_parts:
            try:
                await append_message(
                    db, conversation_id, AiMessageRole.assistant, "".join(final_text_parts)
                )
                await db.commit()
            except Exception:
                pass
        yield f"data: {json.dumps({'type': 'error', 'message': 'An error occurred while generating the response. Please try again.'})}\n\n"
