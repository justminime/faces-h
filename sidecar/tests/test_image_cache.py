"""Tests for the thumbnail / face-crop disk cache (#114)."""

import os
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from db.schema import ALL_TABLES, INDEXES
from services import image_cache


async def _init_db(data_dir: str) -> None:
    os.environ["FACES_H_DATA_DIR"] = data_dir
    from db.database import get_db

    async with get_db() as db:
        for stmt in ALL_TABLES:
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


def _write_jpeg(path: Path, color: tuple[int, int, int] = (200, 60, 60)) -> None:
    Image.new("RGB", (64, 48), color).save(path, format="JPEG")


async def _seed_photo(data_dir: str, photo_path: str, mtime: int = 1000) -> None:
    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO photos (id, path, mtime) VALUES (1, ?, ?)"
            " ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime",
            (photo_path, mtime),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Cache primitives
# ---------------------------------------------------------------------------


def test_put_get_roundtrip(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    key = image_cache.cache_key("thumbs", 1, 1000, variant="256")
    assert image_cache.get(key) is None
    image_cache.put(key, b"jpegbytes")
    assert image_cache.get(key) == b"jpegbytes"


def test_put_removes_stale_variants(tmp_path: Path) -> None:
    """A new mtime for the same photo+size drops the outdated cache file."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    old_key = image_cache.cache_key("thumbs", 1, 1000, variant="256")
    new_key = image_cache.cache_key("thumbs", 1, 2000, variant="256")
    image_cache.put(old_key, b"old")
    image_cache.put(new_key, b"new")
    assert image_cache.get(old_key) is None, "stale variant should be evicted"
    assert image_cache.get(new_key) == b"new"
    # Different size variant for the same photo is untouched.
    other_size = image_cache.cache_key("thumbs", 1, 2000, variant="128")
    image_cache.put(other_size, b"small")
    assert image_cache.get(new_key) == b"new"


def test_eviction_removes_oldest_first(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    keys = []
    for i in range(5):
        k = image_cache.cache_key("thumbs", i, 1000)
        image_cache.put(k, b"x" * 100)
        past = time.time() - (100 - i)  # index 0 oldest
        os.utime(k, (past, past))
        keys.append(k)

    image_cache._evict_if_needed(max_bytes=250)

    survivors = [k for k in keys if image_cache.get(k) is not None]
    assert len(survivors) == 2
    assert survivors == keys[3:], "oldest files must be evicted first"


# ---------------------------------------------------------------------------
# Endpoint integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thumbnail_served_from_cache_after_source_deleted(tmp_path: Path) -> None:
    """Second request must not touch the original: delete the source file
    between requests and the thumbnail still serves (from disk cache)."""
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    photo_file = tmp_path / "img.jpg"
    _write_jpeg(photo_file)

    await _init_db(data_dir)
    await _seed_photo(data_dir, str(photo_file))

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.get("/photos/1/thumbnail?size=64")
        assert r1.status_code == 200
        assert r1.headers["x-cache"] == "miss"

        photo_file.unlink()  # cache must carry the second request

        r2 = await ac.get("/photos/1/thumbnail?size=64")
        assert r2.status_code == 200
        assert r2.headers["x-cache"] == "hit"
        assert r2.content == r1.content


@pytest.mark.asyncio
async def test_thumbnail_regenerated_when_mtime_changes(tmp_path: Path) -> None:
    """Bumping the photo's DB mtime invalidates the cached thumbnail."""
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    photo_file = tmp_path / "img.jpg"
    _write_jpeg(photo_file)

    await _init_db(data_dir)
    await _seed_photo(data_dir, str(photo_file), mtime=1000)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.get("/photos/1/thumbnail?size=64")
        assert r1.status_code == 200

        _write_jpeg(photo_file, color=(20, 200, 20))  # photo edited
        await _seed_photo(data_dir, str(photo_file), mtime=2000)

        r2 = await ac.get("/photos/1/thumbnail?size=64")
        assert r2.status_code == 200
        assert r2.headers["x-cache"] == "miss"
        assert r2.content != r1.content, "edited photo must produce a new thumbnail"


@pytest.mark.asyncio
async def test_face_crop_served_from_cache(tmp_path: Path) -> None:
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    photo_file = tmp_path / "img.jpg"
    _write_jpeg(photo_file)

    await _init_db(data_dir)
    await _seed_photo(data_dir, str(photo_file))

    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            """INSERT INTO faces (id, photo_id, detection_conf, assign_status,
                                  bbox_x, bbox_y, bbox_w, bbox_h)
               VALUES (1, 1, 0.9, 'unreviewed', 0.1, 0.1, 0.5, 0.5)"""
        )
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.get("/faces/1/crop")
        assert r1.status_code == 200
        assert r1.headers["x-cache"] == "miss"
        r2 = await ac.get("/faces/1/crop")
        assert r2.status_code == 200
        assert r2.headers["x-cache"] == "hit"
        assert r2.content == r1.content


@pytest.mark.asyncio
async def test_scan_warms_thumbnail_cache(tmp_path: Path) -> None:
    """#150: after a scan, the 256px thumbnail is already on disk so the
    first gallery visit never decodes the full-resolution original."""
    from services import image_cache
    from services.scanner import run_scan

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    os.environ["FACES_H_DATA_DIR"] = str(data_dir)

    root = tmp_path / "lib"
    root.mkdir()
    photo = root / "warm.jpg"
    _write_jpeg(photo)

    import aiosqlite

    from db.schema import ALL_TABLES, INDEXES

    db = await aiosqlite.connect(str(data_dir / "t.db"))
    db.row_factory = aiosqlite.Row
    for ddl in ALL_TABLES:
        await db.execute(ddl)
    for idx in INDEXES:
        await db.execute(idx)
    await db.commit()

    async def _noop(_msg: object) -> None:
        return None

    try:
        await run_scan(str(root), _noop, db)
        row = await (
            await db.execute("SELECT id, mtime FROM photos WHERE path = ?", (str(photo),))
        ).fetchone()
        assert row is not None
        key = image_cache.cache_key("thumbs", int(row["id"]), int(row["mtime"]), variant="256")
        assert image_cache.get(key) is not None, "scan must pre-generate the thumbnail"
    finally:
        await db.close()
