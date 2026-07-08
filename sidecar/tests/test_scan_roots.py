"""Tests for multi-root scan support (issue #59) and scan-root management
(issue #186)."""

import asyncio
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


def _seed_scan_root(db_path: str, path: str) -> int:
    """Insert a scan_roots row directly, bypassing /scan/start's background
    task (which the TestClient doesn't reliably let finish before the
    response returns — see test_start_scan_inserts_root above, which only
    checks the response status for that reason). Returns the new row id."""

    async def _run() -> int:
        conn = await _make_db(db_path)
        try:
            now = int(time.time())
            cur = await conn.execute(
                "INSERT INTO scan_roots(path, added_at) VALUES(?, ?)", (path, now)
            )
            await conn.commit()
            assert cur.lastrowid is not None
            return cur.lastrowid
        finally:
            await conn.close()

    return asyncio.run(_run())


def test_list_roots_returns_configured_root(client: TestClient, tmp_path: Path) -> None:
    db_path = str(tmp_path / "faces.db")
    _seed_scan_root(db_path, "/my/photos")

    resp = client.get("/scan/roots")
    assert resp.status_code == 200
    body = resp.json()
    assert any(r["path"] == "/my/photos" for r in body)
    row = next(r for r in body if r["path"] == "/my/photos")
    assert "id" in row
    assert "is_network" in row
    assert "last_seen_at" in row
    assert "reachable" in row


def test_delete_root_removes_only_scan_roots_row(
    client: TestClient, tmp_path: Path
) -> None:
    """Removing a scan root (#186) must not touch photos/faces/people —
    it only stops future scanning of that folder."""
    db_path = str(tmp_path / "faces.db")
    root_id = _seed_scan_root(db_path, "/my/photos")

    # Seed indexed data as if a prior scan of this root had already run —
    # this data must survive removing the root row.
    async def _seed_indexed_data() -> None:
        conn = await aiosqlite.connect(db_path)
        try:
            now = int(time.time())
            await conn.execute(
                "INSERT INTO photos(path, mtime, scanned_at) VALUES(?, ?, ?)",
                ("/my/photos/pic.jpg", now, now),
            )
            await conn.execute(
                "INSERT INTO people(name, created_at) VALUES(?, ?)",
                ("Alice", now),
            )
            await conn.execute(
                "INSERT INTO faces(photo_id, detection_conf, person_id, assign_status) "
                "VALUES(1, 0.99, 1, 'assigned')"
            )
            await conn.commit()
        finally:
            await conn.close()

    asyncio.run(_seed_indexed_data())

    async def _counts() -> tuple[int, int, int]:
        conn = await aiosqlite.connect(db_path)
        try:
            photos_row = await (await conn.execute("SELECT count(*) FROM photos")).fetchone()
            faces_row = await (await conn.execute("SELECT count(*) FROM faces")).fetchone()
            people_row = await (await conn.execute("SELECT count(*) FROM people")).fetchone()
            assert photos_row is not None and faces_row is not None and people_row is not None
            return photos_row[0], faces_row[0], people_row[0]
        finally:
            await conn.close()

    before = asyncio.run(_counts())

    resp = client.delete(f"/scan/roots/{root_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"

    after = asyncio.run(_counts())
    assert after == before, "removing a scan root must not change photo/face/person counts"

    roots_after = client.get("/scan/roots").json()
    assert not any(r["id"] == root_id for r in roots_after)


def test_delete_root_not_found_returns_status(client: TestClient) -> None:
    resp = client.delete("/scan/roots/999999")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"
