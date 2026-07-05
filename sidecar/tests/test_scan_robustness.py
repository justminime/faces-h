"""Tests for the #113 robustness fixes: start race, aggregate status, ETA, DDL."""

import os
import time
from pathlib import Path
from typing import Any

import pytest

from db.schema import ALL_TABLES, INDEXES
from services.scanner import (
    ScanStatus,
    begin_scan,
    end_scan,
    get_status,
    reset_status,
    run_scan,
)


async def _open_db(path: str) -> Any:
    import aiosqlite

    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


async def _noop_broadcast(_msg: dict[str, Any]) -> None:
    return None


def test_begin_scan_claims_running_synchronously() -> None:
    """The /scan/start guard depends on running being set before the scan
    task ever runs — two rapid requests must not both pass the check."""
    reset_status()
    assert get_status().running is False
    begin_scan("/some/root")
    assert get_status().running is True, "running must be claimed synchronously"
    assert get_status().root_path == "/some/root"
    end_scan()
    assert get_status().running is False


def test_eta_counts_skipped_files_in_rate() -> None:
    """Incremental rescans are dominated by skips; a scanned-only rate
    inflated the ETA by orders of magnitude."""
    s = ScanStatus(
        running=True,
        total=10_000,
        scanned=10,
        skipped=4_990,
        start_time=time.monotonic() - 10.0,  # 5000 processed in 10 s
    )
    eta = s.eta_seconds()
    # 5000 remaining at ~500 files/s ≈ 10 s. The old math (10 scanned in 10 s
    # → 1 file/s) would report ~5000 s.
    assert 5 <= eta <= 30, f"ETA {eta}s not in the realistic range"


@pytest.mark.asyncio
async def test_rescan_accumulates_totals_across_roots(tmp_path: Path) -> None:
    """With preset=True, run_scan keeps prior totals so a multi-root rescan
    reports one coherent aggregate, and stays 'running' between roots."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    jpeg = bytes.fromhex("ffd8ffdb004300ffffffffffffffffffffffffffffffffffffffffffff"
                         "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
    (root_a / "one.jpg").write_bytes(jpeg)
    (root_b / "two.jpg").write_bytes(jpeg)
    (root_b / "three.jpg").write_bytes(jpeg)

    db = await _open_db(str(tmp_path / "t.db"))
    try:
        begin_scan("(rescan)")
        await run_scan(str(root_a), _noop_broadcast, db, preset=True)
        assert get_status().running is True, "must stay running between roots"
        assert get_status().total == 1
        await run_scan(str(root_b), _noop_broadcast, db, preset=True)
        assert get_status().total == 3, "totals must aggregate across roots"
        end_scan()
        assert get_status().running is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_schema_applied_once_per_path(tmp_path: Path) -> None:
    """get_db runs DDL/migrations only for the first connection per DB path."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    import db.database as database

    database._initialized_paths.discard(database._db_path())
    async with database.get_db() as conn:
        row = await (await conn.execute("SELECT COUNT(*) AS c FROM photos")).fetchone()
        assert row is not None
    assert database._db_path() in database._initialized_paths
    # Second connection skips DDL but still works.
    async with database.get_db() as conn:
        row = await (await conn.execute("SELECT COUNT(*) AS c FROM photos")).fetchone()
        assert row is not None
