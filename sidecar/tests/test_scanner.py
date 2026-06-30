"""Tests for the file scanner service."""

import io
import time
from pathlib import Path
from typing import Any

import aiosqlite
import numpy as np
import pytest
from PIL import Image

from db.schema import ALL_TABLES, INDEXES
from ml.base import FaceResult
from services.clustering import ClusteringService
from services.scanner import _extract_faces, get_status, reset_status, run_scan


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_status() -> None:
    """Reset the global scan state before every test."""
    reset_status()


@pytest.fixture(autouse=True)
def _metadata_only_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force run_scan into metadata-only mode for these file-walking/DB tests.

    Otherwise, on a machine where insightface is installed, run_scan loads the
    recognizer — downloading the 300 MB buffalo_l model on every test. CI doesn't
    install insightface so it already runs metadata-only; this makes local runs
    match (and stay fast). Face-extraction itself is covered separately via
    _extract_faces with a fake recognizer.
    """
    import ml.insightface_recognizer as ir

    def _unavailable(*_a: object, **_k: object) -> None:
        raise RuntimeError("face model disabled in scanner file-walk tests")

    monkeypatch.setattr(ir, "InsightFaceRecognizer", _unavailable)


async def _open_db(path: str) -> aiosqlite.Connection:
    """Open a SQLite connection at path with the full schema applied."""
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row  # match production: scanner reads row["id"]
    await conn.execute("PRAGMA foreign_keys=ON")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(120, 80, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(200, 120, 80)).save(buf, format="PNG")
    return buf.getvalue()


def _tiff_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="TIFF")
    return buf.getvalue()


async def _noop_broadcast(msg: dict[str, Any]) -> None:
    pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finds_all_supported_image_types(tmp_path: Path) -> None:
    """Scanner records one entry per discovered image, for all validated types."""
    samples: dict[str, bytes] = {
        "photo.jpg": _jpeg_bytes(),
        "photo.jpeg": _jpeg_bytes(),
        "photo.png": _png_bytes(),
        "photo.tiff": _tiff_bytes(),
        "photo.tif": _tiff_bytes(),
    }
    for name, data in samples.items():
        (tmp_path / name).write_bytes(data)

    db = await _open_db(str(tmp_path / "test.db"))
    try:
        await run_scan(str(tmp_path), _noop_broadcast, db)
    finally:
        await db.close()

    s = get_status()
    assert s.scanned == len(samples)
    assert s.error_count == 0


@pytest.mark.asyncio
async def test_skips_corrupt_file_increments_error_count(tmp_path: Path) -> None:
    """A corrupt image is skipped and counted in error_count; scan continues."""
    (tmp_path / "good.jpg").write_bytes(_jpeg_bytes())
    (tmp_path / "corrupt.jpg").write_bytes(b"THIS IS NOT A JPEG")

    db = await _open_db(str(tmp_path / "test.db"))
    try:
        await run_scan(str(tmp_path), _noop_broadcast, db)
    finally:
        await db.close()

    s = get_status()
    assert s.scanned == 1
    assert s.error_count == 1


@pytest.mark.asyncio
async def test_incremental_skips_already_scanned_files(tmp_path: Path) -> None:
    """Re-scanning the same folder skips unchanged files without re-inserting them."""
    (tmp_path / "photo.jpg").write_bytes(_jpeg_bytes())

    db = await _open_db(str(tmp_path / "test.db"))
    try:
        await run_scan(str(tmp_path), _noop_broadcast, db)
        first_scanned = get_status().scanned

        reset_status()

        await run_scan(str(tmp_path), _noop_broadcast, db)
        second = get_status()
    finally:
        await db.close()

    assert first_scanned == 1
    assert second.scanned == 0       # no new inserts
    assert second.skipped == 1       # one file recognised as up-to-date
    assert second.error_count == 0


@pytest.mark.asyncio
async def test_scan_progress_events_emitted_every_10_files(tmp_path: Path) -> None:
    """broadcast receives a scan_progress event every 10 files (frequent enough
    to drive the live gallery refresh) carrying scanned/total/eta_seconds."""
    jpeg = _jpeg_bytes()
    for i in range(35):
        (tmp_path / f"photo_{i:04d}.jpg").write_bytes(jpeg)

    events: list[dict[str, Any]] = []

    async def capture(msg: dict[str, Any]) -> None:
        events.append(msg)

    db = await _open_db(str(tmp_path / "test.db"))
    try:
        await run_scan(str(tmp_path), capture, db)
    finally:
        await db.close()

    progress_events = [e for e in events if e.get("type") == "scan_progress"]
    # 35 files → events at 10, 20, 30, and a final one at 35.
    assert len(progress_events) >= 3, (
        f"Expected ≥3 progress events for 35 files at every-10, got {len(progress_events)}"
    )
    for e in progress_events:
        assert set(e) >= {"type", "scanned", "total", "eta_seconds"}

    complete = [e for e in events if e.get("type") == "scan_complete"]
    assert len(complete) == 1
    assert complete[0]["total"] == 35


@pytest.mark.asyncio
async def test_throughput_exceeds_500_files_per_minute(tmp_path: Path) -> None:
    """Scanner (without ML embedding) processes ≥500 files/min on CI runners."""
    jpeg = _jpeg_bytes()
    for i in range(600):
        (tmp_path / f"photo_{i:04d}.jpg").write_bytes(jpeg)

    db = await _open_db(str(tmp_path / "test.db"))
    start = time.monotonic()
    try:
        await run_scan(str(tmp_path), _noop_broadcast, db)
    finally:
        await db.close()
    elapsed = time.monotonic() - start

    s = get_status()
    rate = s.scanned / elapsed * 60
    assert rate >= 500, f"Throughput {rate:.0f} files/min is below 500 files/min"


# ---------------------------------------------------------------------------
# Face extraction wiring: detect → insert → cluster
# ---------------------------------------------------------------------------


def _face(seed: int) -> FaceResult:
    rng = np.random.default_rng(seed)
    emb = rng.standard_normal(512).astype(np.float32)
    emb = emb / np.linalg.norm(emb)
    return FaceResult(bbox=(0.1, 0.1, 0.3, 0.3), embedding=emb, detection_confidence=0.95)


class _FakeRecognizer:
    def __init__(self, faces: list[FaceResult]) -> None:
        self._faces = faces

    def detect_and_embed(self, path: str) -> list[FaceResult]:
        return self._faces


class _ExplodingRecognizer:
    def detect_and_embed(self, path: str) -> list[FaceResult]:
        raise RuntimeError("model blew up")


async def _insert_photo(db: aiosqlite.Connection, path: str = "/p/a.jpg") -> int:
    cur = await db.execute(
        "INSERT INTO photos (path, mtime) VALUES (?, ?)", (path, int(time.time()))
    )
    await db.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


@pytest.mark.asyncio
async def test_extract_faces_inserts_and_clusters(tmp_path: Path) -> None:
    """_extract_faces persists each detected face and assigns it via clustering."""
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        photo_id = await _insert_photo(db)
        recognizer = _FakeRecognizer([_face(1), _face(2)])
        await _extract_faces("/p/a.jpg", photo_id, recognizer, ClusteringService(), db)

        faces = list(await (
            await db.execute("SELECT assign_status FROM faces WHERE photo_id = ?", (photo_id,))
        ).fetchall())
        assert len(faces) == 2
        assert all(f["assign_status"] == "assigned" for f in faces)

        # Two dissimilar embeddings → two seeded clusters.
        prow = await (await db.execute("SELECT COUNT(*) AS c FROM people")).fetchone()
        assert prow is not None and prow["c"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_extract_faces_swallows_recognizer_errors(tmp_path: Path) -> None:
    """A recognizer failure on one photo must not crash the scan or insert faces."""
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        photo_id = await _insert_photo(db)
        await _extract_faces("/p/a.jpg", photo_id, _ExplodingRecognizer(), ClusteringService(), db)

        nrow = await (await db.execute("SELECT COUNT(*) AS c FROM faces")).fetchone()
        assert nrow is not None and nrow["c"] == 0
    finally:
        await db.close()
