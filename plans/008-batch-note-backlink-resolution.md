# Plan 008: Batch note backlink resolution to remove the per-wikilink N+1

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/domains/notes/service.py`
> If it changed since this plan was written, compare the "Current state" excerpt
> against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (one query replaces a loop of identical queries; result is identical)
- **Depends on**: plans/002-verification-baseline.md (for the `db_session` fixture)
- **Category**: perf
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

`_resolve_backlinks` runs on every note create/update. For a note containing K
`[[wikilinks]]`, it issues **K separate** case-insensitive title lookups — one DB
round-trip per wikilink. Heavily-linked notes get slower to save in linear proportion to
their link count. `.claude/rules/performance.md` mandates batch-loading: "Before writing
any query inside a loop, stop and write a batch query instead." This replaces the loop
with a single `IN` query, matching the canonical batch pattern used in `habits/service.py`.

## Current state

File: `api/src/life_dashboard/domains/notes/service.py`, `_resolve_backlinks` (lines 72–116):

```python
    titles = _extract_wikilink_titles(source.content_md)
    if not titles:
        return

    # Resolve titles → note IDs (case-insensitive ILIKE per title)
    title_to_note: dict[str, Note] = {}
    for title in titles:                                            # ← N queries
        result = await db.execute(
            select(Note).where(
                Note.household_id == household_id,
                Note.id != source.id,
                Note.archived_at.is_(None),
                func.lower(Note.title) == title.lower(),
            )
        )
        note = result.scalars().first()
        if note:
            title_to_note[title.lower()] = note

    # Insert resolved backlinks
    for title in titles:
        target = title_to_note.get(title.lower())
        if target:
            db.add(NoteBacklink(
                source_note_id=source.id,
                target_note_id=target.id,
                alias=title,
            ))
```

The lookup filters are: same household, not the source note itself, not archived, and a
case-insensitive title match. The insert loop keys into `title_to_note` by
`title.lower()`. Both the filters and the `title.lower()` keying must be preserved
exactly.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_note_backlinks.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |
| Confirm loop removed | `grep -n "for title in titles" api/src/life_dashboard/domains/notes/service.py` | one match (the insert loop only) |

## Scope

**In scope**:
- `api/src/life_dashboard/domains/notes/service.py` (edit the resolution loop in `_resolve_backlinks`)
- `api/tests/test_note_backlinks.py` (create)

**Out of scope**:
- `_extract_wikilink_titles` — unchanged.
- The `delete(NoteBacklink)` cleanup and the insert loop — the insert loop stays (only the
  *resolution* loop is replaced).
- Any other function in `notes/service.py`.

## Git workflow

- Branch: `advisor/008-batch-note-backlink-resolution`
- Commit style: e.g. `perf(notes): batch backlink title resolution into one query`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Replace the per-title loop with a single `IN` query

Replace the resolution `for title in titles:` block (NOT the insert loop) with:

```python
    # Resolve all titles in one query, then map case-insensitively.
    lowered = [t.lower() for t in titles]
    result = await db.execute(
        select(Note).where(
            Note.household_id == household_id,
            Note.id != source.id,
            Note.archived_at.is_(None),
            func.lower(Note.title).in_(lowered),
        )
    )
    title_to_note: dict[str, Note] = {}
    for note in result.scalars().all():
        title_to_note[note.title.lower()] = note
```

Behavior notes to preserve:
- If two different notes share a title (case-insensitively), the old code kept the
  *first* match per title; the new code keeps the *last* one iterated. This is a
  pre-existing ambiguity (duplicate titles). If you want to preserve "first wins",
  use `title_to_note.setdefault(note.title.lower(), note)` instead of assignment. Prefer
  `setdefault` to stay closest to the old first-match semantics.
- The insert loop below is unchanged and still keys by `title.lower()`.

**Verify**: `grep -n "func.lower(Note.title).in_(" api/src/life_dashboard/domains/notes/service.py` → one match.

### Step 2: Add a correctness test

Create `api/tests/test_note_backlinks.py`. Read `notes/models.py` (`Note`, `NoteBacklink`)
and `notes/service.py` for the create/update entrypoint (likely `create_note`/`update_note`),
then write a test that a note with two wikilinks resolves both. Target shape:

```python
from sqlalchemy import select

from life_dashboard.auth.models import Household
from life_dashboard.domains.notes.models import Note, NoteBacklink
from life_dashboard.domains.notes.service import _resolve_backlinks


async def test_backlinks_resolve_all_wikilinks(db_session):
    hh = Household(name="H")
    db_session.add(hh); await db_session.flush()

    target_a = Note(household_id=hh.id, title="Alpha", content_md="")
    target_b = Note(household_id=hh.id, title="Beta", content_md="")
    db_session.add_all([target_a, target_b]); await db_session.flush()

    source = Note(household_id=hh.id, title="Source", content_md="See [[Alpha]] and [[beta]].")
    db_session.add(source); await db_session.flush()

    await _resolve_backlinks(db_session, source, hh.id)
    await db_session.flush()

    links = (await db_session.execute(
        select(NoteBacklink).where(NoteBacklink.source_note_id == source.id)
    )).scalars().all()
    target_ids = {l.target_note_id for l in links}
    assert target_a.id in target_ids   # [[Alpha]] resolved
    assert target_b.id in target_ids   # [[beta]] resolved case-insensitively
    assert len(links) == 2
```

Adaptation notes:
- Confirm the `Note` required columns (e.g. a `slug` may be required — read `notes/models.py`
  and supply it if so).
- Confirm the wikilink syntax `_extract_wikilink_titles` expects (double brackets per the
  code) — adjust `content_md` if the parser expects a different form.
- If `NoteBacklink` has a different column name than `alias`, that doesn't matter for this
  test (it only reads `source_note_id`/`target_note_id`).

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_note_backlinks.py -v` → pass.

## Test plan

- `test_backlinks_resolve_all_wikilinks` — proves the batched query resolves multiple
  wikilinks (including case-insensitively), i.e. the refactor preserved correctness.
- The query-count reduction itself is verified by code review (one query vs. K).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "func.lower(Note.title).in_(" api/src/life_dashboard/domains/notes/service.py` → one match
- [ ] `grep -c "await db.execute" api/src/life_dashboard/domains/notes/service.py` did not increase for this function (the resolution is now a single execute)
- [ ] `cd api && .venv/bin/python -m pytest tests/test_note_backlinks.py` → pass
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_resolve_backlinks` no longer matches the "Current state" excerpt (drift).
- The `Note` model requires columns you can't determine — report which, don't guess repeatedly.
- `_extract_wikilink_titles` returns an unexpected shape for the test input — inspect it and
  adjust the test's `content_md` to a form it parses; report if unclear.

## Maintenance notes

- Same batch pattern applies if backlink resolution ever needs to also match aliases or
  slugs — extend the single `IN` query, never reintroduce a per-title loop.
- Reviewer should confirm the `setdefault` (first-match-wins) choice matches the intended
  duplicate-title behavior.
- Follow-up deferred: the audit noted `notes/service.py:148` (a `Collection.kind` read-back)
  as a low-confidence unscoped-read; not addressed here.
