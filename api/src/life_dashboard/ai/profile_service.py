"""User profile service — Phase 1 of the AI coach redesign.

The user profile is a single markdown document stored on
member_ai_memory.memory_text (see ai/models.py for why that table is reused
rather than introducing a new user_profiles table — the column already exists,
the chatbot already reads it, and we want one canonical profile blob shared
between chat and coach).

This module owns:
  - Reading and directly-editing the profile
  - The proposed-update workflow (list / accept / reject)
  - The bootstrap pass that drafts the initial profile from existing
    notes, documents, and the last 90 days of behavioural data

Design reference: docs/ai-coach-redesign.md.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai.models import MemberAiMemory, UserProfileUpdate, UserProfileVersion
from life_dashboard.ai.provider import AIProvider
from life_dashboard.ai.schemas import (
    BootstrapResponse,
    ProfileResponse,
    ProfileUpdateResponse,
)
from life_dashboard.ai.service import get_or_create_memory, record_usage

logger = logging.getLogger(__name__)


# Hard cap matches the design doc. Soft cap is enforced in the proposer
# prompt (see _PROPOSER_SYSTEM_PROMPT) by asking the model to also propose
# a removal when content would grow past it.
PROFILE_HARD_CAP_CHARS = 8000
PROFILE_SOFT_CAP_CHARS = 4000

# Pulled into the bootstrap context — bigger than typical limits because
# this is a one-shot pass and we want signal density. The provider's
# context window is the real bound.
_BOOTSTRAP_NOTE_LIMIT = 50
_BOOTSTRAP_DOCUMENT_LIMIT = 20
_BOOTSTRAP_TODO_LOOKBACK_DAYS = 90
_BOOTSTRAP_PROMPT_CHAR_BUDGET = 24_000  # leave headroom for instructions

# Phase 1.5: notes-driven incremental proposer. After this many net-new
# notes have accumulated for a user (since notes_at_last_proposal), the
# proposer runs in the background and either creates a pending
# UserProfileUpdate or skips silently. Tuned conservatively — we'd rather
# under-trigger and have the user re-bootstrap occasionally than spam them
# with low-signal proposals.
_NOTES_PROPOSAL_THRESHOLD = 5
# How many recent notes to feed into the incremental proposer (smaller than
# bootstrap because we already have a current profile to revise).
_INCREMENTAL_NOTE_LIMIT = 15

# Phase 4: profile versioning. Cap the number of versions retained per user.
# Each new version triggers a trim of older rows beyond this count. 50 is
# enough history for debugging + rollback without unbounded growth — at one
# update per week, that's almost a year of trail.
PROFILE_VERSION_RETENTION = 50

# Phase 4: valid source values for UserProfileVersion / UserProfileUpdate.
PROFILE_UPDATE_SOURCES = {
    "bootstrap",
    "incremental",
    "manual",
    "scheduled",
    "direct_edit",
}


# ── Profile reads / direct edits ──────────────────────────────────────────────

def _memory_to_response(memory: MemberAiMemory) -> ProfileResponse:
    return ProfileResponse(
        content_md=memory.memory_text or "",
        last_updated_at=memory.last_updated_at,
        last_bootstrapped_at=memory.last_bootstrapped_at,
    )


async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> ProfileResponse:
    """Return the current accepted profile (creating an empty one if needed)."""
    memory = await get_or_create_memory(db, user_id)
    return _memory_to_response(memory)


async def _apply_profile_update(
    db: AsyncSession,
    memory: MemberAiMemory,
    new_content_md: str,
    *,
    source: str,
) -> datetime:
    """Phase 4: shared write path for ALL profile changes.

    Snapshots the CURRENT memory_text into user_profile_versions (so we
    never lose history), then overwrites memory_text with the new content,
    then trims oldest versions beyond PROFILE_VERSION_RETENTION.

    Returns the timestamp the change was applied at (callers may want to
    use it for last_updated_at coordination). Caller commits.

    Sources must be one of PROFILE_UPDATE_SOURCES — enforced at the
    boundary so a typo doesn't silently land an unrecognised value.
    """
    if source not in PROFILE_UPDATE_SOURCES:
        raise ValueError(
            f"Invalid profile-update source {source!r}; "
            f"expected one of {sorted(PROFILE_UPDATE_SOURCES)}"
        )

    now = datetime.now(tz=timezone.utc)
    old_content = (memory.memory_text or "").strip()

    # Snapshot the OLD content. We skip snapshotting when there's nothing
    # to remember — empty-string → empty-string transitions during the
    # very first bootstrap pass don't deserve history rows.
    if old_content:
        snapshot = UserProfileVersion(
            user_id=memory.user_id,
            content_md=old_content,
            source=source,
        )
        db.add(snapshot)
        # Trim the oldest rows for this user beyond the retention cap.
        # Done in the same transaction as the snapshot so they grow/trim
        # together — no risk of orphan growth on a failed commit.
        kept_ids = (await db.execute(
            select(UserProfileVersion.id)
            .where(UserProfileVersion.user_id == memory.user_id)
            .order_by(UserProfileVersion.created_at.desc())
            .limit(PROFILE_VERSION_RETENTION)
        )).scalars().all()
        if kept_ids:
            from sqlalchemy import delete as _sa_delete, not_
            await db.execute(
                _sa_delete(UserProfileVersion).where(
                    UserProfileVersion.user_id == memory.user_id,
                    not_(UserProfileVersion.id.in_(kept_ids)),
                )
            )

    memory.memory_text = new_content_md.strip()[:PROFILE_HARD_CAP_CHARS]
    memory.last_updated_at = now
    return now


async def update_profile(
    db: AsyncSession, user_id: uuid.UUID, content_md: str
) -> ProfileResponse:
    """Direct user edit. Bypasses the proposed-diff workflow by design —
    the user is always trusted to write their own profile directly.

    Phase 4: goes through _apply_profile_update so the previous content
    is snapshotted into user_profile_versions before overwrite.
    """
    memory = await get_or_create_memory(db, user_id)
    await _apply_profile_update(
        db, memory, (content_md or ""), source="direct_edit"
    )
    await db.commit()
    await db.refresh(memory)
    return _memory_to_response(memory)


# ── Proposed updates: list / accept / reject ──────────────────────────────────

async def list_profile_versions(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int = 50
) -> list[UserProfileVersion]:
    """Phase 4: return the user's profile version history (newest first).

    Debug surface — useful for inspecting how the profile has evolved or
    rolling back if the AI does something unexpected. No public UI; the
    GET /ai/profile/versions endpoint is the only consumer for now.
    """
    rows = (
        await db.execute(
            select(UserProfileVersion)
            .where(UserProfileVersion.user_id == user_id)
            .order_by(UserProfileVersion.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def list_pending_updates(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ProfileUpdateResponse]:
    rows = (
        await db.execute(
            select(UserProfileUpdate)
            .where(
                UserProfileUpdate.user_id == user_id,
                UserProfileUpdate.status == "pending",
            )
            .order_by(UserProfileUpdate.created_at.desc())
        )
    ).scalars().all()
    return [ProfileUpdateResponse.model_validate(u) for u in rows]


async def _get_update(
    db: AsyncSession, user_id: uuid.UUID, update_id: uuid.UUID
) -> UserProfileUpdate | None:
    result = await db.execute(
        select(UserProfileUpdate).where(
            UserProfileUpdate.id == update_id,
            UserProfileUpdate.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def accept_update(
    db: AsyncSession, user_id: uuid.UUID, update_id: uuid.UUID
) -> ProfileResponse | None:
    """Copy the proposed content into the profile and mark this update accepted.

    Side effect: any *other* still-pending updates for this user are marked
    `superseded` — they were drafted against the pre-accept content and would
    otherwise apply stale changes if accepted later.
    """
    update = await _get_update(db, user_id, update_id)
    if update is None or update.status != "pending":
        return None

    memory = await get_or_create_memory(db, user_id)
    memory.memory_text = update.proposed_content_md.strip()[:PROFILE_HARD_CAP_CHARS]
    memory.last_updated_at = datetime.now(tz=timezone.utc)

    update.status = "accepted"
    update.resolved_at = datetime.now(tz=timezone.utc)

    # Supersede any other still-pending updates for this user.
    other_pending = (
        await db.execute(
            select(UserProfileUpdate).where(
                UserProfileUpdate.user_id == user_id,
                UserProfileUpdate.status == "pending",
                UserProfileUpdate.id != update.id,
            )
        )
    ).scalars().all()
    now = datetime.now(tz=timezone.utc)
    for other in other_pending:
        other.status = "superseded"
        other.resolved_at = now

    await db.commit()
    await db.refresh(memory)
    return _memory_to_response(memory)


async def reject_update(
    db: AsyncSession, user_id: uuid.UUID, update_id: uuid.UUID
) -> bool:
    """Mark a proposed update as rejected. Profile content unchanged."""
    update = await _get_update(db, user_id, update_id)
    if update is None or update.status != "pending":
        return False
    update.status = "rejected"
    update.resolved_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return True


# ── Bootstrap pass ────────────────────────────────────────────────────────────

_PROPOSER_SYSTEM_PROMPT = """You are drafting (or revising) a user's personal profile for an AI life
coach and assistant. The profile is the long-term memory both surfaces read
on every interaction. It is the user's own document — you propose changes,
the user accepts or rejects.

## What belongs in the profile

The profile captures who this person is and what is *currently* true for
them, structured under these H2 sections (use exactly these headers,
omit sections that have no content rather than writing "none"):

## Current focuses
What this person is actively working on right now — projects, goals,
life situations they are navigating. Lean toward present-tense facts.

## Values & non-negotiables
What this person cares about, what they will not compromise on, how they
prefer to work and live. Phrased as observed values, not aspirations.

## Recurring patterns
Patterns that show up repeatedly — productivity rhythms, emotional
tendencies, ways they evaluate themselves. Phrase as observed patterns
("often X when Y"), never as fixed traits ("is X").

## What drains me
Things that consistently take energy, where the user has named them.

## What works for me
Things that consistently help — environments, practices, framings the
user has found useful.

## Things to not bring up unless I do
Topics the user has explicitly de-prioritized, or that they want to
raise on their own terms when they're ready.

## What you must NOT add

- Today's tasks, this week's to-do list, or any one-off event.
- Transient moods or a single bad day. The profile is for *patterns*.
- Lists of names, projects, or places without context about why they matter.
- Anything the user mentioned once and did not return to.
- Anything that reads as a fixed trait judgment ("user struggles with X").
  Prefer time-bounded observations ("recently has had trouble with X").
- Confidential details (medical, financial account numbers, government IDs).

## Output rules

- Output ONLY the proposed profile content as markdown, nothing else —
  no preamble, no commentary, no code fences.
- Stay under 4000 characters if possible; absolute ceiling 8000.
- If, after reading the source material, you have nothing profile-worthy
  to ADD or CHANGE versus the current profile, output exactly the single
  word: SKIP
  (Do not output an empty profile, do not re-emit the current profile
  unchanged.)
- When the source material does support a real change, output the FULL
  new profile (not a diff) — the user-facing accept flow replaces the
  entire content."""


def _section_or_empty(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    return [f"### {title}", *lines, ""]


async def _gather_bootstrap_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
) -> tuple[str, dict[str, int]]:
    """Read existing notes, documents, and behavioural data for this user.

    Returns a (prompt_text, counts) tuple. prompt_text is the user message
    fed to the proposer. counts is a debugging summary used in logs.
    """
    from life_dashboard.domains.notes.models import Note
    from life_dashboard.domains.documents.models import Document
    from life_dashboard.domains.todos.models import Todo
    from life_dashboard.domains.goals.models import Goal
    from life_dashboard.domains.projects.models import Project
    from life_dashboard.domains.habits.models import Habit

    counts: dict[str, int] = {}

    # ── Notes (most signal-dense source) ──────────────────────────────────────
    note_rows = (
        await db.execute(
            select(Note.title, Note.content_md, Note.created_at)
            .where(
                Note.household_id == household_id,
                Note.created_by_user_id == user_id,
                Note.archived_at.is_(None),
            )
            .order_by(Note.updated_at.desc())
            .limit(_BOOTSTRAP_NOTE_LIMIT)
        )
    ).all()
    counts["notes"] = len(note_rows)

    # ── Documents (long-form personal writing) ────────────────────────────────
    doc_rows = (
        await db.execute(
            select(Document.title, Document.description, Document.created_at)
            .where(
                Document.household_id == household_id,
                Document.created_by_user_id == user_id,
            )
            .order_by(Document.updated_at.desc())
            .limit(_BOOTSTRAP_DOCUMENT_LIMIT)
        )
    ).all()
    counts["documents"] = len(doc_rows)

    # ── Behavioural snapshot ──────────────────────────────────────────────────
    # privacy-001: scope every behavioural source to THIS user. The
    # profile is a long-term memory of this user; cross-pollinating it
    # with a partner's todos/goals/habits would teach the model that
    # the partner's behavior is the user's.
    ninety_days_ago = date.fromordinal(date.today().toordinal() - _BOOTSTRAP_TODO_LOOKBACK_DAYS)
    todo_rows = (
        await db.execute(
            select(Todo.title)
            .where(
                Todo.household_id == household_id,
                Todo.assigned_to_user_id == user_id,
                Todo.status == "done",
                func.date(Todo.completed_at) >= ninety_days_ago,
            )
            .order_by(Todo.completed_at.desc())
            .limit(80)
        )
    ).all()
    counts["completed_todos_90d"] = len(todo_rows)

    goal_rows = (
        await db.execute(
            select(Goal.title, Goal.status)
            .where(
                Goal.household_id == household_id,
                Goal.created_by_user_id == user_id,
                Goal.status.in_(["active", "paused"]),
            )
            .order_by(Goal.updated_at.desc())
            .limit(15)
        )
    ).all()
    counts["active_goals"] = len(goal_rows)

    project_rows = (
        await db.execute(
            select(Project.name, Project.status)
            .where(
                Project.household_id == household_id,
                Project.created_by_user_id == user_id,
                Project.status.notin_(["complete", "archived"]),
                Project.is_system == False,
            )
            .order_by(Project.updated_at.desc())
            .limit(15)
        )
    ).all()
    counts["active_projects"] = len(project_rows)

    habit_rows = (
        await db.execute(
            select(Habit.name)
            .where(
                Habit.household_id == household_id,
                Habit.created_by_user_id == user_id,
                Habit.status != "archived",
            )
            .order_by(Habit.updated_at.desc())
            .limit(20)
        )
    ).all()
    counts["active_habits"] = len(habit_rows)

    # ── Assemble the prompt, trimming to budget ───────────────────────────────
    parts: list[str] = [
        "Source material follows. Read carefully and produce either a profile "
        "(per the system prompt) or the literal token SKIP."
    ]

    # Notes (with content) carry the most signal — put them first.
    note_lines: list[str] = []
    for note in note_rows:
        title = (note.title or "Untitled").strip()
        body = (note.content_md or "").strip()
        if not body:
            continue
        # Cap each note to keep one outlier from dominating the budget.
        if len(body) > 2000:
            body = body[:2000] + " […]"
        note_lines.append(f"#### {title}\n{body}\n")
    parts += _section_or_empty(
        f"Notes (most recent {len(note_rows)})", note_lines
    )

    # Documents — title + description only (full body would blow the budget).
    doc_lines = [
        f"- {(d.title or 'Untitled').strip()}"
        + (f" — {d.description.strip()}" if d.description else "")
        for d in doc_rows
    ]
    parts += _section_or_empty("Documents (titles + descriptions)", doc_lines)

    parts += _section_or_empty(
        f"Goals (currently active or paused, {len(goal_rows)})",
        [f"- {g.title} ({g.status})" for g in goal_rows],
    )
    parts += _section_or_empty(
        f"Projects (currently active, {len(project_rows)})",
        [f"- {p.name} ({p.status})" for p in project_rows],
    )
    parts += _section_or_empty(
        f"Habits (currently tracked, {len(habit_rows)})",
        [f"- {h.name}" for h in habit_rows],
    )
    parts += _section_or_empty(
        f"Recent completed todos (last {_BOOTSTRAP_TODO_LOOKBACK_DAYS} days, {len(todo_rows)})",
        [f"- {t.title}" for t in todo_rows],
    )

    prompt = "\n".join(parts)
    # Hard trim to the budget. We'd rather drop trailing low-signal sections
    # than blow the provider's context window.
    if len(prompt) > _BOOTSTRAP_PROMPT_CHAR_BUDGET:
        prompt = prompt[:_BOOTSTRAP_PROMPT_CHAR_BUDGET] + "\n\n[…source material trimmed for length…]"

    return prompt, counts


async def run_bootstrap_pass(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    display_name: str,
) -> BootstrapResponse:
    """Read this user's existing data and silently apply an initial profile.

    Per the silent-learning shift (post-Phase-3), this no longer queues a
    pending proposal for user review — it writes the drafted content
    directly to member_ai_memory.memory_text and records an audit row in
    user_profile_updates (status='accepted' on insert). The end user
    never has to click anything; the profile just exists.

    Returns BootstrapResponse with the (auto-accepted) audit record or a
    skip reason. Idempotent — re-running produces a fresh draft that
    overwrites the previous one.
    """
    memory = await get_or_create_memory(db, user_id)

    source_text, counts = await _gather_bootstrap_sources(db, user_id, household_id)
    logger.info("Bootstrap source counts for user %s: %s", user_id, counts)

    if all(v == 0 for v in counts.values()):
        # No data at all — nothing to bootstrap from.
        memory.last_bootstrapped_at = datetime.now(tz=timezone.utc)
        await db.commit()
        return BootstrapResponse(
            update=None,
            bootstrap_skipped=True,
            reason=(
                "No notes, documents, or behavioural data found for your "
                "account yet. Start journaling or using the app and try "
                "again, or edit your profile directly."
            ),
        )

    current = (memory.memory_text or "").strip()
    system_prompt = _PROPOSER_SYSTEM_PROMPT
    if current:
        # Give the model the current profile so it can revise rather than
        # produce something contradictory.
        system_prompt = (
            _PROPOSER_SYSTEM_PROMPT
            + "\n\n## Current profile (revise rather than replace where possible)\n\n"
            + current
        )

    user_msg = (
        f"User display name: {display_name}\n\n"
        + source_text
    )

    text, input_tokens, output_tokens, model = await provider.complete(
        messages=[{"role": "user", "content": user_msg}],
        system=system_prompt,
        max_tokens=2048,
    )

    # Record usage (non-critical).
    if input_tokens > 0 or output_tokens > 0:
        try:
            await record_usage(
                db,
                user_id=user_id,
                conversation_id=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model,
                turn_kind="profile_bootstrap",
            )
        except Exception:
            logger.exception("Usage recording failed for profile bootstrap — ignoring")

    proposed = text.strip()

    # Mark that bootstrap has run for this user regardless of outcome —
    # the UI uses last_bootstrapped_at to show a different empty-state hint.
    memory.last_bootstrapped_at = datetime.now(tz=timezone.utc)

    if not proposed or proposed.strip().upper() == "SKIP":
        await db.commit()
        return BootstrapResponse(
            update=None,
            bootstrap_skipped=True,
            reason=(
                "The proposer found nothing profile-worthy in your existing "
                "data yet. Try again after journaling more, or edit your "
                "profile directly."
            ),
        )

    # Hard cap before persisting.
    proposed = proposed[:PROFILE_HARD_CAP_CHARS]

    summary = (
        "Initial profile draft from existing notes, documents, and behavioural data"
        if not current
        else "Proposed revision to your profile based on recent activity"
    )
    # Silent-learning shift: apply directly. The user_profile_updates row
    # is kept as an audit log (status='accepted' on insert), not a queue.
    # Phase 4: the write goes through _apply_profile_update so the previous
    # content (if any) is snapshotted into user_profile_versions.
    now = await _apply_profile_update(db, memory, proposed, source="bootstrap")
    update = UserProfileUpdate(
        user_id=user_id,
        proposed_content_md=proposed,
        diff_summary=summary,
        source="bootstrap",
        status="accepted",
        resolved_at=now,
    )
    db.add(update)
    await db.commit()
    await db.refresh(update)

    return BootstrapResponse(
        update=ProfileUpdateResponse.model_validate(update),
        bootstrap_skipped=False,
    )


# ── Phase 1.5: notes-driven incremental proposer ──────────────────────────────

async def _count_user_notes(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    """Total non-archived notes this user has authored (any collection)."""
    from life_dashboard.domains.notes.models import Note
    result = await db.execute(
        select(func.count()).select_from(Note).where(
            Note.household_id == household_id,
            Note.created_by_user_id == user_id,
            Note.archived_at.is_(None),
        )
    )
    return int(result.scalar_one() or 0)


async def _gather_incremental_notes_context(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> str:
    """Lightweight source bundle for the incremental proposer.

    Smaller than the bootstrap bundle because we already have a current
    profile to revise — the proposer's job is to spot *new* patterns, not
    to redraw the whole profile from scratch.
    """
    from life_dashboard.domains.notes.models import Note

    note_rows = (
        await db.execute(
            select(Note.title, Note.content_md, Note.updated_at)
            .where(
                Note.household_id == household_id,
                Note.created_by_user_id == user_id,
                Note.archived_at.is_(None),
            )
            .order_by(Note.updated_at.desc())
            .limit(_INCREMENTAL_NOTE_LIMIT)
        )
    ).all()

    lines = [
        f"Recent notes (last {len(note_rows)}, most recent first):"
    ]
    for n in note_rows:
        body = (n.content_md or "").strip()
        if not body:
            continue
        title = (n.title or "Untitled").strip()
        if len(body) > 1500:
            body = body[:1500] + " […]"
        lines.append(f"\n#### {title}\n{body}")
    return "\n".join(lines)


async def maybe_propose_from_notes(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
) -> None:
    """Fire-and-forget hook called from notes service after create/update.

    If enough new notes have accumulated since the last proposer run, this
    spawns a background task that drafts a proposed profile update and
    queues it for the user to accept or reject. Otherwise it returns
    immediately. Never raises — failures are logged and swallowed (this
    runs after every note save and must never block or break the write).

    Why the counter approach: a single user can never trigger more than
    one proposer call per N new notes, even if many notes are saved in
    rapid succession.
    """
    try:
        memory = await get_or_create_memory(db, user_id)

        # Skip if bootstrap hasn't run yet — we don't want to silently
        # populate a profile from scratch via the incremental path. The
        # user must opt in once via the explicit Build my profile button.
        if memory.last_bootstrapped_at is None:
            return

        current_count = await _count_user_notes(db, household_id, user_id)
        delta = current_count - (memory.notes_at_last_proposal or 0)
        if delta < _NOTES_PROPOSAL_THRESHOLD:
            return

        # Advance the counter eagerly so concurrent saves don't all spawn
        # background tasks. The actual proposer runs in a detached task so
        # the note-write commit is not delayed by an AI call.
        memory.notes_at_last_proposal = current_count
        await db.commit()

        import asyncio
        asyncio.create_task(_run_incremental_proposer(user_id, household_id))
    except Exception:
        logger.exception(
            "maybe_propose_from_notes failed for user %s — ignoring", user_id
        )


async def _run_incremental_proposer(
    user_id: uuid.UUID,
    household_id: uuid.UUID,
) -> None:
    """Background task — runs the proposer with its own DB session.

    Opens a fresh AsyncSession so this is decoupled from the request
    session that scheduled it (which may already be closed by the time
    this runs). Looks up the user's display_name inside the task so the
    hot path (note save) doesn't pay for an extra query on every write.
    """
    from life_dashboard.core.database import AsyncSessionLocal
    from life_dashboard.ai.models import AiSettings
    from life_dashboard.ai.service import get_provider
    from life_dashboard.auth.models import User

    try:
        async with AsyncSessionLocal() as db:
            # Resolve display_name — falls back to the email if the user
            # hasn't set one.
            user_row = (await db.execute(
                select(User.display_name, User.email).where(User.id == user_id)
            )).first()
            if user_row is None:
                logger.info(
                    "Incremental proposer skipped: user %s not found", user_id
                )
                return
            display_name = user_row.display_name or user_row.email
            # Resolve AI provider — silently skip if not configured for
            # this user (matches the chat memory refresh pattern).
            ai_settings = (await db.execute(
                select(AiSettings).where(AiSettings.user_id == user_id)
            )).scalar_one_or_none()
            if ai_settings is None:
                logger.info(
                    "Incremental proposer skipped: no AI settings for user %s", user_id
                )
                return
            provider = get_provider(ai_settings)
            if provider is None:
                logger.info(
                    "Incremental proposer skipped: no provider for user %s", user_id
                )
                return

            memory = await get_or_create_memory(db, user_id)
            current = (memory.memory_text or "").strip()

            source_text = await _gather_incremental_notes_context(
                db, household_id, user_id
            )
            if not source_text.strip() or len(source_text) < 100:
                logger.info(
                    "Incremental proposer skipped: no usable note content "
                    "for user %s", user_id,
                )
                return

            system_prompt = (
                _PROPOSER_SYSTEM_PROMPT
                + "\n\n## Current profile (revise only where the new "
                + "material clearly supports a change — otherwise output SKIP)\n\n"
                + (current or "(empty — but bootstrap has run; do not draft "
                              "a brand-new profile here. Output SKIP unless "
                              "the recent material is unambiguous.)")
            )
            user_msg = (
                f"User display name: {display_name}\n\n"
                f"This is an incremental update triggered by recent note "
                f"activity. Compare the recent notes below against the "
                f"current profile and propose a revision ONLY if there is a "
                f"clear, durable change worth recording. Bias toward SKIP.\n\n"
                + source_text
            )

            text, input_tokens, output_tokens, model = await provider.complete(
                messages=[{"role": "user", "content": user_msg}],
                system=system_prompt,
                max_tokens=2048,
            )

            if input_tokens > 0 or output_tokens > 0:
                try:
                    await record_usage(
                        db,
                        user_id=user_id,
                        conversation_id=None,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=model,
                        turn_kind="profile_incremental",
                    )
                except Exception:
                    logger.exception(
                        "Usage recording failed for incremental proposer — ignoring"
                    )

            proposed = text.strip()
            if not proposed or proposed.upper() == "SKIP":
                logger.info(
                    "Incremental proposer for user %s returned SKIP — no change",
                    user_id,
                )
                await db.commit()
                return

            proposed = proposed[:PROFILE_HARD_CAP_CHARS]
            # Silent-learning shift: apply directly. The audit row reflects
            # what was actually applied; pending/accept/reject is no longer
            # a user-facing flow. Phase 4: previous content snapshotted via
            # _apply_profile_update.
            now = await _apply_profile_update(
                db, memory, proposed, source="incremental"
            )
            update = UserProfileUpdate(
                user_id=user_id,
                proposed_content_md=proposed,
                diff_summary="Auto-applied update from recent notes activity",
                source="incremental",
                status="accepted",
                resolved_at=now,
            )
            db.add(update)
            await db.commit()
            logger.info(
                "Incremental proposer applied update %s for user %s",
                update.id, user_id,
            )

    except Exception:
        logger.exception(
            "Incremental proposer background task failed for user %s — ignoring",
            user_id,
        )


# ── Phase 4: scheduled refresh + decay proposer ───────────────────────────────

_SCHEDULED_REFRESH_PROMPT = """You are doing a weekly review of a user's profile. Two jobs:

1) INTEGRATE recent durable patterns. Look at the source material below
   (recent notes, recent chat themes, behavioural snapshot) and integrate
   anything that has shown up repeatedly and feels like a stable
   pattern, value, or focus. Do NOT add one-off events or transient moods.

2) DECAY stale content. Look at the CURRENT PROFILE carefully. Anything
   that:
     - Hasn't shown up in the source material for several weeks
     - Was about a specific past situation that's now resolved
     - Reads as a fixed-trait judgment rather than a current observation
     - Has been contradicted by recent activity
   should be removed or softened. Profile decay is just as important as
   adding new content — a profile that grows monotonically becomes
   inaccurate fast.

Output rules:
- Output ONLY the revised profile as markdown sectioned by H2 headers,
  nothing else. Same section headers as the current profile.
- If, after careful review, NOTHING in the current profile needs to
  change AND nothing in the source material warrants adding, output
  the literal token SKIP.
- Bias toward SKIP. A weekly refresh that returns SKIP means the
  profile is currently accurate — that's a good outcome, not a failure.
- Stay under 4000 characters total."""


async def _gather_scheduled_refresh_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
) -> str:
    """Source bundle for the scheduled weekly refresh.

    Wider than the incremental proposer (looks at 4 weeks of activity)
    and includes recent chat themes alongside notes, so the AI has
    enough signal to decide what's still durable.
    """
    from life_dashboard.domains.notes.models import Note
    from life_dashboard.ai.models import AiConversation, AiMessage, AiMessageRole

    four_weeks_ago = datetime.now(tz=timezone.utc) - timedelta(days=28)

    note_rows = (
        await db.execute(
            select(Note.title, Note.content_md, Note.updated_at)
            .where(
                Note.household_id == household_id,
                Note.created_by_user_id == user_id,
                Note.archived_at.is_(None),
                Note.updated_at >= four_weeks_ago,
            )
            .order_by(Note.updated_at.desc())
            .limit(40)
        )
    ).all()

    # Recent chat — pull the user-side messages only (skip assistant turns
    # to keep the bundle dense). Cap aggressively.
    chat_rows = (
        await db.execute(
            select(AiMessage.content, AiMessage.created_at)
            .join(AiConversation, AiMessage.conversation_id == AiConversation.id)
            .where(
                AiConversation.user_id == user_id,
                AiMessage.role == AiMessageRole.user,
                AiMessage.created_at >= four_weeks_ago,
            )
            .order_by(AiMessage.created_at.desc())
            .limit(60)
        )
    ).all()

    lines: list[str] = []

    if note_rows:
        lines.append(f"Notes written in the last 4 weeks ({len(note_rows)}):")
        for n in note_rows:
            body = (n.content_md or "").strip()
            if not body:
                continue
            title = (n.title or "Untitled").strip()
            if len(body) > 800:
                body = body[:800] + " […]"
            lines.append(f"\n#### {title}\n{body}")
        lines.append("")

    if chat_rows:
        lines.append(f"User messages from recent chat ({len(chat_rows)}):")
        for c in chat_rows:
            body = (c.content or "").strip()
            if not body:
                continue
            if len(body) > 400:
                body = body[:400] + " […]"
            lines.append(f"- {body}")
        lines.append("")

    return "\n".join(lines) if lines else ""


async def run_scheduled_profile_refresh(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    display_name: str,
) -> dict[str, Any]:
    """Weekly review of one user's profile — integrate + decay.

    Returns a small status dict for logging. Never raises — caller can
    iterate over many users without one failure killing the batch.

    Skips when:
      - the user has no profile yet (bootstrap hasn't run)
      - the source bundle is empty (no recent activity at all)
      - the proposer returns SKIP

    Otherwise applies the new profile through _apply_profile_update —
    previous content is snapshotted into user_profile_versions, audit
    row is recorded.
    """
    status: dict[str, Any] = {"user_id": str(user_id), "outcome": "unknown"}

    try:
        memory = await get_or_create_memory(db, user_id)
        current = (memory.memory_text or "").strip()
        if not current:
            status["outcome"] = "skipped_no_profile"
            return status

        source_text = await _gather_scheduled_refresh_sources(db, user_id, household_id)
        if not source_text.strip():
            status["outcome"] = "skipped_no_activity"
            return status

        system_prompt = (
            _SCHEDULED_REFRESH_PROMPT
            + "\n\n## Current profile\n\n"
            + current
        )
        user_msg = (
            f"User display name: {display_name}\n\n"
            f"Source material from the last 4 weeks:\n\n"
            + source_text
        )

        text, input_tok, output_tok, model = await provider.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=system_prompt,
            max_tokens=2048,
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
                    turn_kind="profile_scheduled",
                )
            except Exception:
                logger.exception(
                    "Usage recording failed for scheduled refresh — ignoring"
                )

        proposed = text.strip()
        if not proposed or proposed.upper() == "SKIP":
            status["outcome"] = "skip"
            return status

        proposed = proposed[:PROFILE_HARD_CAP_CHARS]
        now = await _apply_profile_update(
            db, memory, proposed, source="scheduled"
        )
        audit = UserProfileUpdate(
            user_id=user_id,
            proposed_content_md=proposed,
            diff_summary="Weekly scheduled refresh (integrate + decay)",
            source="scheduled",
            status="accepted",
            resolved_at=now,
        )
        db.add(audit)
        await db.commit()
        status["outcome"] = "applied"
        logger.info(
            "Scheduled profile refresh applied for user %s", user_id
        )
        return status

    except Exception:
        logger.exception(
            "Scheduled refresh failed for user %s — skipping", user_id
        )
        status["outcome"] = "error"
        return status


async def run_scheduled_profile_refresh_all() -> dict[str, int]:
    """Called by the APScheduler job. Iterates every user with a
    non-empty profile and runs the scheduled refresh for them.

    Returns aggregate counts for the boot/scheduler log.
    """
    from life_dashboard.core.database import AsyncSessionLocal
    from life_dashboard.ai.models import AiSettings
    from life_dashboard.ai.service import get_provider
    from life_dashboard.auth.models import User, HouseholdMembership

    counts = {"users": 0, "applied": 0, "skip": 0, "skipped_no_activity": 0, "error": 0}

    async with AsyncSessionLocal() as db:
        # Eligible users: have a memory_text non-empty AND AI settings exist.
        candidates = (await db.execute(
            select(MemberAiMemory.user_id)
            .where(MemberAiMemory.memory_text != "")
        )).scalars().all()

        for uid in candidates:
            counts["users"] += 1
            try:
                # Resolve provider + household for this user.
                ai_settings = (await db.execute(
                    select(AiSettings).where(AiSettings.user_id == uid)
                )).scalar_one_or_none()
                if ai_settings is None:
                    continue
                provider = get_provider(ai_settings)
                if provider is None:
                    continue

                user = (await db.execute(
                    select(User.display_name, User.email).where(User.id == uid)
                )).first()
                if user is None:
                    continue
                display_name = user.display_name or user.email

                hh = (await db.execute(
                    select(HouseholdMembership.household_id)
                    .where(HouseholdMembership.user_id == uid)
                    .order_by(HouseholdMembership.joined_at.asc())
                    .limit(1)
                )).scalar_one_or_none()
                if hh is None:
                    continue

                status = await run_scheduled_profile_refresh(
                    db, provider, uid, hh, display_name
                )
                outcome = status.get("outcome", "error")
                if outcome in counts:
                    counts[outcome] += 1
            except Exception:
                logger.exception(
                    "Scheduled refresh iteration failed for user %s", uid
                )
                counts["error"] += 1

    return counts


# ── Shared context loader (used by coach + chat) ──────────────────────────────

async def load_profile_context(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Return a system-prompt fragment that injects the user's profile, or "".

    Both coach_service and the chat code path call this so the two surfaces
    share an understanding of the user. Empty string when no profile exists
    yet (caller can omit the section entirely).
    """
    memory = await get_or_create_memory(db, user_id)
    text = (memory.memory_text or "").strip()
    if not text:
        return ""
    return (
        "## What you know about this person\n\n"
        + "Read this profile. It reflects who they are and what is currently true "
        + "for them. Do NOT name-drop the profile — never say 'I see from your "
        + "profile that…'. Just let it inform your response.\n\n"
        + text
    )
