"""Async database connection using aiosqlite.

WAL mode and foreign-key enforcement are set on every new connection so they
survive across reconnects. Schema DDL is applied on first connect — idempotent
because every statement uses CREATE … IF NOT EXISTS.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from db.schema import ALL_MIGRATIONS, ALL_TABLES, INDEXES

logger = logging.getLogger(__name__)


def _db_path() -> str:
    """Resolve the database file path from the runtime environment."""
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    return os.path.join(data_dir, "faces.db")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Yield an open, configured aiosqlite connection.

    Applies schema DDL and PRAGMAs on each connection; keeps them cheap
    because CREATE IF NOT EXISTS is a no-op after the first run.
    """
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        for ddl in ALL_TABLES:
            await conn.execute(ddl)
        for idx in INDEXES:
            await conn.execute(idx)
        # Best-effort column migrations — silently ignored if already applied.
        for migration in ALL_MIGRATIONS:
            try:
                await conn.execute(migration)
            except Exception:
                pass
        await conn.commit()
        yield conn
