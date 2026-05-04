import json
from datetime import datetime, timezone

import asyncpg


async def upsert_page(conn: asyncpg.Connection, record: dict) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO logseq_index
            (id, graph, page_name, file_path, content, properties, tags,
             block_count, content_hash, last_indexed_at, created_at, updated_at)
        VALUES
            (gen_random_uuid(), $1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $9, $9)
        ON CONFLICT (graph, page_name) DO UPDATE SET
            file_path       = EXCLUDED.file_path,
            content         = EXCLUDED.content,
            properties      = EXCLUDED.properties,
            tags            = EXCLUDED.tags,
            block_count     = EXCLUDED.block_count,
            content_hash    = EXCLUDED.content_hash,
            last_indexed_at = EXCLUDED.last_indexed_at,
            updated_at      = EXCLUDED.updated_at
        WHERE logseq_index.content_hash IS DISTINCT FROM EXCLUDED.content_hash
        """,
        record["graph"],
        record["page_name"],
        record["file_path"],
        record["content"],
        json.dumps(record["properties"]),
        record["tags"],
        record["block_count"],
        record["content_hash"],
        now,
    )


async def delete_page(conn: asyncpg.Connection, graph: str, file_path: str) -> None:
    await conn.execute(
        "DELETE FROM logseq_index WHERE graph = $1 AND file_path = $2",
        graph,
        file_path,
    )


async def reconcile_graph(
    conn: asyncpg.Connection, graph: str, current_file_paths: list[str]
) -> None:
    """Remove index rows whose source files no longer exist on disk."""
    if not current_file_paths:
        await conn.execute("DELETE FROM logseq_index WHERE graph = $1", graph)
        return
    await conn.execute(
        "DELETE FROM logseq_index WHERE graph = $1 AND file_path != ALL($2::text[])",
        graph,
        current_file_paths,
    )
