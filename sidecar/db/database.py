"""Async database connection using aiosqlite.

WAL mode and foreign-key enforcement are set on every new connection so they
survive across reconnects. Schema DDL and migrations are applied once per
database path per process (#113) — every API request opens a connection, and
re-running the full DDL set plus try/except ALTERs on each one was measurable
overhead and hid real migration failures.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from db.schema import ALL_MIGRATIONS, ALL_TABLES, INDEXES

logger = logging.getLogger(__name__)

# DB paths whose schema+migrations have been applied this process. Keyed by
# path (not a bool) because tests point FACES_H_DATA_DIR at fresh tmp dirs.
_initialized_paths: set[str] = set()


def _db_path() -> str:
    """Resolve the database file path from the runtime environment."""
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    return os.path.join(data_dir, "faces.db")


def _is_duplicate_column_error(exc: Exception) -> bool:
    return "duplicate column" in str(exc).lower()


async def _apply_schema(conn: aiosqlite.Connection) -> None:
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    # A followup (e.g. a data backfill) runs exactly once: only on the
    # connection whose ALTER actually added the column. "Duplicate column"
    # means already applied and is expected; anything else is a real
    # migration failure and must be visible, not swallowed (#113).
    for alter_stmt, followup_stmt in ALL_MIGRATIONS:
        try:
            await conn.execute(alter_stmt)
        except Exception as exc:
            if not _is_duplicate_column_error(exc):
                logger.error("migration failed: %s — %s", alter_stmt, exc)
            continue
        if followup_stmt is not None:
            await conn.execute(followup_stmt)
    # Indexes AFTER migrations: an index on a migrated-in column (e.g.
    # photos.missing, #105) would otherwise fail on a pre-migration database.
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Yield an open, configured aiosqlite connection.

    PRAGMAs are per-connection; schema DDL + migrations run only for the
    first connection to each database path in this process.
    """
    path = _db_path()
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        if path not in _initialized_paths:
            await _apply_schema(conn)
            _initialized_paths.add(path)
        yield conn
