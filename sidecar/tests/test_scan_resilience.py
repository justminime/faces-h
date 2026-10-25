"""Tests for #203: a scan survives DB errors, reports when it gives up, and
resumes after a restart."""

import asyncio
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import aiosqlite
import numpy as np
import pytest
from PIL import Image

import api.scan as scan_api
from db.schema import ALL_TABLES, INDEXES
from ml.base import FaceResult
from services import scanner
from services.scanner import ScanAborted, get_status, reset_status, run_scan


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_status()
    # Retries without the real back-off.
    monkeypatch.setattr(scanner, "_DB_RETRY_DELAYS", (0.0, 0.0, 0.0))


async def _open_db(path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


def _write_jpegs(folder: Path, n: int) -> None:
    for i in range(n):
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), color=(i * 40 % 255, 80, 200)).save(buf, format="JPEG")
        (folder / f"p{i}.jpg").write_bytes(buf.getvalue())


class _OneFaceRecognizer:
    def detect_and_embed(self, path: str) -> list[FaceResult]:
        emb = np.ones(512, dtype=np.float32) / np.sqrt(512)
        return [FaceResult(bbox=(0, 0, 4, 4), embedding=emb, detection_confidence=0.99)]


def _install_recognizer(monkeypatch: pytest.MonkeyPatch) -> None:
    import ml.insightface_recognizer as ir

    monkeypatch.setattr(ir, "InsightFaceRecognizer", lambda data_dir: _OneFaceRecognizer())


async def _noop_broadcast(_msg: dict[str, Any]) -> None:
    return None


def _fail_extract(
    monkeypatch: pytest.MonkeyPatch, times: int, exc: Exception
) -> list[str]:
    """Make _extract_faces raise `exc` for its first `times` calls."""
    real = scanner._extract_faces
    calls: list[str] = []

    async def _flaky(path: str, *args: Any, **kwargs: Any) -> None:
        calls.append(path)
        if len(calls) <= times:
            raise exc
        await real(path, *args, **kwargs)

    monkeypatch.setattr(scanner, "_extract_faces", _flaky)
    return calls


async def _faces_extracted(db: aiosqlite.Connection) -> list[int]:
    cur = await db.execute("SELECT faces_extracted FROM photos ORDER BY path")
    return [int(r["faces_extracted"]) for r in await cur.fetchall()]


# ── Scanner ──────────────────────────────────────────────────────────────────


async def test_transient_db_error_is_retried_and_scan_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    _write_jpegs(photos, 3)
    _install_recognizer(monkeypatch)
    calls = _fail_extract(monkeypatch, 2, sqlite3.OperationalError("disk I/O error"))

    db = await _open_db(str(tmp_path / "t.db"))
    try:
        await run_scan(str(photos), _noop_broadcast, db)
        # The failing photo was retried until its faces committed.
        assert await _faces_extracted(db) == [1, 1, 1]
        assert len(calls) == 5  # 2 failures + 3 successes
        assert get_status().error_count == 0
        cur = await db.execute("SELECT COUNT(*) FROM faces")
        row = await cur.fetchone()
        assert row is not None and row[0] == 3
    finally:
        await db.close()


async def test_persistent_db_error_aborts_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    _write_jpegs(photos, 3)
    _install_recognizer(monkeypatch)
    calls = _fail_extract(monkeypatch, 1_000, sqlite3.OperationalError("disk I/O error"))

    db = await _open_db(str(tmp_path / "t.db"))
    try:
        with pytest.raises(ScanAborted, match="disk I/O error"):
            await run_scan(str(photos), _noop_broadcast, db)
        assert len(calls) == len(scanner._DB_RETRY_DELAYS) + 1
        # Nothing half-written: the photo stays unindexed for the next scan.
        assert 0 in await _faces_extracted(db)
    finally:
        await db.close()


async def test_other_error_skips_only_that_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    _write_jpegs(photos, 3)
    _install_recognizer(monkeypatch)
    _fail_extract(monkeypatch, 1, ValueError("bad embedding"))

    db = await _open_db(str(tmp_path / "t.db"))
    try:
        await run_scan(str(photos), _noop_broadcast, db)
        assert get_status().error_count == 1
        assert sorted(await _faces_extracted(db)) == [0, 1, 1]
    finally:
        await db.close()


# ── API: failure report and resume marker ────────────────────────────────────


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FACES_H_DATA_DIR", str(tmp_path))
    return tmp_path


def _capture_broadcasts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def _broadcast(msg: dict[str, Any]) -> None:
        sent.append(msg)

    monkeypatch.setattr(scan_api._manager, "broadcast", _broadcast)
    return sent


async def _wait_until_idle() -> None:
    for _ in range(200):
        if not get_status().running:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("scan task never finished")


async def _marker(data_dir: Path) -> dict[str, str] | None:
    async with aiosqlite.connect(str(data_dir / "faces.db")) as db:
        cur = await db.execute(
            "SELECT value FROM scan_state WHERE key = 'interrupted_scan'"
        )
        row = await cur.fetchone()
    return json.loads(row[0]) if row else None


async def test_finished_scan_leaves_no_resume_marker(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_broadcasts(monkeypatch)
    seen: list[dict[str, str] | None] = []

    async def _scan(root: str, broadcast: Any, db: Any, preset: bool = False) -> None:
        seen.append(await _marker(data_dir))

    monkeypatch.setattr(scan_api, "run_scan", _scan)
    await scan_api.start_scan(scan_api.StartScanRequest(root_path="/photos"))
    await _wait_until_idle()

    assert seen == [{"kind": "start", "root": "/photos"}]  # set while running
    assert await _marker(data_dir) is None  # cleared on success


async def test_failed_scan_reports_and_keeps_resume_marker(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture_broadcasts(monkeypatch)

    async def _scan(root: str, broadcast: Any, db: Any, preset: bool = False) -> None:
        raise ScanAborted("database error: disk I/O error")

    monkeypatch.setattr(scan_api, "run_scan", _scan)
    await scan_api.start_scan(scan_api.StartScanRequest(root_path="/photos"))
    await _wait_until_idle()

    assert {"type": "scan_failed", "message": "database error: disk I/O error"} in sent
    assert get_status().error == "database error: disk I/O error"
    assert await _marker(data_dir) == {"kind": "start", "root": "/photos"}


async def test_resume_restarts_the_interrupted_scan(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_broadcasts(monkeypatch)
    roots: list[str] = []

    async def _fail(root: str, broadcast: Any, db: Any, preset: bool = False) -> None:
        raise ScanAborted("database error: disk I/O error")

    async def _ok(root: str, broadcast: Any, db: Any, preset: bool = False) -> None:
        roots.append(root)

    monkeypatch.setattr(scan_api, "run_scan", _fail)
    await scan_api.start_scan(scan_api.StartScanRequest(root_path="/photos"))
    await _wait_until_idle()

    reset_status()  # a fresh sidecar process
    monkeypatch.setattr(scan_api, "run_scan", _ok)
    assert await scan_api.resume_interrupted_scan() == "/photos"
    await _wait_until_idle()

    assert roots == ["/photos"]
    assert await _marker(data_dir) is None
    assert await scan_api.resume_interrupted_scan() is None  # nothing left


async def test_resume_drops_marker_for_a_removed_folder(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_broadcasts(monkeypatch)

    async def _fail(root: str, broadcast: Any, db: Any, preset: bool = False) -> None:
        raise ScanAborted("database error: disk I/O error")

    monkeypatch.setattr(scan_api, "run_scan", _fail)
    await scan_api.start_scan(scan_api.StartScanRequest(root_path="/photos"))
    await _wait_until_idle()
    async with aiosqlite.connect(str(data_dir / "faces.db")) as db:
        await db.execute("DELETE FROM scan_roots")
        await db.commit()

    reset_status()
    assert await scan_api.resume_interrupted_scan() is None
    assert await _marker(data_dir) is None
