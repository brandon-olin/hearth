"""SQLite schema evolution — ADR-014 (plans/014-sqlite-schema-evolution.md).

SQLite installs used to skip Alembic entirely; schema came from create_all()
plus a patcher that silently dropped UNIQUE constraints and never ran data
backfills.  These tests pin the replacement: fresh databases are stamped at
head, and subsequent migrations actually apply — constraints and backfills
included.

The migrations exercised here are generated into a temp script directory at
run time, deliberately NOT committed to api/migrations/versions.  They import
the real ``migrations/env.py``, so batch mode and the removed SQLite
early-return are what is under test.
"""

import shutil
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from life_dashboard.core.database import _migrations_dir, _stamp_head_if_unversioned

API_DIR = Path(__file__).resolve().parents[1]

BASE_REVISION = '''
"""base — a table to evolve"""
from alembic import op
import sqlalchemy as sa

revision = "t001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("widgets")
'''

UNIQUE_COLUMN_REVISION = '''
"""add a column WITH a unique constraint"""
from alembic import op
import sqlalchemy as sa

revision = "t002"
down_revision = "t001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("widgets") as batch_op:
        batch_op.add_column(sa.Column("code", sa.String(), nullable=True))
        batch_op.create_unique_constraint("uq_widgets_code", ["code"])


def downgrade() -> None:
    with op.batch_alter_table("widgets") as batch_op:
        batch_op.drop_constraint("uq_widgets_code", type_="unique")
        batch_op.drop_column("code")
'''

BACKFILL_REVISION = '''
"""data backfill via op.execute"""
from alembic import op

revision = "t003"
down_revision = "t002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE widgets SET kind = 'journal' WHERE kind IS NULL")


def downgrade() -> None:
    pass
'''


def _write_script_dir(tmp_path: Path) -> Path:
    """Build a throwaway Alembic script directory using the real env.py."""
    script_dir = tmp_path / "migrations"
    (script_dir / "versions").mkdir(parents=True)

    real = _migrations_dir()
    shutil.copy(real / "env.py", script_dir / "env.py")
    shutil.copy(real / "script.py.mako", script_dir / "script.py.mako")

    for name, body in (
        ("t001_base.py", BASE_REVISION),
        ("t002_unique.py", UNIQUE_COLUMN_REVISION),
        ("t003_backfill.py", BACKFILL_REVISION),
    ):
        (script_dir / "versions" / name).write_text(body)

    (tmp_path / "alembic.ini").write_text(
        textwrap.dedent(
            f"""
            [alembic]
            script_location = {script_dir}
            prepend_sys_path = {API_DIR / "src"}

            [loggers]
            keys = root

            [handlers]
            keys = console

            [formatters]
            keys = generic

            [logger_root]
            level = WARN
            handlers = console

            [handler_console]
            class = StreamHandler
            args = (sys.stderr,)
            formatter = generic

            [formatter_generic]
            format = %(levelname)-5.5s [%(name)s] %(message)s
            """
        ).lstrip()
    )
    return tmp_path / "alembic.ini"


def _alembic(ini: Path, db_path: Path, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        cwd=API_DIR,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "JWT_SECRET_KEY": "test-secret-key-not-for-production",
            "ENVIRONMENT": "test",
        },
    )
    assert result.returncode == 0, f"alembic {args} failed:\n{result.stdout}\n{result.stderr}"


@pytest.fixture
def sqlite_db(tmp_path: Path) -> tuple[Path, Path]:
    """A temp SQLite DB plus the alembic.ini driving the temp migration chain."""
    return _write_script_dir(tmp_path), tmp_path / "evolve.db"


def test_fresh_sqlite_db_is_stamped_at_head(tmp_path: Path) -> None:
    """create_all() on a fresh SQLite DB records the current head."""
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        _stamp_head_if_unversioned(conn)

    expected = ScriptDirectory(str(_migrations_dir())).get_current_head()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == expected


def test_stamp_does_not_clobber_an_existing_version(tmp_path: Path) -> None:
    """A DB already carrying a revision is left alone — upgrades stay forward-only."""
    db_path = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0001')"))

    with engine.begin() as conn:
        _stamp_head_if_unversioned(conn)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"


def test_unique_constraint_lands_on_sqlite(sqlite_db: tuple[Path, Path]) -> None:
    """A migration adding a column WITH a UNIQUE constraint applies on SQLite.

    The old _patch_sqlite_schema() skipped these entirely, letting duplicate
    rows accumulate that Postgres would reject.
    """
    ini, db_path = sqlite_db
    _alembic(ini, db_path, "upgrade", "head")

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(widgets)")}
        assert "code" in columns

        conn.execute("INSERT INTO widgets (name, code) VALUES ('a', 'dup')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO widgets (name, code) VALUES ('b', 'dup')")
    finally:
        conn.close()


def test_data_backfill_runs_on_sqlite(sqlite_db: tuple[Path, Path]) -> None:
    """op.execute UPDATE backfills actually touch rows — the collection.kind failure."""
    ini, db_path = sqlite_db
    _alembic(ini, db_path, "upgrade", "t001")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO widgets (name, kind) VALUES ('pre-existing', NULL)")
        conn.execute("INSERT INTO widgets (name, kind) VALUES ('already-set', 'recipe')")
        conn.commit()
    finally:
        conn.close()

    _alembic(ini, db_path, "upgrade", "head")

    conn = sqlite3.connect(db_path)
    try:
        rows = dict(conn.execute("SELECT name, kind FROM widgets"))
        assert rows["pre-existing"] == "journal"
        assert rows["already-set"] == "recipe"
    finally:
        conn.close()
