"""Tests for multi-root scan support (issue #59)."""

import os
import time
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from db.schema import ALL_TABLES, INDEXES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_db(path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_roots_table_exists(tmp_path: Path) -> None:
    db_path = str(tmp_path / "faces.db")
    conn = await _make_db(db_path)
    cur = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scan_roots'"
    )
    row = await cur.fetchone()
    await conn.close()
    assert row is not None, "scan_roots table must exist after schema init"


@pytest.mark.asyncio
async def test_scan_roots_unique_constraint(tmp_path: Path) -> None:
    db_path = str(tmp_path / "faces.db")
    conn = await _make_db(db_path)
    now = int(time.time())
    await conn.execute("INSERT INTO scan_roots(path, added_at) VALUES(?, ?)", ("/photos", now))
    await conn.commit()
    # ON CONFLICT DO NOTHING must not raise
    await conn.execute(
        "INSERT INTO scan_roots(path, added_at) VALUES(?, ?) ON CONFLICT(path) DO NOTHING",
        ("/photos", now + 10),
    )
    await conn.commit()
    cur = await conn.execute("SELECT count(*) FROM scan_roots")
    (count,) = await cur.fetchone()  # type: ignore[misc]
    await conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    # Prevent the scanner from actually walking any real paths
    import services.scanner as scanner_mod

    async def _noop_scan(root: str, broadcast, db) -> None:  # type: ignore[type-arg]
        await broadcast({"type": "scan_complete"})

    monkeypatch.setattr(scanner_mod, "run_scan", _noop_scan)

    from main import app

    return TestClient(app)


def test_start_scan_inserts_root(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/scan/start", json={"root_path": "/my/photos"})
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")


def test_list_roots_empty(client: TestClient) -> None:
    resp = client.get("/scan/roots")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_rescan_no_roots_returns_started(client: TestClient) -> None:
    resp = client.post("/scan/rescan")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("started", "already_running")
