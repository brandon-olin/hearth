# AI Coach Redesign — CBT-aware, three-layer context

**Status:** All four phases (1, 1.5, 2, 3, 4) implemented + journal-001 Phase A + B (guided journaling with personalized openers). **Silent-learning shift (2026-05-25):** the profile is no longer surfaced to the user — bootstrap auto-fires on API-key save, the proposed-diffs UI was removed, and chat-driven profile updates land via the `update_profile` tool the AI calls without asking. Phase 4 adds profile versioning + a weekly scheduled refresh-with-decay job. **journal-001 Phase A (2026-05-25):** adds a 'Talk it out' button to today's journal entry — full-screen guided session with adaptive AI register, role-clarity baked into the prompt, point-at-humans rule for interpersonal topics. Synthesized first-person summary; optional transcript below a divider. **journal-001 Phase B (2026-05-25):** the AI now *opens* sessions with a personalized message — pulls profile + sentiment trend + harsh-self-talk streak + dominant themes + time-of-day, generates a 1-2 sentence warm opener that doesn't direct the user.
**Owner:** Brandon
**Last updated:** 2026-05-25

> **Implementation note (2026-05-25)** — during build-out we discovered that
> `member_ai_memory.memory_text` already exists and is already read by the
> chatbot. Rather than introduce a new `user_profiles` table the
> implementation reuses that column as the profile blob and only adds:
> `last_bootstrapped_at` and `notes_at_last_proposal` to `member_ai_memory`,
> plus a new `user_profile_updates` table for the proposed-diffs workflow.
> The original "new table" wording below has been left intact for design
> reference, but the actual schema is leaner. See migrations 0030 and 0031.

---

## Summary

The current AI coach (`api/src/life_dashboard/ai/coach_service.py`) is a behavioral scorekeeper. It pulls todos, habits, goals, and projects, computes a 6-week rolling completion sparkline plus 7d-vs-30d habit trend rates, and renders a morning / evening / weekly digest in one of four tones. It does this well — the behavioral data layer is the *foundation* this redesign builds on, not something we're replacing.

What it can't do today is reason about *how the user feels about* the data. It doesn't read journal entries, it has no awareness of self-talk patterns, and it has no long-term memory of who the user is across sessions. Every morning it meets the user for the first time.

This document specifies a redesign that adds two new context streams alongside the existing behavioral one, gives both the coach and the AI chatbot a shared persistent understanding of the user, and updates the coach prompts to do explicit CBT moves: notice the user's narrative, reality-test it against the behavioral data, and reframe gently when the two diverge.

---

## What exists today

- **Coach service:** `api/src/life_dashboard/ai/coach_service.py` — morning/evening/weekly Friday digests, four tone personas, project-pinning, 6-week behavioral history, habit trend rates. ~1000 lines, well-factored.
- **Coach storage:** `ai_coach_digests` table (migration 0019, weekly added in 0024) — one row per (user, date, kind).
- **AI chatbot:** Separate surface (`/ai/chat` route in `ai/router.py`), independently configured tone, no shared context with the coach today.
- **Notes domain:** Zettelkasten-style atomic notes with markdown content, wikilinks, tags, BlockNote editor, and the `VisibilityMixin` for personal-vs-household scoping.
- **Collections:** Named views over the notes (or documents) domain, with default tags, optional auto-create rules ("daily entry"), and a `show_in_nav` flag. The journaling surface is meant to be a default Collection inside the notes domain, not a separate domain.

---

## What's missing

Three things, in order of leverage:

1. **A persistent user profile.** A long-term, structured-prose document — owned and editable by the user, maintained over time by the AI — that captures who the user is, what they're working on, what drains them, what works, recurring patterns. Read by *both* the coach and the chatbot at the start of every interaction.
2. **A narrative signal stream from journal entries.** Sentiment, themes, self-talk valence, and notable phrases extracted at journal write time and stored as features. Powers trend math like "harsh self-evaluation streak: 5 days" — the same shape of trend reasoning the behavioral side already does, but on the emotional/narrative axis.
3. **CBT-aware coach prompts.** New prompt structure that explicitly directs the coach to notice the narrative, compare it against the behavior, and respond to the *gap* between them — not just to the behavior alone.

---

## Design

### The three layers of context

Every coach run (and every chatbot conversation start) reads three layers, each at a different timescale:

| Layer | Timescale | What it captures | Storage |
|---|---|---|---|
| User profile | Long-term — who you are | Current focuses, values, recurring patterns, what drains/works, things to not bring up | Markdown blob on `user_profiles` table |
| Narrative signals | Medium-term — recent trajectory | Sentiment, themes, self-talk valence per entry; rolled-up trends | `journal_signals` table |
| Raw recent entries | Short-term — today's nuance | Last N journal entries verbatim | Existing `notes` rows in the Journal collection |

Existing behavioral layer (todos / habits / goals / projects) remains exactly as it is and is read alongside these.

### Why these three and not more

The temptation is to add a "mood tracker," a "values inventory questionnaire," a "weekly reflection prompt," and so on. Each is a separate surface the user has to remember to engage with. The point of this design is that **the only thing the user has to do is journal**. The profile is *derived* from the journal (plus existing notes/documents) and proposed back to the user; the signals are *extracted* automatically at write time. One input, three layers of derived context.

---

## Data model changes

### New table: `user_profiles`

One row per user. The profile is a single markdown document, not a schema of fields, to keep it expressive and human-editable. The AI maintains it via *proposed diffs* (never silent rewrites).

```
user_profiles
─────────────
id                    UUID  PK
user_id               UUID  FK users.id  UNIQUE  ON DELETE CASCADE
content_md            TEXT  — the profile itself; sectioned by H2 headers
last_bootstrapped_at  TIMESTAMPTZ  NULL  — when the initial pass was run
last_updated_at       TIMESTAMPTZ        — last accepted change (user or AI)
created_at            TIMESTAMPTZ
```

**Visibility:** Hard-coded personal scope. Never inherits `VisibilityMixin` — this is one-row-per-user data, never household-shared, never `members`-shared. Excluded by default from any future "export household data" feature.

**Proposed diffs:** A companion table `user_profile_updates` holds pending AI suggestions the user has not yet accepted:

```
user_profile_updates
────────────────────
id                  UUID  PK
user_id             UUID  FK users.id  ON DELETE CASCADE
proposed_content_md TEXT  — the AI's proposed new version
diff_summary        TEXT  — one-line natural language summary of the change
source              TEXT  — "bootstrap" | "incremental" | "manual"
created_at          TIMESTAMPTZ
status              ENUM("pending", "accepted", "rejected", "superseded")
resolved_at         TIMESTAMPTZ  NULL
```

The user reviews pending diffs in a dedicated UI surface (proposed: `/settings/coach/profile`) and accepts or rejects. On accept, `proposed_content_md` replaces `user_profiles.content_md` and `last_updated_at` advances.

### New table: `journal_signals`

One row per journal entry processed. Keyed by note ID — when a note in a Journal-typed collection is created or updated, a background extraction pass writes (or replaces) the row.

```
journal_signals
───────────────
id                  UUID  PK
note_id             UUID  FK notes.id  UNIQUE  ON DELETE CASCADE
user_id             UUID  FK users.id
entry_date          DATE  — the journal entry's *intended* date (from collection rule), not the note's created_at
sentiment           NUMERIC(3,2)  — -1.00 (very negative) to +1.00 (very positive)
self_talk_valence   ENUM("positive", "neutral", "harsh", "mixed")
themes              JSON  — short string array, e.g. ["consistency", "work stress"]
notable_phrases     JSON  — short string array; sparingly used for callbacks
energy_level        ENUM("low", "medium", "high")  NULL
extraction_version  INTEGER  — bumped when the extraction prompt changes; lets us re-extract
extracted_at        TIMESTAMPTZ
```

`entry_date` is separate from `created_at` because a user might journal *about Tuesday* on Wednesday morning, and the trend math should align with the day being reflected on.

### Marking the Journal collection

Add a `kind` column to `collections` (nullable, no default) that identifies semantic collection types the system needs to recognize. Initial values:

- `journal` — entries fed into the narrative signal extractor and into the coach's raw-text context.
- (future) `recipes`, `routines`, etc.

On first launch for a new user, seed a default Journal collection (`kind='journal'`, `domain='notes'`, `auto_create_rule={"frequency": "daily", ...}`) in the same flow that today creates the default household. Existing users get a one-time data migration that creates the collection if they don't have one with `kind='journal'`.

### Migrations

- `0030_user_profile.py` — adds `user_profiles` and `user_profile_updates` tables.
- `0031_journal_signals.py` — adds `journal_signals` table; backfill is empty (no historical extraction at migration time).
- `0032_collection_kind.py` — adds `kind` column to `collections`; backfills `kind='journal'` for any collection currently named "Journal" or with the daily-entry auto-create rule (best-effort heuristic; user can correct in settings).

---

## API surface

### Profile

```
GET    /ai/profile                     — current accepted profile
PATCH  /ai/profile                     — user edits content_md directly
POST   /ai/profile/bootstrap           — kick off the bootstrap pass (idempotent; returns the proposed update)
GET    /ai/profile/updates             — pending proposed diffs
POST   /ai/profile/updates/{id}/accept
POST   /ai/profile/updates/{id}/reject
```

### Signals

Signals are an internal concern; no public read endpoint in Phase 2. The coach and chatbot read them directly via service-layer calls. We may add a read endpoint later if we want to surface a "your recent emotional weather" widget.

Extraction is triggered from the notes service when a note is created or updated *and* its collection has `kind='journal'`. Done in-process synchronously for the local tier (acceptable latency on save); promoted to a background job (APScheduler) when we hit the NAS tier.

### Coach

The existing `/ai/coach/digest` endpoints don't change shape — they continue to return `CoachDigestResponse`. The internals change: `coach_service.py` gains a third context-fetcher (`_fetch_narrative_context`) alongside `_fetch_context` and `_fetch_history`, and the prompt builders incorporate profile + signals + recent raw entries.

### Chatbot

The chatbot's existing `/ai/chat` endpoint loads the user profile into the system prompt on every conversation start. Implementation: a single `_load_profile_context(user_id)` helper shared between coach and chatbot prompt assembly, so the two surfaces speak to the same person.

---

## The bootstrap pass

A one-time job, runnable per user via `POST /ai/profile/bootstrap`. Reads:

- All existing notes in the user's Journal collection (or any collection with `kind='journal'`).
- All other notes created by this user (best-effort signal — opt-out in settings).
- All documents the user has authored (best-effort signal — opt-out in settings).
- Existing behavioral data (last 90 days of completed todos, current goals/projects).

Drafts the first `user_profiles.content_md` as a proposed update (`user_profile_updates.source='bootstrap'`) using a fixed section structure:

```markdown
## Current focuses
…

## Values & non-negotiables
…

## Recurring patterns I've noticed
…

## What drains me
…

## What works for me
…

## Things to not bring up unless I do
…
```

User reviews and accepts in the same `/settings/coach/profile` UI. On accept, the profile is live and both the coach and chatbot start using it on next run.

**Why a bootstrap pass instead of cold-start incremental learning:** Brandon already has a year+ of data. Without bootstrap, the coach feels generic for the first month while the incremental pass slowly accumulates signal. With bootstrap, the profile is meaningful from day one. New users (no data) skip bootstrap and the profile builds incrementally as they journal.

---

## CBT-aware prompt redesign

The current tone definitions in `COACH_TONES` describe a *style* (warm vs stoic vs drill sergeant) but they don't describe a *method*. The redesign keeps the four tones — they're a real product feature — but adds a method layer shared across all tones.

The method, encoded as a stable system-prompt fragment loaded on every coach run:

> You are reviewing the user's day with three sources of information available to you:
> 1. Their **profile** — who they are, what they're working on, what they value, what tends to drain them, recurring patterns they've noticed about themselves.
> 2. Their **recent narrative** — how they've been talking about their experience in their own journal entries, including the emotional tone and any recurring themes from the past 1–3 weeks.
> 3. Their **behavioral data** — what they actually completed, their habit consistency, their goal progress, and how this week compares to recent weeks.
>
> Your job is not to summarize any one of these. It is to notice when they *diverge*, and respond to the gap.
>
> Concretely:
> - If the user is being harsh on themselves but the data shows a normal or strong week → gently reality-test. Name what the data actually shows. Don't be preachy.
> - If the user sounds confident but the data shows a real dip → be honest, not flattering. Honesty is the kindness here.
> - If both are negative → name it, normalize it briefly, and stay with them rather than rushing to fix it. "Bird by bird" register. Do not pile on advice.
> - If both are positive → notice it without inflating it. Don't manufacture a lesson where there isn't one.
> - Reference the profile to make the response feel like it's *for this person*, not for anyone. But do not name-drop the profile (don't say "I see from your profile that…").
> - Quote the user's own journal language sparingly — at most one short phrase per response, and only when it lands as *seen* rather than *surveilled*.

The tone fragments then layer the *voice* on top of this method.

---

## Privacy considerations

The narrative stream is the most sensitive data in the system. Decisions:

- **Profile scope is hard-coded personal.** Not a `VisibilityMixin` choice — it cannot be set to household. One row per user, always private.
- **Journal collection's notes use existing `VisibilityMixin`** but default to `personal` (already the case for the Journal use). The signal extraction respects this — extracted signals inherit the personal scope of the source note.
- **Signal extraction is opt-out per user.** Settings flag `ai_journal_extraction_enabled` (default true). When off, the coach falls back to behavioral-only mode and the chatbot reads only the profile.
- **Coach quoting is bounded by the prompt method (above)** — at most one short phrase per response, and only when contextually serving the moment. We will need to monitor this empirically; if the coach quotes too liberally or in unsettling ways, tighten the rule.
- **No third-party AI providers see profile content without consent.** For BYOK / cloud providers, the profile is sent in the same request as everything else; the existing AI provider configuration governs this. For users worried about provider exposure, the local-LLM path remains the privacy floor.
- **Profile and signals are excluded from default household export.** Any future export feature must explicitly opt in to including a user's personal profile + signals, and must do so per-user (only the requesting user can export their own).

---

## Open questions

- **How often does the incremental update pass run?** Options: after every N journal entries, weekly, on-demand only. Recommend: weekly background job that proposes a diff if it has enough new signal to be worth reading. Skip silently if not.
- **Should the chatbot also *propose* profile updates from conversations?** Probably yes eventually, but Phase 1 limits updates to the journal-driven flow to keep the loop simple.
- **What's the right N for "raw recent entries"?** Recommend: last 5 entries OR last 14 days, whichever is fewer entries (cap on prompt size).
- **Profile size cap?** Recommend: soft cap at ~4KB, hard cap at ~8KB. When proposed updates would push past the soft cap, the AI must also propose a *removal* (decay old entries).
- **Should the user be able to "pin" sections of the profile so the AI can't propose changes to them?** Phase 3 nice-to-have. For Phase 1, all sections are equally editable.
- **Versioning / history of the profile?** Probably worth a `user_profile_versions` table eventually so the user can roll back. Out of scope for Phase 1; the proposed-diffs table is a partial substitute.

---

## Phasing

### Phase 1 — User profile + bootstrap pass

**Priority:** Highest. Single biggest leverage point because it also unlocks the chatbot, not just the coach.

Scope:
- Migration 0030 (user_profiles + user_profile_updates).
- Service layer: profile CRUD, proposed-update CRUD, bootstrap pass implementation.
- Bootstrap reads existing notes/documents + behavioral data, drafts the first profile.
- Frontend: `/settings/coach/profile` page — view profile, view pending diffs, accept/reject, edit directly.
- Coach service: load profile into prompt assembly (uses placeholder narrative layer = empty for now).
- Chatbot service: load profile into prompt assembly.

Out of scope for Phase 1: journal signal extraction, CBT prompt rewrite (coach still uses today's prompts plus profile context).

**Why this first:** The profile alone makes both surfaces dramatically more useful. It's also the cleanest piece to build — no streaming extraction, no per-entry latency to manage. And we can ship it without touching the existing coach prompts at all.

### Phase 1.5 — Notes-driven incremental proposer ✅

**Priority:** Highest follow-up to Phase 1. Closes the "profile goes stale between bootstrap clicks" gap.

Scope:
- Migration 0031 (adds `notes_at_last_proposal` to `member_ai_memory`).
- New service helpers in `profile_service.py`: `maybe_propose_from_notes`, `_run_incremental_proposer`, `_gather_incremental_notes_context`.
- Hook into notes service: after `create_note` and any content/title `update_note` write, fire-and-forget call to the proposer. The hot path pays one counter query — the proposer's AI call runs in a detached `asyncio.create_task` with its own DB session.
- Threshold: 5 net-new notes between proposer runs. Tuned conservatively — we'd rather under-trigger than spam the user with low-signal proposals.
- The proposer is biased toward outputting `SKIP` — it only creates a pending update when the recent notes clearly support a durable change. The system prompt for the proposer is the same one used by bootstrap (in `_PROPOSER_SYSTEM_PROMPT`), so both surfaces apply the same editorial restraint.
- Skips entirely until bootstrap has run at least once — we never silently populate a profile from scratch via the incremental path. Bootstrap remains the explicit opt-in.

What this gives the user: after running bootstrap once, the profile stays roughly current as they journal, without manual re-bootstrap clicks. Every accepted incremental update flows through the same `user_profile_updates` UI as bootstrap proposals.

Out of scope (deferred to Phase 4): scheduled background proposer (currently event-driven only), chatbot conversation activity as a trigger source, decay of stale profile sections.

### Phase 2 — Journal signal extraction ✅

**Priority:** High. Required for the CBT moves to work.

Implementation note (deviates slightly from the original Phase 2 spec):
- Migration **0032** adds `collection.kind` (with a Postgres heuristic backfill for existing journal-looking collections) + seeds a Journal collection for every household. New users get the seed via the household-bootstrap path in `setup/router.py` and `auth/router.py` (mirrors `seed_system_project`).
- Migration **0033** creates `journal_signals` + adds `ai_journal_extraction_enabled` to `ai_settings` (default true).
- `ai/journal_signal_service.py` (new file, ~430 lines) owns extraction:
  - `extract_signals_for_note`: runs the extractor against one note, parses + coerces the JSON response, upserts the `journal_signals` row.
  - `maybe_extract_signals`: gated wrapper called from the notes hook — checks the journal-kind flag and the per-user opt-out before spawning an async background task with its own DB session.
  - `backfill_for_user`: synchronous backfill across every journal entry; supports `only_outdated_version=true` for post-prompt-rev re-runs.
  - Trend helpers used by the coach in Phase 3: `sentiment_trend`, `harsh_self_talk_streak`, `dominant_themes_recent`.
  - `_EXTRACTOR_SYSTEM_PROMPT` mandates JSON output and never refuses — short/generic entries get zero-valued signals rather than a refusal, so the extractor never silently drops rows.
  - `EXTRACTION_VERSION` constant: bump when the prompt changes; backfill can re-extract only outdated rows.
- Notes service hooks: `create_note` and any `update_note` that touches `content_md` fire `maybe_extract_signals` (and `maybe_propose_from_notes` from Phase 1.5) after the successful commit. Both helpers are fire-and-forget; a note save can never be broken by downstream AI issues.
- API surface: `POST /ai/journal-signals/backfill?only_outdated_version=...` returns per-category counts (`scanned`, `extracted`, `skipped_empty`, `skipped_current`, `errors`).
- Frontend: a new "Journal signals" subsection in Settings → AI with a toggle for `ai_journal_extraction_enabled` and a "Backfill existing entries" button that reports the result counts.

What this gives us: every journal entry the user saves produces a small persistent record of how they felt while writing it, what themes recurred, whether their self-talk was harsh, and what their energy was like — without storing or re-reading the raw journal content at digest time. Phase 3 reads these alongside the profile + last few raw entries to do the CBT moves.

Out of scope for Phase 2 (intentionally): visualization of signals in the dashboard (defer to a possible "emotional weather" widget later). Coach prompt rewrites that *use* the signals — that's Phase 3.

### Phase 3 — CBT-aware coach rewrite ✅

**Priority:** Medium-high. The payoff phase — this is where the user-visible behavior change happens.

Implementation:
- `_fetch_narrative_context(db, household_id, user_id, for_date)` added to `coach_service.py` (~80 lines). Returns `{sentiment: {avg_7d, avg_30d, delta}, harsh_streak: int, themes: list[(theme, count)], recent_entries: list[{title, body, created_at}]}`. Each sub-fetch is wrapped in its own try/except so one broken stream never blocks the others — degrades gracefully to safe defaults.
- `_COACH_METHOD_PROMPT` added (the stable CBT method-layer fragment). Specifies the four divergence cases (narrative harsh + data strong → reality-test; narrative confident + data dip → honest not flattering; both negative → bird-by-bird, one next step max; both positive → no manufactured lessons). Hard rules: no name-dropping the profile, journal quotes at most once per response and only when they land as *seen* rather than *surveilled*, fall back gracefully when profile or narrative is empty, no diagnosis.
- `_fmt_narrative()` formatter — emits a `## Recent narrative` section with structured trends followed by raw entries oldest-first. Returns `""` for the empty case so the prompt builder cleanly omits the whole section.
- `_build_morning_user_message`, `_build_evening_user_message`, `_build_weekly_user_message` each gained an optional `narrative` kwarg and slot the narrative block in *before* the briefing/review instructions, so the model has the full picture when it starts composing.
- `generate_digest` rewritten to assemble the system prompt as:

  ```
  [tone voice]
  ## How to coach
  [_COACH_METHOD_PROMPT]
  [profile fragment, if any]
  ```

  Tones describe *voice* (warm vs stoic vs drill-sergeant vs gentle-mentor); the method describes the moves shared across all tones. Profile is added last so it reads as concrete context, not as a rule.

- `generate_digest`'s public signature is unchanged — the existing `run_scheduled_digests` call site and `/ai/coach/digest/generate` endpoint continue to work without modification.

What this gives the user: the coach now reads (1) who they are, (2) how they've been talking about their experience lately, and (3) what they actually did — and writes from the gap between those three streams. The CBT moves are explicit in the method prompt; tones supply the register.

Empirical tuning is still ahead — Brandon should run digests against real data over the next 1-2 weeks and iterate on prompt phrasing if the moves feel off. The lever is `_COACH_METHOD_PROMPT` in `coach_service.py`.

Out of scope for Phase 3: chatbot CBT moves (chatbot already benefits from the profile via the existing `_build_system_prompt`; deeper CBT in chat is a possible Phase 4). Dashboard widget for visualizing the narrative trends — defer to a possible "emotional weather" widget.

### Phase 4 — Versioning + scheduled refresh + decay ✅

**Implementation:**
- Migration **0034** creates `user_profile_versions` (id, user_id, content_md, source, created_at). Append-only history; index on (user_id, created_at) for the version-listing query.
- New `_apply_profile_update(db, memory, new_content_md, *, source)` helper in `profile_service.py` is the single write path for memory_text. Every write — bootstrap, incremental proposer, `update_profile` tool, direct `PATCH /ai/profile`, scheduled refresh — flows through this helper. It snapshots the PREVIOUS content into `user_profile_versions` before overwriting, then trims rows beyond `PROFILE_VERSION_RETENTION` (50) for that user.
- New `run_scheduled_profile_refresh()` and `run_scheduled_profile_refresh_all()`. The refresh has *two jobs*: integrate durable patterns from the last 4 weeks of activity (notes + recent chat user messages) AND decay stale content from the current profile (anything that hasn't recurred recently, references resolved past situations, reads as fixed-trait, or contradicts recent activity). The proposer prompt is biased hard toward `SKIP` — a profile that's currently accurate is the correct weekly outcome, not a failure.
- APScheduler weekly job: Sunday 03:00 (`profile_scheduled_refresh`). Iterates every user whose `memory_text` is non-empty, resolves their AI provider, runs the refresh, logs aggregate counts. Wraps each per-user call in its own try/except so one bad user never kills the batch.
- New endpoint `GET /ai/profile/versions?limit=N` returns newest-first history. Debug surface only — no frontend UI.

**What earlier phases changed in Phase 4 (small refactors):**
- `update_profile` chat tool now goes through `_apply_profile_update`.
- Bootstrap and incremental proposers now go through `_apply_profile_update`.
- Direct `PATCH /ai/profile` (still backend-only, no UI) goes through `_apply_profile_update` with source=`direct_edit`.

**`ProfileUpdateSource` literal expanded** from `bootstrap | incremental | manual` to `bootstrap | incremental | manual | scheduled | direct_edit`. `PROFILE_UPDATE_SOURCES` constant guards against typos at the boundary.

**What this gives the user:** the profile stops being a write-only blob that grows monotonically. Over weeks of use, stale focuses get pruned, completed life-situations get retired, and stable new patterns get integrated — without anyone ever clicking anything. The audit trail (`user_profile_versions` + `user_profile_updates`) means Brandon can always see why the profile changed, and can roll back via `PATCH /ai/profile` if the AI ever does something off.

**Out of scope for Phase 4 (intentionally deferred):**
- UI rollback button. The version-listing endpoint is enough for debug; if rollback becomes a frequent operation we can add a UI.
- Per-section pinning. Without a user-facing profile UI it doesn't make sense yet; if the journaling tool surfaces sections to the user we can revisit.
- Chatbot-driven profile updates beyond the existing `update_profile` tool (e.g. conversational confirmation flows). The tool covers the high-value case.

---

## Out of scope

- A dedicated mood-tracking surface separate from journaling. The narrative signals serve this purpose without adding another input the user must remember.
- A values inventory questionnaire. The profile's "Values & non-negotiables" section is populated by the bootstrap pass from existing writing; explicit questionnaire is a fallback only for users with no existing data.
- Per-household coach style (e.g. a coach for shared family goals). Out of scope; the coach is per-user by design.
- Voice journaling / transcription pipeline. The text-based journal collection works first; voice can be added later as another input into the same collection.

---

## Tracking

Phase entries are tracked in `feature_list.json` under category `AI Coach`:

- `coach-001` — Phase 1: User profile + bootstrap pass
- `coach-002` — Phase 2: Journal signal extraction
- `coach-003` — Phase 3: CBT-aware coach prompt rewrite

Per `CLAUDE.md`, mark `passes: true` only after manual end-to-end verification.
