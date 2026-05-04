"""Graph indexer service.

Runs a full scan of each Logseq graph on startup, then watches for file
changes and keeps logseq_index up to date in near-real-time.

Configuration (env vars):
  DATABASE_URL   — same as the API (postgresql+asyncpg://... format accepted)
  LOGSEQ_GRAPHS  — comma-separated list of  name:path  pairs, e.g.:
                   household:/data/logseq/household-graph,brandon-private:/data/logseq/brandon-private
  LOG_LEVEL      — optional, defaults to INFO
"""

import asyncio
import logging
import os
import signal
from pathlib import Path

import asyncpg
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from life_dashboard.indexer.db import delete_page, reconcile_graph, upsert_page
from life_dashboard.indexer.parser import parse_page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _parse_graphs_env() -> list[tuple[str, Path]]:
    raw = os.environ.get("LOGSEQ_GRAPHS", "").strip()
    if not raw:
        raise RuntimeError("LOGSEQ_GRAPHS env var is required (format: name:path,name:path)")
    graphs = []
    for entry in raw.split(","):
        name, _, path_str = entry.strip().partition(":")
        if name and path_str:
            graphs.append((name.strip(), Path(path_str.strip())))
    if not graphs:
        raise RuntimeError("LOGSEQ_GRAPHS contained no valid entries")
    return graphs


def _db_dsn() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL env var is required")
    # asyncpg uses postgresql:// not postgresql+asyncpg://
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# File event handler (watchdog → asyncio queue bridge)
# ---------------------------------------------------------------------------

class _GraphEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        graph: str,
        graph_root: Path,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
    ) -> None:
        self.graph = graph
        self.graph_root = graph_root
        self._loop = loop
        self._queue = queue

    def _put(self, event_type: str, path: str) -> None:
        asyncio.run_coroutine_threadsafe(
            self._queue.put((event_type, self.graph, self.graph_root, path)),
            self._loop,
        )

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._put("upsert", event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._put("upsert", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._put("delete", event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            if event.src_path.endswith(".md"):
                self._put("delete", event.src_path)
            if event.dest_path.endswith(".md"):
                self._put("upsert", event.dest_path)


# ---------------------------------------------------------------------------
# Async event processor
# ---------------------------------------------------------------------------

async def _process_events(conn: asyncpg.Connection, queue: asyncio.Queue) -> None:
    while True:
        event_type, graph, graph_root, path_str = await queue.get()
        try:
            if event_type == "upsert":
                record = parse_page(Path(path_str), graph_root, graph)
                if record:
                    await upsert_page(conn, record)
                    logger.info("indexed  %s :: %s", graph, record["page_name"])
            elif event_type == "delete":
                await delete_page(conn, graph, path_str)
                logger.info("removed  %s :: %s", graph, path_str)
        except Exception:
            logger.exception("error processing %s event for %s", event_type, path_str)
        finally:
            queue.task_done()


# ---------------------------------------------------------------------------
# Startup scan
# ---------------------------------------------------------------------------

async def _scan_graph(conn: asyncpg.Connection, graph: str, graph_root: Path) -> None:
    found: list[str] = []
    count = 0
    for subdir in ("pages", "journals"):
        dir_path = graph_root / subdir
        if not dir_path.exists():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            record = parse_page(md_file, graph_root, graph)
            if record:
                await upsert_page(conn, record)
                found.append(str(md_file))
                count += 1
    await reconcile_graph(conn, graph, found)
    logger.info("scan complete: %s — %d page(s) indexed", graph, count)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    graphs = _parse_graphs_env()
    conn = await asyncpg.connect(dsn=_db_dsn())
    logger.info("connected to database")

    for graph, graph_root in graphs:
        if not graph_root.exists():
            logger.warning("graph root does not exist, skipping: %s", graph_root)
            continue
        logger.info("scanning %s at %s", graph, graph_root)
        await _scan_graph(conn, graph, graph_root)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    observer = Observer()
    for graph, graph_root in graphs:
        if graph_root.exists():
            handler = _GraphEventHandler(graph, graph_root, loop, queue)
            observer.schedule(handler, str(graph_root), recursive=True)
    observer.start()
    logger.info("watching %d graph(s) for changes", len(graphs))

    stop = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGINT, stop.set)

    event_task = asyncio.create_task(_process_events(conn, queue))

    await stop.wait()
    logger.info("shutting down...")
    observer.stop()
    observer.join()
    event_task.cancel()
    await conn.close()
    logger.info("shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
