"""Correctness test for batched note-backlink resolution (plan 008).

`_resolve_backlinks` now resolves all [[wikilinks]] in a single IN query
instead of one query per link. This proves the refactor preserved behavior:
multiple wikilinks resolve, including case-insensitively.
"""

from sqlalchemy import select

from life_dashboard.auth.models import Household
from life_dashboard.domains.notes.models import Note, NoteBacklink
from life_dashboard.domains.notes.service import _resolve_backlinks


async def test_backlinks_resolve_all_wikilinks(db_session):
    hh = Household(name="H")
    db_session.add(hh)
    await db_session.flush()

    target_a = Note(household_id=hh.id, title="Alpha", content_md="")
    target_b = Note(household_id=hh.id, title="Beta", content_md="")
    db_session.add_all([target_a, target_b])
    await db_session.flush()

    source = Note(
        household_id=hh.id, title="Source", content_md="See [[Alpha]] and [[beta]]."
    )
    db_session.add(source)
    await db_session.flush()

    await _resolve_backlinks(db_session, source, hh.id)
    await db_session.flush()

    links = (
        await db_session.execute(
            select(NoteBacklink).where(NoteBacklink.source_note_id == source.id)
        )
    ).scalars().all()

    target_ids = {link.target_note_id for link in links}
    assert target_a.id in target_ids  # [[Alpha]] resolved
    assert target_b.id in target_ids  # [[beta]] resolved case-insensitively
    assert len(links) == 2


async def test_unresolved_wikilink_creates_no_backlink(db_session):
    """A [[wikilink]] with no matching note title produces no backlink row."""
    hh = Household(name="H")
    db_session.add(hh)
    await db_session.flush()

    source = Note(
        household_id=hh.id, title="Source", content_md="Points at [[Nonexistent]]."
    )
    db_session.add(source)
    await db_session.flush()

    await _resolve_backlinks(db_session, source, hh.id)
    await db_session.flush()

    links = (
        await db_session.execute(
            select(NoteBacklink).where(NoteBacklink.source_note_id == source.id)
        )
    ).scalars().all()
    assert links == []
