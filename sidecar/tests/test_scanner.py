"""Tests for the file scanner service."""

import io
import os
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


@pytest.mark.slow
@pytest.mark.asyncio
async def test_throughput_exceeds_500_files_per_minute(tmp_path: Path) -> None:
    """Scanner (without ML embedding) processes ≥500 files/min on CI runners.

    Hardware-variance-sensitive hard threshold — belongs with the other perf
    benchmarks under `-m slow`, not the default CI gate (it flaked on a
    throttled Windows runner: 382/min, unrelated to any code change)."""
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
    """A recognizer failure on one photo must not crash the scan or insert faces.

    The photo also stays faces_extracted = 0 so it is retried on the next scan.
    """
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        photo_id = await _insert_photo(db)
        await _extract_faces("/p/a.jpg", photo_id, _ExplodingRecognizer(), ClusteringService(), db)

        nrow = await (await db.execute("SELECT COUNT(*) AS c FROM faces")).fetchone()
        assert nrow is not None and nrow["c"] == 0

        prow = await (await db.execute(
            "SELECT faces_extracted FROM photos WHERE id = ?", (photo_id,)
        )).fetchone()
        assert prow is not None and prow["faces_extracted"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_extract_faces_marks_photo_extracted(tmp_path: Path) -> None:
    """faces_extracted is set to 1 after all faces commit — even for zero faces."""
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        with_faces = await _insert_photo(db, "/p/a.jpg")
        no_faces = await _insert_photo(db, "/p/b.jpg")
        await _extract_faces("/p/a.jpg", with_faces, _FakeRecognizer([_face(1)]), ClusteringService(), db)
        await _extract_faces("/p/b.jpg", no_faces, _FakeRecognizer([]), ClusteringService(), db)

        for photo_id in (with_faces, no_faces):
            row = await (await db.execute(
                "SELECT faces_extracted FROM photos WHERE id = ?", (photo_id,)
            )).fetchone()
            assert row is not None and row["faces_extracted"] == 1
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Crash-resume and re-extraction gate (#90 / #104)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crash_resume_replaces_partial_faces(tmp_path: Path) -> None:
    """A photo left with faces_extracted=0 and a partial face row (mid-extraction
    crash) is re-extracted cleanly: stale rows — and corrections pointing at
    them — are replaced, no duplicates, and the flag becomes 1."""
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        photo_id = await _insert_photo(db)  # faces_extracted defaults to 0

        # Simulate the crash: one face row committed, flag still 0, plus a
        # correction referencing the partial face (FK: corrections → faces).
        cur = await db.execute(
            """INSERT INTO faces (photo_id, detection_conf, assign_status)
               VALUES (?, 0.9, 'unreviewed')""",
            (photo_id,),
        )
        assert cur.lastrowid is not None
        await db.execute(
            "INSERT INTO corrections (face_id, corrected_at) VALUES (?, ?)",
            (cur.lastrowid, int(time.time())),
        )
        await db.commit()

        recognizer = _FakeRecognizer([_face(1), _face(2)])
        await _extract_faces("/p/a.jpg", photo_id, recognizer, ClusteringService(), db)

        frow = await (await db.execute(
            "SELECT COUNT(*) AS c FROM faces WHERE photo_id = ?", (photo_id,)
        )).fetchone()
        assert frow is not None and frow["c"] == 2  # exactly the new set — no leftovers

        prow = await (await db.execute(
            "SELECT faces_extracted FROM photos WHERE id = ?", (photo_id,)
        )).fetchone()
        assert prow is not None and prow["faces_extracted"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reextraction_rebuilds_affected_centroids(tmp_path: Path) -> None:
    """Deleting a photo's faces rebuilds the affected person's centroid from the
    remaining assigned faces, so stale embeddings stop voting (#104)."""
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        clustering = ClusteringService()
        photo1 = await _insert_photo(db, "/p/1.jpg")
        photo2 = await _insert_photo(db, "/p/2.jpg")

        # Face 1 (photo1) seeds person P; face 2 (photo2) is similar enough to
        # auto-assign to P and blend into its centroid.
        emb1 = _face(1).embedding
        blend = 0.9 * emb1 + 0.1 * _face(2).embedding
        emb2 = (blend / np.linalg.norm(blend)).astype(np.float32)

        face_ids = []
        for photo_id, emb in ((photo1, emb1), (photo2, emb2)):
            cur = await db.execute(
                """INSERT INTO faces (photo_id, detection_conf, assign_status)
                   VALUES (?, 0.95, 'unreviewed')""",
                (photo_id,),
            )
            await db.commit()
            assert cur.lastrowid is not None
            face_ids.append(int(cur.lastrowid))
            await clustering.assign_face(int(cur.lastrowid), emb, db)

        prow = await (await db.execute("SELECT COUNT(*) AS c FROM people")).fetchone()
        assert prow is not None and prow["c"] == 1  # both faces on one person

        # photo1 was modified and now contains no faces: its face row is
        # deleted and the centroid must be rebuilt from emb2 alone.
        await _extract_faces("/p/1.jpg", photo1, _FakeRecognizer([]), clustering, db)

        crow = await (await db.execute("SELECT centroid FROM people")).fetchone()
        assert crow is not None
        centroid = np.frombuffer(crow["centroid"], dtype=np.float32)
        assert np.allclose(centroid, emb2, atol=1e-5)

        # The surviving face is untouched (status unchanged — Rule 6: nothing
        # is promoted or demoted by the rebuild).
        srow = await (await db.execute(
            "SELECT assign_status FROM faces WHERE id = ?", (face_ids[1],)
        )).fetchone()
        assert srow is not None and srow["assign_status"] == "assigned"
    finally:
        await db.close()


class _CountingRecognizer:
    """Fake recognizer that records how many times detection ran."""

    def __init__(self, faces: list[FaceResult]) -> None:
        self._faces = faces
        self.calls = 0

    def detect_and_embed(self, path: str) -> list[FaceResult]:
        self.calls += 1
        return list(self._faces)


def _install_recognizer(
    monkeypatch: pytest.MonkeyPatch, recognizer: _CountingRecognizer
) -> None:
    """Make run_scan use the given fake instead of loading buffalo_l."""
    import ml.insightface_recognizer as ir

    monkeypatch.setattr(ir, "InsightFaceRecognizer", lambda data_dir: recognizer)


@pytest.mark.asyncio
async def test_zero_face_photo_not_reprocessed_on_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A photo with no detected faces gets faces_extracted=1 and is NOT re-run
    through detection on the next scan (fixes perpetual re-processing)."""
    (tmp_path / "photo.jpg").write_bytes(_jpeg_bytes())
    recognizer = _CountingRecognizer([])
    _install_recognizer(monkeypatch, recognizer)

    db = await _open_db(str(tmp_path / "test.db"))
    try:
        await run_scan(str(tmp_path), _noop_broadcast, db)
        assert recognizer.calls == 1

        row = await (await db.execute(
            "SELECT faces_extracted FROM photos WHERE path LIKE '%photo.jpg'"
        )).fetchone()
        assert row is not None and row["faces_extracted"] == 1

        reset_status()
        await run_scan(str(tmp_path), _noop_broadcast, db)
        assert recognizer.calls == 1  # unchanged file + flag=1 → no re-detection
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_modified_photo_faces_replaced_not_duplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scan → touch mtime → rescan: the photo's face count is unchanged (#104)."""
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(_jpeg_bytes())
    recognizer = _CountingRecognizer([_face(1)])
    _install_recognizer(monkeypatch, recognizer)

    db = await _open_db(str(tmp_path / "test.db"))
    try:
        await run_scan(str(tmp_path), _noop_broadcast, db)
        assert recognizer.calls == 1

        # Touch the file: bump mtime by well over a second so the int compare sees it.
        new_time = time.time() + 100
        os.utime(photo, (new_time, new_time))

        reset_status()
        await run_scan(str(tmp_path), _noop_broadcast, db)
        assert recognizer.calls == 2  # modified file was re-detected

        row = await (await db.execute(
            """SELECT COUNT(*) AS c FROM faces
               WHERE photo_id = (SELECT id FROM photos WHERE path LIKE '%photo.jpg')"""
        )).fetchone()
        assert row is not None and row["c"] == 1  # replaced, not doubled

        prow = await (await db.execute(
            "SELECT faces_extracted FROM photos WHERE path LIKE '%photo.jpg'"
        )).fetchone()
        assert prow is not None and prow["faces_extracted"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_extract_faces_skips_small_and_low_confidence(tmp_path: Path) -> None:
    """OD-04 (#111): detections below min_face_px or the detector-confidence
    floor are not persisted; the skip count lands in scan status."""
    from services.scanner import reset_status

    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)  # defaults: 20px / 0.5
    reset_status()
    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        photo_id = await _insert_photo(db)

        good = _face(1)
        good.size_px = 120.0
        tiny = _face(2)
        tiny.size_px = 8.0  # below 20px floor
        low_conf = _face(3)
        low_conf.size_px = 90.0
        low_conf.detection_confidence = 0.2  # below 0.5 floor
        unknown_size = _face(4)
        unknown_size.size_px = 0.0  # backend didn't report — exempt from size filter

        recognizer = _FakeRecognizer([good, tiny, low_conf, unknown_size])
        await _extract_faces("/p/a.jpg", photo_id, recognizer, ClusteringService(), db)

        rows = list(await (
            await db.execute("SELECT id FROM faces WHERE photo_id = ?", (photo_id,))
        ).fetchall())
        assert len(rows) == 2, "only the good and unknown-size faces persist"
        assert get_status().skipped_faces == 2

        # Photo still marked extraction-complete even though faces were skipped.
        prow = await (
            await db.execute("SELECT faces_extracted FROM photos WHERE id = ?", (photo_id,))
        ).fetchone()
        assert prow is not None and prow["faces_extracted"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_extract_faces_size_filter_respects_config(tmp_path: Path) -> None:
    """min_face_px from config.json overrides the default floor."""
    import json

    from config import reset_config_cache
    from services.scanner import reset_status

    (tmp_path / "config.json").write_text(
        json.dumps({"min_face_px": 5, "min_detection_confidence": 0.1}), encoding="utf-8"
    )
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    reset_config_cache()
    reset_status()

    db = await _open_db(str(tmp_path / "test.db"))
    db.row_factory = aiosqlite.Row
    try:
        photo_id = await _insert_photo(db)
        small = _face(1)
        small.size_px = 8.0  # above the configured 5px floor now
        recognizer = _FakeRecognizer([small])
        await _extract_faces("/p/a.jpg", photo_id, recognizer, ClusteringService(), db)

        rows = list(await (
            await db.execute("SELECT id FROM faces WHERE photo_id = ?", (photo_id,))
        ).fetchall())
        assert len(rows) == 1
        assert get_status().skipped_faces == 0
    finally:
        await db.close()
