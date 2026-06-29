"""Safety invariant: original photo files must never be modified, moved, or deleted.

These tests verify the core promise of faces-h: it is a read-only observer of
the user's photo library. They cover both the file scanner (which walks and
reads photos) and the face-crop endpoint (which opens images to extract crops).
"""

from __future__ import annotations

import hashlib
import io
import os
from typing import Any

import aiosqlite
from httpx import ASGITransport, AsyncClient
from PIL import Image

from db.schema import ALL_TABLES, INDEXES
from main import app
from services.scanner import reset_status, run_scan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jpeg_bytes(color: tuple[int, int, int] = (100, 150, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _file_fingerprint(path: str) -> dict[str, Any]:
    """Capture mtime, size, and SHA-256 of a file."""
    stat = os.stat(path)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return {"mtime": stat.st_mtime, "size": stat.st_size, "sha256": digest}


def _directory_snapshot(directory: str) -> dict[str, dict[str, Any]]:
    """Return a mapping of relative path → fingerprint for every file under directory."""
    snapshot: dict[str, dict[str, Any]] = {}
    for dirpath, _, filenames in os.walk(directory):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, directory)
            snapshot[rel] = _file_fingerprint(full)
    return snapshot


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


async def _noop_broadcast(msg: dict[str, Any]) -> None:
    pass


# ---------------------------------------------------------------------------
# Test 1: scanner does not touch photo files
# ---------------------------------------------------------------------------


async def test_scan_does_not_modify_photo_files(tmp_path: Any) -> None:
    """A full scan must leave every photo file byte-for-byte identical."""
    reset_status()

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()

    # Create 50 synthetic images across two sub-directories
    sub_a = photos_dir / "2022"
    sub_b = photos_dir / "2023"
    sub_a.mkdir()
    sub_b.mkdir()

    for i in range(25):
        (sub_a / f"img_{i:03d}.jpg").write_bytes(_jpeg_bytes((i * 3, i * 5, i * 7)))
    for i in range(25):
        (sub_b / f"img_{i:03d}.jpg").write_bytes(_jpeg_bytes((255 - i, i * 2, 128)))

    # Snapshot before scan
    before = _directory_snapshot(str(photos_dir))
    assert len(before) == 50

    db_path = str(tmp_path / "scan.db")
    conn = await _open_db(db_path)
    try:
        await run_scan(str(photos_dir), _noop_broadcast, conn)
    finally:
        await conn.close()

    # Snapshot after scan
    after = _directory_snapshot(str(photos_dir))

    # No files added or removed
    assert set(after.keys()) == set(before.keys()), (
        f"Scanner changed directory contents.\n"
        f"  Added: {set(after) - set(before)}\n"
        f"  Removed: {set(before) - set(after)}"
    )

    # Every file is byte-for-byte identical
    for rel, fp_before in before.items():
        fp_after = after[rel]
        assert fp_after["sha256"] == fp_before["sha256"], (
            f"Scanner modified file content: {rel}"
        )
        assert fp_after["size"] == fp_before["size"], (
            f"Scanner changed file size: {rel}"
        )
        assert fp_after["mtime"] == fp_before["mtime"], (
            f"Scanner changed file mtime: {rel}"
        )


# ---------------------------------------------------------------------------
# Test 2: second scan (incremental) still does not touch photo files
# ---------------------------------------------------------------------------


async def test_incremental_rescan_does_not_modify_photo_files(tmp_path: Any) -> None:
    """Re-scanning the same folder (incremental skip path) also leaves files intact."""
    reset_status()

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    for i in range(10):
        (photos_dir / f"img_{i:02d}.jpg").write_bytes(_jpeg_bytes((i * 10, 200, 50)))

    db_path = str(tmp_path / "scan.db")

    # First scan
    conn = await _open_db(db_path)
    await run_scan(str(photos_dir), _noop_broadcast, conn)
    await conn.close()

    reset_status()
    before = _directory_snapshot(str(photos_dir))

    # Second scan (incremental — all files already in DB)
    conn = await _open_db(db_path)
    try:
        await run_scan(str(photos_dir), _noop_broadcast, conn)
    finally:
        await conn.close()

    after = _directory_snapshot(str(photos_dir))

    assert set(after.keys()) == set(before.keys()), "Incremental scan changed directory contents"
    for rel, fp_before in before.items():
        assert after[rel]["sha256"] == fp_before["sha256"], (
            f"Incremental scan modified: {rel}"
        )


# ---------------------------------------------------------------------------
# Test 3: GET /faces/{id}/crop does not modify the source photo
# ---------------------------------------------------------------------------


async def test_face_crop_endpoint_does_not_modify_source_photo(tmp_path: Any) -> None:
    """The crop endpoint opens the photo read-only; the source file must be unchanged."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    photo_path = photos_dir / "portrait.jpg"
    photo_path.write_bytes(_jpeg_bytes((80, 120, 200)))

    fp_before = _file_fingerprint(str(photo_path))

    db_path = str(tmp_path / "faces.db")
    conn = await _open_db(db_path)
    try:
        # Insert a photo and face record pointing at the synthetic file
        await conn.execute(
            "INSERT INTO photos (path, mtime, taken_at) VALUES (?, ?, NULL)",
            (str(photo_path), int(os.path.getmtime(str(photo_path)))),
        )
        await conn.commit()
        row = await (await conn.execute("SELECT last_insert_rowid()")).fetchone()
        assert row is not None
        photo_id: int = row[0]

        await conn.execute(
            """INSERT INTO faces
               (photo_id, bbox_x, bbox_y, bbox_w, bbox_h,
                detection_conf, assign_status, assign_conf)
               VALUES (?, 0.1, 0.1, 0.8, 0.8, 1.0, 'unreviewed', 0.0)""",
            (photo_id,),
        )
        await conn.commit()
        row2 = await (await conn.execute("SELECT last_insert_rowid()")).fetchone()
        assert row2 is not None
        face_id: int = row2[0]
    finally:
        await conn.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/faces/{face_id}/crop")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    fp_after = _file_fingerprint(str(photo_path))
    assert fp_after["sha256"] == fp_before["sha256"], "Crop endpoint modified source photo content"
    assert fp_after["size"] == fp_before["size"], "Crop endpoint changed source photo size"
    assert fp_after["mtime"] == fp_before["mtime"], "Crop endpoint changed source photo mtime"
