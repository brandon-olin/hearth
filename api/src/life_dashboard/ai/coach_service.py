"""AI coach service layer.

Generates morning and evening digest messages for individual users based on
their household data (todos, habits, goals, projects). Digests are cached in
the ai_coach_digests table — one row per (user, date, kind).

Called by:
  - The APScheduler background jobs in main.py (automatic, all users)
  - The /ai/coach/digest/generate endpoint (manual on-demand)
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai.models import AiCoachDigest, CoachDigestKind
from life_dashboard.ai.provider import AIProvider
from life_dashboard.ai.service import record_usage

logger = logging.getLogger(__name__)

# ── Tone definitions ──────────────────────────────────────────────────────────

COACH_TONES: dict[str, dict[str, str]] = {
    "supportive": {
        "label": "Supportive",
        "description": "Warm, believes in you unconditionally (Ted Lasso energy)",
        "morning_voice": (
            "You are an upbeat, warm personal coach — like Ted Lasso but for daily productivity. "
            "You genuinely believe in this person. Use encouraging language, celebrate wins no matter "
            "how small, and frame challenges as opportunities. Keep it concise but heartfelt."
        ),
        "evening_voice": (
            "You are a warm, caring coach wrapping up the day with this person. "
            "Help them feel good about what they accomplished, acknowledge what didn't happen without "
            "judgment, and leave them in a calm, positive headspace for the evening."
        ),
    },
    "stoic": {
        "label": "Direct (Stoic)",
        "description": "Calm, no-frills, focused on what's in your control",
        "morning_voice": (
            "You are a stoic coach — calm, direct, and focused on what is actionable. "
            "No cheerleading, no fluff. State facts clearly: what was done, what needs doing. "
            "Remind the user to focus only on what is in their control. Keep it brief and matter-of-fact."
        ),
        "evening_voice": (
            "You are a stoic coach closing out the day. Acknowledge what was accomplished without "
            "excessive praise. Note what remains undone without self-criticism — it simply carries to "
            "tomorrow. Leave the user with a clear, quiet mind. Be brief."
        ),
    },
    "drill_sergeant": {
        "label": "Drill Sergeant",
        "description": "Hard-nosed, no excuses, pushes you harder",
        "morning_voice": (
            "You are a no-nonsense drill sergeant giving this soldier their morning briefing. "
            "Be direct, demanding, and motivating. Call out incomplete items from yesterday. "
            "Make today's mission crystal clear. You expect excellence — say so. "
            "Keep it punchy, not cruel. You want them to succeed."
        ),
        "evening_voice": (
            "You are a drill sergeant doing end-of-day review. Acknowledge what got done — briefly. "
            "Be clear about what didn't happen and why it matters. Then stand them down: "
            "give them permission to rest so they can perform at full capacity tomorrow."
        ),
    },
    "gentle_mentor": {
        "label": "Gentle Mentor",
        "description": "Thoughtful, reflective, like a wise friend who also tracks your todos",
        "morning_voice": (
            "You are a thoughtful, wise mentor starting the morning with this person. "
            "Reflect gently on yesterday's progress. Help them see the bigger picture of what they're "
            "working toward. Ask a quiet guiding question if appropriate. Keep it warm, unhurried, "
            "and meaningful — not a task list."
        ),
        "evening_voice": (
            "You are a gentle mentor helping this person wind down. Reflect on the day with them — "
            "what went well, what was hard, what can be let go. Help them transition from doing-mode "
            "to being-mode. No pressure. Just thoughtful companionship at the end of a day."
        ),
    },
}

DEFAULT_TONE = "supportive"


# ── Context data fetching ─────────────────────────────────────────────────────

async def _fetch_context(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    for_date: date,
    pinned_project_ids: list[str],
    pinned_goal_ids: list[str],
    pinned_habit_ids: list[str],
) -> dict[str, Any]:
    """Fetch relevant data for building the digest prompt.

    Returns a dict with keys: todos_yesterday, todos_today, habits_today,
    habits_yesterday, goals, projects.  Each value is a list of dicts
    with display-friendly fields.
    """
    from sqlalchemy import func
    from life_dashboard.domains.todos.models import Todo
    from life_dashboard.domains.habits.models import Habit, HabitOccurrence
    from life_dashboard.domains.goals.models import Goal
    from life_dashboard.domains.projects.models import Project

    yesterday = date.fromordinal(for_date.toordinal() - 1)
    ctx: dict[str, Any] = {}

    # ── Todos completed yesterday ─────────────────────────────────────────────
    rows = (await db.execute(
        select(Todo.title)
        .where(
            Todo.household_id == household_id,
            Todo.status == "completed",
            func.date(Todo.completed_at) == yesterday,
        )
        .order_by(Todo.completed_at.desc())
        .limit(20)
    )).all()
    ctx["todos_completed_yesterday"] = [{"title": r.title} for r in rows]

    # ── Todos due today or overdue (incomplete) ───────────────────────────────
    rows = (await db.execute(
        select(Todo.title, Todo.due_date, Todo.priority)
        .where(
            Todo.household_id == household_id,
            Todo.status != "completed",
            Todo.due_date.isnot(None),
            Todo.due_date <= for_date,
        )
        .order_by(Todo.priority.desc().nulls_last(), Todo.due_date.asc())
        .limit(20)
    )).all()
    ctx["todos_due_today"] = [
        {
            "title": r.title,
            "overdue": r.due_date < for_date if r.due_date else False,
        }
        for r in rows
    ]

    # ── Todos completed today (for evening digest) ────────────────────────────
    rows = (await db.execute(
        select(Todo.title)
        .where(
            Todo.household_id == household_id,
            Todo.status == "completed",
            func.date(Todo.completed_at) == for_date,
        )
        .order_by(Todo.completed_at.desc())
        .limit(20)
    )).all()
    ctx["todos_completed_today"] = [{"title": r.title} for r in rows]

    # ── Habits ────────────────────────────────────────────────────────────────
    habit_q = select(Habit.id, Habit.name).where(
        Habit.household_id == household_id,
        Habit.status != "archived",
    )
    if pinned_habit_ids:
        habit_q = habit_q.where(Habit.id.in_([uuid.UUID(h) for h in pinned_habit_ids]))
    habits = (await db.execute(habit_q)).all()
    habit_ids = [h.id for h in habits]

    # Occurrences for yesterday and today — completed when status == "completed"
    if habit_ids:
        occurrences = (await db.execute(
            select(HabitOccurrence.habit_id, HabitOccurrence.scheduled_date, HabitOccurrence.status)
            .where(
                HabitOccurrence.habit_id.in_(habit_ids),
                HabitOccurrence.scheduled_date.in_([yesterday, for_date]),
            )
        )).all()
        occ_map: dict[tuple, str] = {
            (str(o.habit_id), o.scheduled_date): o.status for o in occurrences
        }
    else:
        occ_map = {}

    ctx["habits_yesterday"] = [
        {
            "name": h.name,
            "completed": occ_map.get((str(h.id), yesterday)) == "completed",
        }
        for h in habits
    ]
    ctx["habits_today"] = [
        {
            "name": h.name,
            "completed": occ_map.get((str(h.id), for_date)) == "completed",
        }
        for h in habits
    ]

    # ── Goals ─────────────────────────────────────────────────────────────────
    goal_q = (
        select(Goal.id, Goal.title, Goal.current_value, Goal.target_value, Goal.unit, Goal.status)
        .where(
            Goal.household_id == household_id,
            Goal.status.in_(["active", "paused"]),
        )
        .order_by(Goal.updated_at.desc())
        .limit(10)
    )
    if pinned_goal_ids:
        goal_q = goal_q.where(Goal.id.in_([uuid.UUID(g) for g in pinned_goal_ids]))
    goals = (await db.execute(goal_q)).all()
    ctx["goals"] = []
    for g in goals:
        pct: float | None = None
        if g.target_value and g.current_value is not None and float(g.target_value) > 0:
            pct = round(float(g.current_value) / float(g.target_value) * 100, 1)
        ctx["goals"].append({
            "title": g.title,
            "progress_pct": pct,
            "status": g.status,
        })

    # ── Projects ──────────────────────────────────────────────────────────────
    proj_q = (
        select(Project.id, Project.name, Project.status)
        .where(
            Project.household_id == household_id,
            Project.status.notin_(["complete", "archived"]),
            Project.is_system == False,
        )
        .order_by(Project.updated_at.desc())
        .limit(10)
    )
    if pinned_project_ids:
        proj_q = proj_q.where(Project.id.in_([uuid.UUID(p) for p in pinned_project_ids]))
    projects = (await db.execute(proj_q)).all()
    ctx["projects"] = [
        {"name": p.name, "status": p.status, "progress_pct": None}
        for p in projects
    ]

    return ctx


# ── Prompt building ───────────────────────────────────────────────────────────

def _fmt_todo_list(todos: list[dict], overdue_label: bool = False) -> str:
    if not todos:
        return "  (none)"
    lines = []
    for t in todos:
        prefix = "• "
        if overdue_label and t.get("overdue"):
            prefix = "• [OVERDUE] "
        lines.append(f"{prefix}{t['title']}")
    return "\n".join(lines)


def _fmt_habit_list(habits: list[dict]) -> str:
    if not habits:
        return "  (none tracked)"
    lines = []
    for h in habits:
        mark = "✓" if h["completed"] else "✗"
        lines.append(f"  {mark} {h['name']}")
    return "\n".join(lines)


def _fmt_goals(goals: list[dict]) -> str:
    if not goals:
        return "  (no active goals)"
    lines = []
    for g in goals:
        pct = f"{g['progress_pct']}%" if g.get("progress_pct") is not None else "?"
        lines.append(f"  • {g['title']} ({pct})")
    return "\n".join(lines)


def _fmt_projects(projects: list[dict]) -> str:
    if not projects:
        return "  (no active projects)"
    lines = []
    for p in projects:
        lines.append(f"  • {p['name']} — {p['status']}")
    return "\n".join(lines)


def _build_morning_user_message(
    display_name: str,
    for_date: date,
    ctx: dict[str, Any],
    include_goals: bool,
    include_projects: bool,
) -> str:
    yesterday = date.fromordinal(for_date.toordinal() - 1)
    parts = [
        f"Good morning, {display_name}! Today is {for_date.strftime('%A, %B %d')}.",
        "",
        f"## Yesterday ({yesterday.strftime('%A, %B %d')})",
        "",
        "**Completed tasks:**",
        _fmt_todo_list(ctx["todos_completed_yesterday"]),
        "",
        "**Habits:**",
        _fmt_habit_list(ctx["habits_yesterday"]),
    ]

    if include_goals:
        parts += ["", "**Goal progress:**", _fmt_goals(ctx["goals"])]

    if include_projects:
        parts += ["", "**Active projects:**", _fmt_projects(ctx["projects"])]

    parts += [
        "",
        f"## Today ({for_date.strftime('%A, %B %d')})",
        "",
        "**Tasks due today (including overdue):**",
        _fmt_todo_list(ctx["todos_due_today"], overdue_label=True),
        "",
        "Please give me a morning briefing covering:",
        "1. A brief reflection on yesterday (what I accomplished, how habits went)",
        "2. What's on my plate today — highlight anything overdue",
        "3. A short motivational close (keep it genuine, not generic)",
        "",
        "Keep your response to 3–5 short paragraphs. No bullet-point dumps.",
    ]
    return "\n".join(parts)


def _build_evening_user_message(
    display_name: str,
    for_date: date,
    ctx: dict[str, Any],
    include_goals: bool,
    include_projects: bool,
) -> str:
    parts = [
        f"Good evening, {display_name}. Today is {for_date.strftime('%A, %B %d')}.",
        "",
        f"## Today's accomplishments",
        "",
        "**Completed tasks today:**",
        _fmt_todo_list(ctx["todos_completed_today"]),
        "",
        "**Habits today:**",
        _fmt_habit_list(ctx["habits_today"]),
        "",
        "**Still on the list (not done today):**",
        _fmt_todo_list(ctx["todos_due_today"]),
    ]

    if include_goals:
        parts += ["", "**Goal progress:**", _fmt_goals(ctx["goals"])]

    if include_projects:
        parts += ["", "**Active projects:**", _fmt_projects(ctx["projects"])]

    parts += [
        "",
        "Please give me an evening wind-down summary covering:",
        "1. A brief acknowledgment of what I got done today",
        "2. A gentle note on what's still open — without stress or guilt",
        "3. A calm, grounding close to help me shift into evening mode",
        "",
        "Keep it to 3–4 short paragraphs. Warm and unhurried.",
    ]
    return "\n".join(parts)


# ── Digest generation ─────────────────────────────────────────────────────────

async def generate_digest(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    display_name: str,
    for_date: date,
    kind: str,  # "morning" | "evening"
    tone: str,
    pinned_project_ids: list[str],
    pinned_goal_ids: list[str],
    pinned_habit_ids: list[str],
) -> AiCoachDigest:
    """Generate (or regenerate) a coach digest and persist it.

    If a digest for the same (user, date, kind) already exists it is deleted
    and replaced — this supports the manual "Regenerate" action in the widget.
    """
    tone_def = COACH_TONES.get(tone, COACH_TONES[DEFAULT_TONE])
    include_goals = bool(pinned_goal_ids) or not (pinned_project_ids or pinned_habit_ids)
    include_projects = bool(pinned_project_ids) or not (pinned_goal_ids or pinned_habit_ids)

    ctx = await _fetch_context(
        db, household_id, user_id, for_date,
        pinned_project_ids, pinned_goal_ids, pinned_habit_ids,
    )

    if kind == CoachDigestKind.morning or kind == "morning":
        system = tone_def["morning_voice"]
        user_msg = _build_morning_user_message(
            display_name, for_date, ctx, include_goals, include_projects
        )
    else:
        system = tone_def["evening_voice"]
        user_msg = _build_evening_user_message(
            display_name, for_date, ctx, include_goals, include_projects
        )

    content, input_tokens, output_tokens, model = await provider.complete(
        messages=[{"role": "user", "content": user_msg}],
        system=system,
        max_tokens=1024,
    )

    # Record token usage (non-critical).
    if input_tokens > 0 or output_tokens > 0:
        try:
            await record_usage(
                db,
                user_id=user_id,
                conversation_id=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model,
                turn_kind="coach_digest",
            )
        except Exception:
            logger.exception("Usage recording failed for coach digest — ignoring")

    # Delete any existing digest for this slot (idempotent upsert).
    await db.execute(
        delete(AiCoachDigest).where(
            AiCoachDigest.user_id == user_id,
            AiCoachDigest.date == for_date,
            AiCoachDigest.kind == kind,
        )
    )

    digest = AiCoachDigest(
        user_id=user_id,
        date=for_date,
        kind=kind,
        content=content.strip(),
        tone=tone,
    )
    db.add(digest)
    await db.commit()
    await db.refresh(digest)

    logger.info(
        "Generated %s coach digest for user %s on %s (tone=%s)",
        kind, user_id, for_date, tone,
    )
    return digest


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def get_digest(
    db: AsyncSession,
    user_id: uuid.UUID,
    for_date: date,
    kind: str,
) -> AiCoachDigest | None:
    """Return the stored digest for a given day/kind, or None."""
    result = await db.execute(
        select(AiCoachDigest).where(
            AiCoachDigest.user_id == user_id,
            AiCoachDigest.date == for_date,
            AiCoachDigest.kind == kind,
        )
    )
    return result.scalar_one_or_none()


# ── Scheduler helper ──────────────────────────────────────────────────────────

async def run_scheduled_digests(kind: str) -> None:
    """Called by APScheduler. Generates digests for all eligible users.

    A user is eligible if:
    - They have an AI provider configured (AiSettings with a key, or the system
      key is available).
    - Their dashboard preferences include at least one ai_coach widget.

    The first ai_coach widget config found for the user is used.  Users with
    multiple coach widgets get one shared digest (same content, different tone
    is not yet supported in scheduled mode — use on-demand regeneration).
    """
    from life_dashboard.core.database import AsyncSessionLocal
    from life_dashboard.auth.models import User
    from life_dashboard.ai.models import AiSettings
    from life_dashboard.ai.service import get_provider
    from life_dashboard.core.settings import settings as app_settings

    today = date.today()
    logger.info("Running scheduled %s coach digests for %s", kind, today)

    async with AsyncSessionLocal() as db:
        # Load all users who have preferences set (may have a coach widget).
        users = (await db.execute(
            select(User).where(User.is_active == True, User.preferences.isnot(None))
        )).scalars().all()

        generated = 0
        for user in users:
            try:
                prefs = user.preferences or {}
                dashboard = prefs.get("dashboard", {})
                widgets = dashboard.get("widgets", [])
                coach_widgets = [w for w in widgets if w.get("type") == "ai_coach"]
                if not coach_widgets:
                    continue

                cfg = coach_widgets[0].get("config", {})
                tone = cfg.get("tone", DEFAULT_TONE)
                pinned_project_ids = cfg.get("pinned_project_ids", [])
                pinned_goal_ids = cfg.get("pinned_goal_ids", [])
                pinned_habit_ids = cfg.get("pinned_habit_ids", [])

                # Resolve AI provider for this user.
                ai_settings_result = await db.execute(
                    select(AiSettings).where(AiSettings.user_id == user.id)
                )
                ai_settings = ai_settings_result.scalar_one_or_none()
                if ai_settings is None:
                    continue

                provider = get_provider(ai_settings)
                if provider is None:
                    continue

                # Skip if a digest already exists for this slot.
                existing = await get_digest(db, user.id, today, kind)
                if existing is not None:
                    continue

                await generate_digest(
                    db=db,
                    provider=provider,
                    user_id=user.id,
                    household_id=user.memberships[0].household_id if user.memberships else None,
                    display_name=user.display_name or user.email,
                    for_date=today,
                    kind=kind,
                    tone=tone,
                    pinned_project_ids=pinned_project_ids,
                    pinned_goal_ids=pinned_goal_ids,
                    pinned_habit_ids=pinned_habit_ids,
                )
                generated += 1

            except Exception:
                logger.exception(
                    "Scheduled coach digest failed for user %s — skipping", user.id
                )

    logger.info(
        "Scheduled %s coach digests done: %d generated out of %d eligible users",
        kind, generated, len(users),
    )
