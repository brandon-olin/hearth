"""Journal signal extraction service — Phase 2 of AI coach redesign.

For every saved note in a journal-kind collection, the AI extracts a small
structured JSON document (sentiment, self-talk valence, themes, notable
phrases, energy level) and persists it as one journal_signals row. The
coach reads these rows at digest time to do trend math without re-reading
raw journal content each run.

Three entry points:
  - extract_signals_for_note: run extraction for one note. Used by the
    on-save hook in notes service and by the backfill endpoint.
  - maybe_extract_signals: gated wrapper called from the notes hook —
    checks the journal-kind flag and the per-user opt-out flag before
    spawning a background task.
  - backfill_for_user: re-runs extraction for every journal note this
    user has written (or only those at an older extraction_version).

Plus trend helpers used by the coach in Phase 3:
  - sentiment_trend
  - harsh_self_talk_streak
  - dominant_themes_recent

See docs/ai-coach-redesign.md → Phase 2 for the full design.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai.models import AiSettings, JournalSignal
from life_dashboard.ai.provider import AIProvider
from life_dashboard.ai.service import record_usage

logger = logging.getLogger(__name__)


# Bump this when the extraction prompt changes meaningfully. Lets us
# re-extract older rows during a backfill without re-doing the rows that
# are already current.
EXTRACTION_VERSION = 1

_VALID_VALENCES = {"positive", "neutral", "harsh", "mixed"}
_VALID_ENERGY = {"low", "medium", "high"}
_NOTE_CONTENT_CHAR_BUDGET = 6000  # trim very long entries before extraction


_EXTRACTOR_SYSTEM_PROMPT = """You are extracting structured signal from a single journal entry. Your
output will be persisted as a small JSON document used by an AI life coach
to track emotional and behavioural trends WITHOUT re-reading the entry
every time.

Read the entry carefully and return ONLY a JSON object with this exact
shape (no preamble, no code fences, no commentary):

{
  "sentiment": <number from -1.00 to 1.00, two decimals>,
  "self_talk_valence": "positive" | "neutral" | "harsh" | "mixed",
  "themes": [<short string>, ...],          // max 5; lowercase short phrases
  "notable_phrases": [<short string>, ...], // max 3; verbatim short quotes
  "energy_level": "low" | "medium" | "high" | null
}

Rules:
- sentiment: how the writer FEELS overall, not the events described.
  A bad day described with equanimity is closer to 0 than to -1.
- self_talk_valence: how the writer is talking to themselves about
  themselves. "harsh" = self-critical, self-blaming, all-or-nothing.
  "mixed" = swings between supportive and harsh in the same entry.
- themes: durable topics that recur or feel important to the writer.
  Examples: "consistency", "work stress", "relationships", "money",
  "sleep". Skip one-off subjects.
- notable_phrases: short verbatim quotes (under ~10 words each) the
  coach can use sparingly to make a callback feel "seen". Skip if
  nothing landed.
- energy_level: only set when the writer named it (mentions tiredness,
  burnout, feeling alive, etc.). Null otherwise.
- If the entry is too short or generic to extract meaningfully, still
  return valid JSON with sentiment 0.0, valence "neutral", and empty
  arrays. Do NOT refuse or apologize.

Output MUST be valid JSON parseable by json.loads."""


# ── Entry-date resolution ─────────────────────────────────────────────────────

def _resolve_entry_date(note_title: str | None, fallback: datetime) -> date:
    """Infer the date this entry is *about*.

    Auto-create rule produces titles like "Tuesday, May 25, 2026"; we try
    to recover a date from that. If parsing fails, fall back to the note's
    created_at date. The 1-day-off "I journal about Tuesday on Wednesday
    morning" case is handled because the auto-create rule fires for the
    current day — the title carries the right date.
    """
    if note_title:
        # Match "Month DD, YYYY" — robust to weekday prefix and ordinal suffixes.
        # Use a generous regex; fall back on failure rather than guessing.
        match = re.search(
            r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})",
            note_title,
        )
        if match:
            month_str, day_str, year_str = match.groups()
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    parsed = datetime.strptime(
                        f"{month_str} {day_str} {year_str}", fmt
                    )
                    return parsed.date()
                except ValueError:
                    continue
    return fallback.astimezone(timezone.utc).date()


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_extractor_response(text: str) -> dict[str, Any]:
    """Parse the extractor JSON, defending against minor formatting drift."""
    # Strip code fences if the model added them despite the instructions.
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the first fence line and any trailing fence.
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


def _coerce_sentiment(value: Any) -> Decimal:
    """Coerce sentiment into a Decimal in [-1.00, 1.00]."""
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")
    if d < Decimal("-1"):
        return Decimal("-1.00")
    if d > Decimal("1"):
        return Decimal("1.00")
    return d


def _coerce_valence(value: Any) -> str:
    v = (value or "").strip().lower() if isinstance(value, str) else ""
    return v if v in _VALID_VALENCES else "neutral"


def _coerce_energy(value: Any) -> str | None:
    if value is None:
        return None
    v = value.strip().lower() if isinstance(value, str) else ""
    return v if v in _VALID_ENERGY else None


def _coerce_string_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:200])
        if len(out) >= max_items:
            break
    return out


# ── Extraction core ───────────────────────────────────────────────────────────

async def extract_signals_for_note(
    db: AsyncSession,
    provider: AIProvider,
    note: Any,  # Note ORM instance — annotated as Any to avoid a circular import
    user_id: uuid.UUID,
) -> JournalSignal | None:
    """Run extraction for one note. Upserts the journal_signals row.

    Returns the persisted JournalSignal, or None when there's nothing to
    extract (e.g. the note has no body). Caller commits the session.

    Never raises on extraction errors — the on-save hook must not break the
    note write. Errors are logged.
    """
    try:
        body = (getattr(note, "content_md", None) or "").strip()
        if not body:
            return None
        # Trim very long entries to keep extraction cheap & predictable.
        if len(body) > _NOTE_CONTENT_CHAR_BUDGET:
            body = body[:_NOTE_CONTENT_CHAR_BUDGET] + " […]"

        title = (getattr(note, "title", None) or "").strip()
        entry_date = _resolve_entry_date(
            title, getattr(note, "created_at", datetime.now(tz=timezone.utc))
        )

        user_msg = (
            f"Title: {title or '(untitled)'}\n"
            f"Date (inferred): {entry_date.isoformat()}\n\n"
            f"--- entry body ---\n{body}"
        )

        text, input_tok, output_tok, model = await provider.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=_EXTRACTOR_SYSTEM_PROMPT,
            max_tokens=512,
        )

        # Record usage (non-critical).
        if input_tok > 0 or output_tok > 0:
            try:
                await record_usage(
                    db,
                    user_id=user_id,
                    conversation_id=None,
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    model=model,
                    turn_kind="journal_extraction",
                )
            except Exception:
                logger.exception(
                    "Usage recording failed for journal extraction — ignoring"
                )

        try:
            parsed = _parse_extractor_response(text)
        except Exception:
            logger.exception(
                "Journal extraction returned non-JSON for note %s — skipping",
                note.id,
            )
            return None

        sentiment = _coerce_sentiment(parsed.get("sentiment"))
        valence = _coerce_valence(parsed.get("self_talk_valence"))
        themes = _coerce_string_list(parsed.get("themes"), max_items=5)
        phrases = _coerce_string_list(parsed.get("notable_phrases"), max_items=3)
        energy = _coerce_energy(parsed.get("energy_level"))

        # Upsert (unique on note_id). We delete-then-insert rather than ORM
        # merge so that re-extraction always lands on a fresh row with the
        # current extraction_version — there's nothing we want to preserve
        # from the old row.
        await db.execute(
            delete(JournalSignal).where(JournalSignal.note_id == note.id)
        )
        signal = JournalSignal(
            note_id=note.id,
            user_id=user_id,
            entry_date=entry_date,
            sentiment=sentiment,
            self_talk_valence=valence,
            themes=themes,
            notable_phrases=phrases,
            energy_level=energy,
            extraction_version=EXTRACTION_VERSION,
        )
        db.add(signal)
        return signal

    except Exception:
        logger.exception(
            "extract_signals_for_note failed for note %s — skipping",
            getattr(note, "id", "?"),
        )
        return None


# ── Save-time gating ──────────────────────────────────────────────────────────

async def maybe_extract_signals(
    db: AsyncSession,
    note: Any,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
) -> None:
    """Fire-and-forget hook called from notes service after create/update.

    Spawns a background task that runs extraction IF:
      - the note belongs to a collection with kind='journal'
      - AND the user has ai_journal_extraction_enabled=true
      - AND the user has an AI provider configured

    Never raises; failures are logged and swallowed.
    """
    try:
        from life_dashboard.domains.collections.models import Collection

        if not getattr(note, "collection_id", None):
            return

        # Cheap gate first: is this note in a journal-kind collection?
        col = (await db.execute(
            select(Collection.kind).where(Collection.id == note.collection_id)
        )).scalar_one_or_none()
        if col != "journal":
            return

        # Honor the per-user opt-out flag.
        settings = (await db.execute(
            select(AiSettings).where(AiSettings.user_id == user_id)
        )).scalar_one_or_none()
        if settings is None or not settings.ai_journal_extraction_enabled:
            return

        # Run in a detached task with its own session so the note-write
        # commit isn't delayed by the AI call.
        import asyncio
        asyncio.create_task(
            _run_extraction_background(note.id, user_id, household_id)
        )
    except Exception:
        logger.exception(
            "maybe_extract_signals failed for note %s — ignoring",
            getattr(note, "id", "?"),
        )


async def _run_extraction_background(
    note_id: uuid.UUID,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
) -> None:
    """Background task — opens a fresh session, fetches the note, extracts."""
    from life_dashboard.core.database import AsyncSessionLocal
    from life_dashboard.ai.service import get_provider
    from life_dashboard.domains.notes.models import Note

    try:
        async with AsyncSessionLocal() as db:
            # Resolve provider for this user.
            settings = (await db.execute(
                select(AiSettings).where(AiSettings.user_id == user_id)
            )).scalar_one_or_none()
            if settings is None:
                logger.info(
                    "Journal extraction skipped: no AI settings for user %s",
                    user_id,
                )
                return
            provider = get_provider(settings)
            if provider is None:
                logger.info(
                    "Journal extraction skipped: no provider for user %s",
                    user_id,
                )
                return

            # Re-fetch the note in this session.
            note = (await db.execute(
                select(Note).where(Note.id == note_id)
            )).scalar_one_or_none()
            if note is None:
                # Note was deleted between save and extraction; nothing to do.
                return

            signal = await extract_signals_for_note(db, provider, note, user_id)
            await db.commit()
            if signal is not None:
                logger.info(
                    "Extracted journal signals for note %s (user %s, sentiment=%s, valence=%s)",
                    note_id, user_id, signal.sentiment, signal.self_talk_valence,
                )
    except Exception:
        logger.exception(
            "Background journal extraction failed for note %s — ignoring",
            note_id,
        )


# ── Backfill ──────────────────────────────────────────────────────────────────

async def backfill_for_user(
    db: AsyncSession,
    provider: AIProvider,
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    *,
    limit: int = 500,
    only_outdated_version: bool = False,
) -> dict[str, int]:
    """Run extraction across every journal note this user has written.

    Used by the /ai/journal-signals/backfill endpoint. Runs SYNCHRONOUSLY
    in the request — the caller is doing this deliberately and should
    tolerate the latency. Returns counts so the UI can show progress.

    Args:
      only_outdated_version: when True, skip notes that already have a
        signal row at EXTRACTION_VERSION (used after prompt revs).
    """
    from life_dashboard.domains.collections.models import Collection
    from life_dashboard.domains.notes.models import Note

    journal_collection_ids = [
        cid for (cid,) in (await db.execute(
            select(Collection.id).where(
                Collection.household_id == household_id,
                Collection.kind == "journal",
            )
        )).all()
    ]
    if not journal_collection_ids:
        return {"scanned": 0, "extracted": 0, "skipped_empty": 0, "skipped_current": 0, "errors": 0}

    notes = (await db.execute(
        select(Note)
        .where(
            Note.household_id == household_id,
            Note.created_by_user_id == user_id,
            Note.collection_id.in_(journal_collection_ids),
            Note.archived_at.is_(None),
        )
        .order_by(Note.created_at.desc())
        .limit(limit)
    )).scalars().all()

    counts = {"scanned": 0, "extracted": 0, "skipped_empty": 0, "skipped_current": 0, "errors": 0}

    for note in notes:
        counts["scanned"] += 1
        body = (note.content_md or "").strip()
        if not body:
            counts["skipped_empty"] += 1
            continue

        if only_outdated_version:
            existing_version = (await db.execute(
                select(JournalSignal.extraction_version).where(
                    JournalSignal.note_id == note.id
                )
            )).scalar_one_or_none()
            if existing_version == EXTRACTION_VERSION:
                counts["skipped_current"] += 1
                continue

        signal = await extract_signals_for_note(db, provider, note, user_id)
        if signal is None:
            counts["errors"] += 1
        else:
            counts["extracted"] += 1
            await db.commit()  # commit per note so partial failures aren't lost

    return counts


# ── Trend helpers (used by the coach starting in Phase 3) ─────────────────────

async def sentiment_trend(
    db: AsyncSession,
    user_id: uuid.UUID,
    for_date: date,
) -> dict[str, float | None]:
    """Return {"avg_7d": x, "avg_30d": x, "delta": x} — 7-day vs 30-day mean
    sentiment. delta is avg_7d - avg_30d (positive = trending up).

    Returns None values when there aren't enough entries in the window.
    """
    seven_ago = date.fromordinal(for_date.toordinal() - 7)
    thirty_ago = date.fromordinal(for_date.toordinal() - 30)

    rows = (await db.execute(
        select(JournalSignal.entry_date, JournalSignal.sentiment).where(
            JournalSignal.user_id == user_id,
            JournalSignal.entry_date >= thirty_ago,
            JournalSignal.entry_date <= for_date,
        )
    )).all()
    if not rows:
        return {"avg_7d": None, "avg_30d": None, "delta": None}

    last_7 = [float(s) for d, s in rows if d >= seven_ago]
    last_30 = [float(s) for _, s in rows]
    avg_7 = sum(last_7) / len(last_7) if last_7 else None
    avg_30 = sum(last_30) / len(last_30) if last_30 else None
    delta = (avg_7 - avg_30) if (avg_7 is not None and avg_30 is not None) else None
    return {"avg_7d": avg_7, "avg_30d": avg_30, "delta": delta}


async def harsh_self_talk_streak(
    db: AsyncSession,
    user_id: uuid.UUID,
    for_date: date,
) -> int:
    """Return the current run of consecutive days (anchored at for_date,
    going back) where the writer's self_talk_valence was 'harsh'.

    Days with no entry break the streak. Used by the coach to detect "you've
    been hard on yourself for N days running" — the threshold for switching
    into the gentler 'bird by bird' register is a coach-prompt decision, not
    a service decision.
    """
    rows = (await db.execute(
        select(JournalSignal.entry_date, JournalSignal.self_talk_valence)
        .where(
            JournalSignal.user_id == user_id,
            JournalSignal.entry_date <= for_date,
        )
        .order_by(JournalSignal.entry_date.desc())
        .limit(60)
    )).all()
    if not rows:
        return 0

    by_date = {d: v for d, v in rows}
    streak = 0
    cursor = for_date
    while True:
        valence = by_date.get(cursor)
        if valence != "harsh":
            break
        streak += 1
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return streak


async def dominant_themes_recent(
    db: AsyncSession,
    user_id: uuid.UUID,
    for_date: date,
    *,
    window_days: int = 14,
    top_n: int = 5,
) -> list[tuple[str, int]]:
    """Return up to top_n (theme, count) pairs from the last window_days
    of journal signals. Used by the coach for "what's been on your mind".
    """
    since = date.fromordinal(for_date.toordinal() - window_days)
    rows = (await db.execute(
        select(JournalSignal.themes).where(
            JournalSignal.user_id == user_id,
            JournalSignal.entry_date >= since,
            JournalSignal.entry_date <= for_date,
        )
    )).all()

    counts: dict[str, int] = {}
    for (themes_list,) in rows:
        for theme in (themes_list or []):
            if not isinstance(theme, str) or not theme.strip():
                continue
            key = theme.strip().lower()
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
