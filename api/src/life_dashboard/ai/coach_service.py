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

async def _get_descendant_project_ids(
    db: AsyncSession,
    household_id: uuid.UUID,
    root_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Return root_ids plus all descendant project IDs (any depth).

    Uses an iterative BFS over projects.parent_id so we correctly pick up
    todos that live 2–7 sub-projects deep without needing a recursive CTE.
    """
    from life_dashboard.domains.projects.models import Project

    if not root_ids:
        return []

    all_ids: set[uuid.UUID] = set(root_ids)
    frontier: list[uuid.UUID] = list(root_ids)

    while frontier:
        result = await db.execute(
            select(Project.id).where(
                Project.parent_id.in_(frontier),
                Project.household_id == household_id,
            )
        )
        children = [row[0] for row in result.all()]
        new_children = [c for c in children if c not in all_ids]
        all_ids.update(new_children)
        frontier = new_children

    return list(all_ids)


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

    # Resolve pinned projects → full descendant tree (handles sub-projects at any depth)
    if pinned_project_ids:
        all_pinned_ids = await _get_descendant_project_ids(
            db, household_id, [uuid.UUID(p) for p in pinned_project_ids]
        )
    else:
        all_pinned_ids = []

    # ── Todos completed yesterday ─────────────────────────────────────────────
    # Per-user scoping (privacy-001): the coach digest must reflect THIS
    # user's behavior only, not the whole household. Otherwise a partner's
    # completed chores show up in your "Completed yesterday" list.
    rows = (await db.execute(
        select(Todo.title)
        .where(
            Todo.household_id == household_id,
            Todo.assigned_to_user_id == user_id,
            Todo.status == "done",
            func.date(Todo.completed_at) == yesterday,
        )
        .order_by(Todo.completed_at.desc())
        .limit(30)
    )).all()
    ctx["todos_completed_yesterday"] = [{"title": r.title} for r in rows]

    # Pinned-project todos completed yesterday (includes all sub-project depths)
    if all_pinned_ids:
        rows = (await db.execute(
            select(Todo.title)
            .where(
                Todo.household_id == household_id,
                Todo.assigned_to_user_id == user_id,
                Todo.status == "done",
                func.date(Todo.completed_at) == yesterday,
                Todo.project_id.in_(all_pinned_ids),
            )
            .order_by(Todo.completed_at.desc())
            .limit(30)
        )).all()
        ctx["todos_completed_yesterday_pinned"] = [{"title": r.title} for r in rows]
    else:
        ctx["todos_completed_yesterday_pinned"] = []

    # ── Todos due today or overdue (incomplete) ───────────────────────────────
    rows = (await db.execute(
        select(Todo.title, Todo.due_date, Todo.priority)
        .where(
            Todo.household_id == household_id,
            Todo.assigned_to_user_id == user_id,
            Todo.status != "done",
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
            Todo.assigned_to_user_id == user_id,
            Todo.status == "done",
            func.date(Todo.completed_at) == for_date,
        )
        .order_by(Todo.completed_at.desc())
        .limit(30)
    )).all()
    ctx["todos_completed_today"] = [{"title": r.title} for r in rows]

    # Pinned-project todos completed today (includes all sub-project depths)
    if all_pinned_ids:
        rows = (await db.execute(
            select(Todo.title)
            .where(
                Todo.household_id == household_id,
                Todo.assigned_to_user_id == user_id,
                Todo.status == "done",
                func.date(Todo.completed_at) == for_date,
                Todo.project_id.in_(all_pinned_ids),
            )
            .order_by(Todo.completed_at.desc())
            .limit(30)
        )).all()
        ctx["todos_completed_today_pinned"] = [{"title": r.title} for r in rows]
    else:
        ctx["todos_completed_today_pinned"] = []

    # ── Habits ────────────────────────────────────────────────────────────────
    # privacy-001: scope to this user's habits only. Old habits with
    # NULL created_by_user_id will be excluded — that's correct (we
    # can't attribute them to any user).
    habit_q = select(Habit.id, Habit.name).where(
        Habit.household_id == household_id,
        Habit.created_by_user_id == user_id,
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
    # privacy-001: scope to this user's goals only. Goals don't have an
    # explicit "shared participants" concept yet; a partner's goal
    # appearing in your digest would be a leak.
    goal_q = (
        select(Goal.id, Goal.title, Goal.current_value, Goal.target_value, Goal.unit, Goal.status)
        .where(
            Goal.household_id == household_id,
            Goal.created_by_user_id == user_id,
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
    # privacy-001: scope to this user's projects only. The descendant
    # tree walk (_get_descendant_project_ids) above still traverses
    # household-wide structure — that's deliberate, because a user might
    # pin a parent project that has subprojects created by a partner
    # and we want to count THAT user's todos under those subprojects.
    # The Todo queries above already filter by assigned_to_user_id.
    proj_q = (
        select(Project.id, Project.name, Project.status)
        .where(
            Project.household_id == household_id,
            Project.created_by_user_id == user_id,
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
    # Keep a name lookup for pinned root projects (used to label focused sections)
    ctx["pinned_project_names"] = [p.name for p in projects] if pinned_project_ids else []

    return ctx


# ── Historical context ────────────────────────────────────────────────────────

async def _fetch_history(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    for_date: date,
    pinned_project_ids: list[str],
    pinned_habit_ids: list[str],
    all_pinned_ids: list[uuid.UUID],  # pre-resolved descendant project IDs
) -> dict[str, Any]:
    """Return rolling historical data for trajectory-aware coaching.

    Fetches the past 6 weeks of todo completion counts (by week) and habit
    completion rates, scoped to pinned projects/habits when set.

    privacy-001: all queries here are filtered to this user's data only.
    The 6-week completion history is the user's, not the household's.
    """
    from sqlalchemy import func, case
    from life_dashboard.domains.todos.models import Todo
    from life_dashboard.domains.habits.models import Habit, HabitOccurrence

    history: dict[str, Any] = {}

    # ── Weekly todo completion counts (past 6 weeks) ──────────────────────────
    six_weeks_ago = date.fromordinal(for_date.toordinal() - 42)

    todo_q = (
        select(
            func.date_trunc("week", Todo.completed_at).label("week_start"),
            func.count().label("count"),
        )
        .where(
            Todo.household_id == household_id,
            Todo.assigned_to_user_id == user_id,
            Todo.status == "done",
            func.date(Todo.completed_at) >= six_weeks_ago,
            func.date(Todo.completed_at) < for_date,  # exclude today (in progress)
        )
        .group_by(func.date_trunc("week", Todo.completed_at))
        .order_by(func.date_trunc("week", Todo.completed_at))
    )
    if all_pinned_ids:
        todo_q = todo_q.where(Todo.project_id.in_(all_pinned_ids))

    rows = (await db.execute(todo_q)).all()
    history["weekly_completions"] = [
        {"week_start": str(r.week_start.date()) if hasattr(r.week_start, "date") else str(r.week_start), "count": r.count}
        for r in rows
    ]

    # ── Habit completion rates (7d vs 30d) ────────────────────────────────────
    habit_q = select(Habit.id, Habit.name).where(
        Habit.household_id == household_id,
        Habit.created_by_user_id == user_id,
        Habit.status != "archived",
    )
    if pinned_habit_ids:
        habit_q = habit_q.where(Habit.id.in_([uuid.UUID(h) for h in pinned_habit_ids]))
    habits = (await db.execute(habit_q)).all()
    habit_ids = [h.id for h in habits]

    if habit_ids:
        thirty_days_ago = date.fromordinal(for_date.toordinal() - 30)
        seven_days_ago = date.fromordinal(for_date.toordinal() - 7)

        occ_rows = (await db.execute(
            select(
                HabitOccurrence.habit_id,
                HabitOccurrence.scheduled_date,
                HabitOccurrence.status,
            )
            .where(
                HabitOccurrence.habit_id.in_(habit_ids),
                HabitOccurrence.scheduled_date >= thirty_days_ago,
                HabitOccurrence.scheduled_date < for_date,
            )
        )).all()

        # Group occurrences by habit
        occ_by_habit: dict[uuid.UUID, list] = {h.id: [] for h in habits}
        for o in occ_rows:
            occ_by_habit[o.habit_id].append(o)

        habit_stats = []
        for h in habits:
            occs = occ_by_habit[h.id]
            last30 = occs
            last7 = [o for o in occs if o.scheduled_date >= seven_days_ago]
            rate_30 = (
                round(sum(1 for o in last30 if o.status == "completed") / len(last30) * 100)
                if last30 else None
            )
            rate_7 = (
                round(sum(1 for o in last7 if o.status == "completed") / len(last7) * 100)
                if last7 else None
            )
            habit_stats.append({"name": h.name, "rate_7d": rate_7, "rate_30d": rate_30})

        history["habit_trends"] = habit_stats
    else:
        history["habit_trends"] = []

    return history


# ── Narrative context (Phase 3 of AI coach redesign) ──────────────────────────

# How many recent journal entries to pass to the model verbatim. Capped to
# keep prompts predictable; the structured trend numbers carry the broader
# story.
_NARRATIVE_RECENT_ENTRY_LIMIT = 5
_NARRATIVE_RECENT_ENTRY_CHAR_BUDGET = 1200  # per entry; trim outliers


async def _fetch_narrative_context(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    for_date: date,
) -> dict[str, Any]:
    """Pull the user's recent journal narrative for CBT-aware coaching.

    Returns a dict with three keys:
      sentiment       — {avg_7d, avg_30d, delta} or {Nones} when no signals.
      harsh_streak    — int (consecutive days of harsh self-talk back from for_date).
      themes          — list[(theme, count)] from the last 14 days.
      recent_entries  — list[{date, title, body}] for the last N journal notes
                        the user has written (any journal-kind collection in
                        this household), oldest first within the list.

    All fields are safe defaults when the user has no journal entries yet
    or signal extraction is off — the coach falls back to behavior-only
    reasoning rather than hallucinating a narrative.
    """
    from life_dashboard.ai.journal_signal_service import (
        sentiment_trend,
        harsh_self_talk_streak,
        dominant_themes_recent,
    )
    from life_dashboard.domains.collections.models import Collection
    from life_dashboard.domains.notes.models import Note

    narrative: dict[str, Any] = {
        "sentiment": {"avg_7d": None, "avg_30d": None, "delta": None},
        "harsh_streak": 0,
        "themes": [],
        "recent_entries": [],
    }

    try:
        narrative["sentiment"] = await sentiment_trend(db, user_id, for_date)
    except Exception:
        logger.exception("sentiment_trend failed — proceeding without it")

    try:
        narrative["harsh_streak"] = await harsh_self_talk_streak(db, user_id, for_date)
    except Exception:
        logger.exception("harsh_self_talk_streak failed — proceeding without it")

    try:
        narrative["themes"] = await dominant_themes_recent(
            db, user_id, for_date, window_days=14, top_n=5
        )
    except Exception:
        logger.exception("dominant_themes_recent failed — proceeding without it")

    # Recent raw entries — looked up by the household's journal-kind
    # collections, restricted to this user's notes, sorted newest first
    # then reversed in the prompt builder to read oldest-first.
    try:
        journal_collection_ids = [
            cid for (cid,) in (await db.execute(
                select(Collection.id).where(
                    Collection.household_id == household_id,
                    Collection.kind == "journal",
                )
            )).all()
        ]
        if journal_collection_ids:
            rows = (await db.execute(
                select(Note.title, Note.content_md, Note.created_at)
                .where(
                    Note.household_id == household_id,
                    Note.created_by_user_id == user_id,
                    Note.collection_id.in_(journal_collection_ids),
                    Note.archived_at.is_(None),
                )
                .order_by(Note.updated_at.desc())
                .limit(_NARRATIVE_RECENT_ENTRY_LIMIT)
            )).all()
            entries = []
            for n in rows:
                body = (n.content_md or "").strip()
                if not body:
                    continue
                if len(body) > _NARRATIVE_RECENT_ENTRY_CHAR_BUDGET:
                    body = body[:_NARRATIVE_RECENT_ENTRY_CHAR_BUDGET] + " […]"
                entries.append({
                    "title": (n.title or "Untitled").strip(),
                    "body": body,
                    "created_at": n.created_at,
                })
            narrative["recent_entries"] = entries
    except Exception:
        logger.exception("recent journal entry fetch failed — proceeding without it")

    return narrative


# ── Phase 3: CBT method-layer system prompt ───────────────────────────────────

# Stable system-prompt fragment loaded on every coach run, regardless of tone.
# Tones describe the *voice* (warm vs stoic vs drill sergeant vs gentle
# mentor). This fragment describes the *method* shared across all tones.
#
# Intentional design choices:
# - The model is given three named context streams and a *job* (notice the
#   gap between narrative and behavior), not a long list of rules.
# - Every move is paired with what to do when both signals point the same
#   way (positive or negative) so the model never has to invent a "lesson"
#   from a clean run.
# - The profile is opaque to the user-facing response: name-dropping it
#   feels like surveillance, even when it's accurate.
# - Journal quoting is bounded sharply because the loss landscape is
#   asymmetric — a great quote helps a little; a bad one feels invasive.
_COACH_METHOD_PROMPT = """You have three sources of context about this person, listed in the
prompt below:

1. Their PROFILE — long-term memory of who they are, what they're working
   on, what they value, what tends to drain them, recurring patterns they
   themselves have noticed.
2. Their RECENT NARRATIVE — how they've been talking about their
   experience in their journal lately. You receive structured signals
   (sentiment trend, harsh self-talk streak, dominant themes) AND the
   last few entries verbatim.
3. Their BEHAVIORAL DATA — what they actually completed, their habit
   consistency, their goal progress, and how recent activity compares
   to prior weeks.

Your job is not to summarize any one of these. It is to notice when they
*diverge*, and respond to the gap. Concretely:

- If the writer sounds harsh on themselves but the data shows a normal or
  strong week → gently reality-test. Name what the data actually shows.
  Do not be preachy. One sentence is plenty.
- If the writer sounds confident but the data shows a real dip → be
  honest, not flattering. Honesty is the kindness here.
- If both narrative and data are negative → name it briefly, normalize
  it ("happens to everyone"), and stay with them. Bird-by-bird register.
  Do NOT pile on advice. One next step at most.
- If both are positive → notice it without inflating it. Do not
  manufacture a lesson from a clean run.
- Reference the profile to make the response feel like it's for *this*
  person, not for anyone. But do NOT name-drop the profile — never say
  "I see from your profile that…" or "you've told me before that…".
- Quote the writer's own journal language at most once per response, and
  only when the quote lands as *seen* rather than *surveilled*. When in
  doubt, paraphrase instead.
- If the profile is empty or the narrative stream is empty, do not
  invent one. Fall back to grounded reflection on the behavioral data
  alone.

You are not a therapist and you do not diagnose. You are a coach who has
been watching this person for a while and responds to the whole picture."""


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


def _fmt_weekly_completions(weekly: list[dict], for_date: date) -> str:
    """Format a 6-week completion sparkline with context."""
    if not weekly:
        return "  (no completion history)"

    lines = []
    total = sum(w["count"] for w in weekly)
    avg = total / len(weekly) if weekly else 0

    for w in weekly:
        count = w["count"]
        bar = "█" * min(count, 20)  # cap bar at 20 chars
        lines.append(f"  Week of {w['week_start']}: {count:>3} tasks  {bar}")

    # Current-week vs historical average
    if len(weekly) >= 2:
        this_week_count = weekly[-1]["count"]
        prior_avg = sum(w["count"] for w in weekly[:-1]) / (len(weekly) - 1)
        if prior_avg > 0:
            pct_diff = round((this_week_count - prior_avg) / prior_avg * 100)
            if pct_diff > 0:
                lines.append(f"\n  ↑ {pct_diff}% above your {len(weekly)-1}-week average of {prior_avg:.0f}/week")
            elif pct_diff < 0:
                lines.append(f"\n  ↓ {abs(pct_diff)}% below your {len(weekly)-1}-week average of {prior_avg:.0f}/week")
            else:
                lines.append(f"\n  → Right on your {len(weekly)-1}-week average of {prior_avg:.0f}/week")

    return "\n".join(lines)


def _fmt_habit_trends(trends: list[dict]) -> str:
    if not trends:
        return "  (no habit data)"
    lines = []
    for h in trends:
        r7 = f"{h['rate_7d']}%" if h["rate_7d"] is not None else "—"
        r30 = f"{h['rate_30d']}%" if h["rate_30d"] is not None else "—"
        # Trend arrow: compare 7d vs 30d rates
        if h["rate_7d"] is not None and h["rate_30d"] is not None:
            diff = h["rate_7d"] - h["rate_30d"]
            arrow = " ↑" if diff >= 10 else (" ↓" if diff <= -10 else "  ")
        else:
            arrow = "  "
        lines.append(f"  {arrow} {h['name']}: {r7} (7d) vs {r30} (30d)")
    return "\n".join(lines)


def _fmt_narrative(narrative: dict[str, Any]) -> str:
    """Format the narrative-context block for inclusion in user messages.

    Returns "" when there's no narrative to surface — the prompt builders
    omit the whole section in that case rather than render an empty header.
    """
    if not narrative:
        return ""

    has_signals = (
        narrative.get("sentiment", {}).get("avg_30d") is not None
        or narrative.get("harsh_streak", 0) > 0
        or bool(narrative.get("themes"))
    )
    has_entries = bool(narrative.get("recent_entries"))
    if not (has_signals or has_entries):
        return ""

    lines: list[str] = ["## Recent narrative", ""]

    # Structured trend numbers — small, dense, easy for the coach to
    # reason about without re-reading text.
    sent = narrative.get("sentiment", {})
    avg_7 = sent.get("avg_7d")
    avg_30 = sent.get("avg_30d")
    delta = sent.get("delta")
    if avg_7 is not None or avg_30 is not None:
        a7 = f"{avg_7:+.2f}" if avg_7 is not None else "—"
        a30 = f"{avg_30:+.2f}" if avg_30 is not None else "—"
        d = f"{delta:+.2f}" if delta is not None else "—"
        lines.append(
            f"**Journal sentiment:** 7d avg {a7} vs 30d avg {a30} (delta {d}). "
            f"Range is -1.00 (very negative) to +1.00 (very positive)."
        )

    streak = narrative.get("harsh_streak", 0)
    if streak >= 1:
        lines.append(
            f"**Self-talk:** {streak} consecutive day(s) of harsh self-talk "
            f"in the journal (anchored at today, going back)."
        )

    themes = narrative.get("themes") or []
    if themes:
        joined = ", ".join(f"{t} (×{c})" for t, c in themes)
        lines.append(f"**Dominant themes (last 14 days):** {joined}")

    # Raw recent entries — oldest first so the coach reads them
    # chronologically. Bounded by _NARRATIVE_RECENT_ENTRY_LIMIT and
    # per-entry char budget in the fetcher.
    if has_entries:
        lines.append("")
        lines.append("**Last few journal entries (oldest first):**")
        # The fetcher returns newest-first; reverse for chronological read.
        for e in reversed(narrative["recent_entries"]):
            created = e["created_at"]
            try:
                date_str = created.date().isoformat()
            except AttributeError:
                date_str = str(created)[:10]
            lines.append("")
            lines.append(f"#### {date_str} — {e['title']}")
            lines.append(e["body"])

    return "\n".join(lines)


def _fmt_focus(focus: str | None) -> str:
    """Format the user-supplied 'focus' text into a labelled section.

    Used by all three digest builders. Returns "" when focus is missing or
    blank, so callers can append unconditionally.
    """
    if not focus:
        return ""
    cleaned = focus.strip()
    if not cleaned:
        return ""
    # Cap to keep prompt size predictable. Users will write 1-2 sentences;
    # longer free-text gets trimmed rather than blowing the prompt budget.
    if len(cleaned) > 1000:
        cleaned = cleaned[:1000] + " […]"
    return (
        "## What I want you to focus on right now\n\n"
        + cleaned
        + "\n\n"
        + "Weight this above the standard briefing structure. If it "
        + "conflicts with the default sections, follow this guidance."
    )


def _build_morning_user_message(
    display_name: str,
    for_date: date,
    ctx: dict[str, Any],
    include_goals: bool,
    include_projects: bool,
    narrative: dict[str, Any] | None = None,
    focus: str | None = None,
) -> str:
    yesterday = date.fromordinal(for_date.toordinal() - 1)
    pinned_names = ctx.get("pinned_project_names", [])
    pinned_yesterday = ctx.get("todos_completed_yesterday_pinned", [])
    all_yesterday = ctx.get("todos_completed_yesterday", [])

    parts = [
        f"Good morning, {display_name}! Today is {for_date.strftime('%A, %B %d')}.",
        "",
        f"## Yesterday ({yesterday.strftime('%A, %B %d')})",
        "",
    ]

    if pinned_names and pinned_yesterday:
        # Lead with project-specific work — this is the primary focus
        project_label = " / ".join(pinned_names)
        parts += [
            f"**Completed in {project_label} (focus project):**",
            _fmt_todo_list(pinned_yesterday),
            "",
        ]
        # Show remaining household todos that aren't in the pinned project
        pinned_titles = {t["title"] for t in pinned_yesterday}
        other_yesterday = [t for t in all_yesterday if t["title"] not in pinned_titles]
        if other_yesterday:
            parts += [
                "**Other completed tasks:**",
                _fmt_todo_list(other_yesterday),
                "",
            ]
    else:
        parts += [
            "**Completed tasks:**",
            _fmt_todo_list(all_yesterday),
            "",
        ]

    parts += [
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
    ]

    # Phase 3: narrative section, inserted before the briefing instructions
    # so the model has the full picture when it starts composing.
    narrative_block = _fmt_narrative(narrative or {})
    if narrative_block:
        parts += ["", narrative_block]

    # coach-004: user-supplied focus text. Rendered last (right before the
    # briefing instructions) so it's the freshest thing in the prompt when
    # the model starts composing.
    focus_block = _fmt_focus(focus)
    if focus_block:
        parts += ["", focus_block]

    parts += [
        "",
        "Please give me a morning briefing covering:",
    ]

    if pinned_names:
        project_label = " / ".join(pinned_names)
        parts += [
            f"1. A focused reflection on yesterday's progress in {project_label} — this is the primary lens",
            "2. Any other notable accomplishments or habit results from yesterday",
            "3. What's on my plate today — highlight anything overdue",
            "4. A short motivational close (keep it genuine, not generic)",
        ]
    else:
        parts += [
            "1. A brief reflection on yesterday (what I accomplished, how habits went)",
            "2. What's on my plate today — highlight anything overdue",
            "3. A short motivational close (keep it genuine, not generic)",
        ]

    parts += [
        "",
        "Keep your response to 3–5 short paragraphs. No bullet-point dumps.",
    ]
    return "\n".join(parts)


def _build_weekly_user_message(
    display_name: str,
    for_date: date,
    ctx: dict[str, Any],
    history: dict[str, Any],
    include_goals: bool,
    include_projects: bool,
    narrative: dict[str, Any] | None = None,
    focus: str | None = None,
) -> str:
    """Weekly Friday review prompt — trajectory and higher-level reflection."""
    pinned_names = ctx.get("pinned_project_names", [])
    pinned_today = ctx.get("todos_completed_today_pinned", [])
    all_today = ctx.get("todos_completed_today", [])

    # Compute week start (Monday) for the label
    days_since_monday = for_date.weekday()  # Mon=0
    week_start = date.fromordinal(for_date.toordinal() - days_since_monday)

    parts = [
        f"Good Friday evening, {display_name}! Today is {for_date.strftime('%A, %B %d')}.",
        "",
        "## This week's completions",
        "",
    ]

    if pinned_names and pinned_today:
        project_label = " / ".join(pinned_names)
        parts += [
            f"**Completed in {project_label} today:**",
            _fmt_todo_list(pinned_today),
            "",
        ]
        pinned_titles = {t["title"] for t in pinned_today}
        other_today = [t for t in all_today if t["title"] not in pinned_titles]
        if other_today:
            parts += ["**Other tasks today:**", _fmt_todo_list(other_today), ""]
    elif all_today:
        parts += ["**Completed today:**", _fmt_todo_list(all_today), ""]

    # Rolling 6-week history
    parts += [
        "## Rolling 6-week completion history",
        "",
        _fmt_weekly_completions(history.get("weekly_completions", []), for_date),
    ]

    # Habit trends
    if history.get("habit_trends"):
        parts += [
            "",
            "## Habit trends (7-day vs 30-day completion rate)",
            "",
            _fmt_habit_trends(history["habit_trends"]),
        ]

    if include_goals:
        parts += ["", "**Goal progress:**", _fmt_goals(ctx["goals"])]

    if include_projects:
        parts += ["", "**Active projects:**", _fmt_projects(ctx["projects"])]

    parts += ["", "**Habits this week:**", _fmt_habit_list(ctx["habits_today"])]

    # Phase 3: narrative section before the review instructions.
    narrative_block = _fmt_narrative(narrative or {})
    if narrative_block:
        parts += ["", narrative_block]

    # coach-004: user-supplied focus text.
    focus_block = _fmt_focus(focus)
    if focus_block:
        parts += ["", focus_block]

    parts += [
        "",
        "Please give me a weekly Friday review covering:",
    ]
    if pinned_names:
        project_label = " / ".join(pinned_names)
        parts += [
            f"1. Reflect on this week's progress in {project_label} — what moved forward?",
            "2. Highlight any meaningful trend in the 6-week history — am I accelerating, maintaining, or slipping?",
            "3. Note habit trends — where am I improving or regressing?",
            "4. A brief, grounding close that sets the tone for the weekend",
        ]
    else:
        parts += [
            "1. Reflect on this week overall — what got done, what didn't?",
            "2. Highlight any meaningful trend in the 6-week history — am I accelerating, maintaining, or slipping?",
            "3. Note habit trends — where am I improving or regressing?",
            "4. A brief, grounding close that sets the tone for the weekend",
        ]
    parts += [
        "",
        "This is a higher-level, longitudinal view — not just today. Draw on the multi-week history to say something meaningful about trajectory.",
        "Keep it to 4–5 paragraphs. Reference actual numbers from the history when it makes the point stronger.",
    ]
    return "\n".join(parts)


def _build_evening_user_message(
    display_name: str,
    for_date: date,
    ctx: dict[str, Any],
    include_goals: bool,
    include_projects: bool,
    history: dict[str, Any] | None = None,
    narrative: dict[str, Any] | None = None,
    focus: str | None = None,
) -> str:
    pinned_names = ctx.get("pinned_project_names", [])
    pinned_today = ctx.get("todos_completed_today_pinned", [])
    all_today = ctx.get("todos_completed_today", [])

    parts = [
        f"Good evening, {display_name}. Today is {for_date.strftime('%A, %B %d')}.",
        "",
        "## Today's accomplishments",
        "",
    ]

    if pinned_names and pinned_today:
        # Lead with project-specific work — this is the primary focus
        project_label = " / ".join(pinned_names)
        parts += [
            f"**Completed in {project_label} (focus project):**",
            _fmt_todo_list(pinned_today),
            "",
        ]
        # Show remaining household todos not in the pinned project
        pinned_titles = {t["title"] for t in pinned_today}
        other_today = [t for t in all_today if t["title"] not in pinned_titles]
        if other_today:
            parts += [
                "**Other completed tasks:**",
                _fmt_todo_list(other_today),
                "",
            ]
    else:
        parts += [
            "**Completed tasks today:**",
            _fmt_todo_list(all_today),
            "",
        ]

    parts += [
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

    # Historical trajectory — only include when data exists
    weekly = history.get("weekly_completions", []) if history else []
    habit_trends = history.get("habit_trends", []) if history else []
    if weekly or habit_trends:
        parts += ["", "## Your trajectory (last 6 weeks)"]
        if weekly:
            parts += ["", "**Weekly completion history:**", _fmt_weekly_completions(weekly, for_date)]
        if habit_trends:
            parts += ["", "**Habit trends (7-day vs 30-day):**", _fmt_habit_trends(habit_trends)]

    # Phase 3: narrative section.
    narrative_block = _fmt_narrative(narrative or {})
    if narrative_block:
        parts += ["", narrative_block]

    # coach-004: user-supplied focus text.
    focus_block = _fmt_focus(focus)
    if focus_block:
        parts += ["", focus_block]

    parts += [
        "",
        "Please give me an evening wind-down summary covering:",
    ]

    if pinned_names:
        project_label = " / ".join(pinned_names)
        parts += [
            f"1. A focused acknowledgment of today's progress in {project_label} — this is the primary lens",
            "2. Any other notable wins from today",
            "3. A gentle note on what's still open — without stress or guilt",
        ]
    else:
        parts += [
            "1. A brief acknowledgment of what I got done today",
            "2. A gentle note on what's still open — without stress or guilt",
        ]

    if weekly:
        parts += [
            "4. End with a brief trajectory note — look at the multi-week history and say something genuine about the arc. Some days are lighter; zoom out and show the bigger picture. If today was slow, reassure with the trend. If today was strong, celebrate the momentum.",
        ]
    else:
        parts += [
            "3. A calm, grounding close to help me shift into evening mode",
        ]

    parts += [
        "",
        "Keep it to 3–5 short paragraphs. Warm and unhurried.",
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
    focus: str | None = None,
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

    # Resolve descendant project IDs once for the history query (same BFS used in _fetch_context)
    all_pinned_ids = await _get_descendant_project_ids(
        db, household_id, [uuid.UUID(p) for p in pinned_project_ids]
    ) if pinned_project_ids else []

    is_weekly = kind in (CoachDigestKind.weekly, "weekly")
    is_evening = kind in (CoachDigestKind.evening, "evening")

    # Fetch history for evening and weekly digests (not needed for morning briefing)
    history: dict[str, Any] = {}
    if is_evening or is_weekly:
        try:
            history = await _fetch_history(
                db, household_id, user_id, for_date,
                pinned_project_ids, pinned_habit_ids, all_pinned_ids,
            )
        except Exception:
            logger.exception("History fetch failed — proceeding without historical context")

    # Phase 3: narrative-context fetch (sentiment trend, harsh-self-talk
    # streak, dominant themes, last few raw journal entries). All-safe
    # defaults when the user has no journal entries yet — the prompt
    # builder omits the section entirely in that case.
    narrative: dict[str, Any] = {}
    try:
        narrative = await _fetch_narrative_context(db, household_id, user_id, for_date)
    except Exception:
        logger.exception(
            "Narrative context fetch failed — proceeding without narrative"
        )

    if kind == CoachDigestKind.morning or kind == "morning":
        tone_voice = tone_def["morning_voice"]
        user_msg = _build_morning_user_message(
            display_name, for_date, ctx, include_goals, include_projects,
            narrative=narrative, focus=focus,
        )
    elif is_weekly:
        tone_voice = tone_def["evening_voice"]  # weekly uses the same reflective voice
        user_msg = _build_weekly_user_message(
            display_name, for_date, ctx, history, include_goals, include_projects,
            narrative=narrative, focus=focus,
        )
    else:
        tone_voice = tone_def["evening_voice"]
        user_msg = _build_evening_user_message(
            display_name, for_date, ctx, include_goals, include_projects, history,
            narrative=narrative, focus=focus,
        )

    # Phase 3: layer the system prompt as
    #   [tone voice]
    #   ## How to coach
    #   [_COACH_METHOD_PROMPT]
    #   [profile fragment, if any]
    #
    # Tones describe *voice* (warm vs stoic vs drill sergeant vs gentle
    # mentor); the method describes the CBT-style moves that are shared
    # across all tones. Profile is added last so it reads as concrete
    # context, not as a rule.
    system = tone_voice + "\n\n## How to coach\n\n" + _COACH_METHOD_PROMPT

    try:
        from life_dashboard.ai.profile_service import load_profile_context
        profile_fragment = await load_profile_context(db, user_id)
        if profile_fragment:
            system = system + "\n\n" + profile_fragment
    except Exception:
        logger.exception("Profile load failed for coach digest — proceeding without profile")

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
        from sqlalchemy.orm import selectinload
        # Load all users who have preferences set (may have a coach widget).
        # selectinload is required — async SQLAlchemy cannot lazy-load relationships
        # from within a scheduler callback (no greenlet context).
        users = (await db.execute(
            select(User)
            .options(selectinload(User.memberships))
            .where(User.is_active == True, User.preferences.isnot(None))
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
