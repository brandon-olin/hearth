from sqlalchemy import inspect


async def test_core_tables_are_created(db_session):
    def _tables(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    conn = await db_session.connection()
    names = await conn.run_sync(_tables)
    expected_tables = (
        "households",
        "users",
        "todos",
        "goals",
        "budget_categories",
        "budget_profiles",
    )
    for expected in expected_tables:
        assert expected in names, f"table {expected!r} missing from SQLite schema"
