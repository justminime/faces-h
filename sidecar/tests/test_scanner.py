"""Tests for the file scanner service."""

import io
import time
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from PIL import Image

from db.schema import ALL_TABLES, INDEXES
from services.scanner import get_status, reset_status, run_scan


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_status() -> None:
    """Reset the global scan state before every test."""
    reset_status()


async def _open_db(path: str) -> aiosqlite.Connection:
    """Open a SQLite connection at path with the full schema applied."""
    conn = await aiosqlite.connect(path)
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
async def test_scan_progress_events_emitted_every_100_files(tmp_path: Path) -> None:
    """broadcast receives a scan_progress event at least once per 100 files."""
    jpeg = _jpeg_bytes()
    for i in range(201):
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
    assert len(progress_events) >= 2, (
        f"Expected ≥2 progress events for 201 files, got {len(progress_events)}"
    )
    assert any(e.get("type") == "scan_complete" for e in events)


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
