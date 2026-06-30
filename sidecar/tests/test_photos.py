"""Tests for the photo thumbnail serving endpoint."""

import io
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from db.schema import ALL_TABLES, INDEXES


async def _init_db(data_dir: str) -> None:
    os.environ["FACES_H_DATA_DIR"] = data_dir
    from db.database import get_db

    async with get_db() as db:
        for stmt in ALL_TABLES:
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


def _write_jpeg(path: Path, size: tuple[int, int] = (800, 600)) -> None:
    Image.new("RGB", size, color=(180, 90, 40)).save(path, format="JPEG")


async def _insert_photo(photo_id: int, path: str) -> None:
    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO photos (id, path, mtime, scanned_at) VALUES (?, ?, 0, 0)",
            (photo_id, path),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_thumbnail_returns_jpeg(tmp_path: Path) -> None:
    """GET /photos/{id}/thumbnail returns a valid JPEG with image content-type."""
    await _init_db(str(tmp_path))
    img_path = tmp_path / "photo.jpg"
    _write_jpeg(img_path)
    await _insert_photo(1, str(img_path))

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/photos/1/thumbnail")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0
    out = Image.open(io.BytesIO(r.content))
    assert out.format == "JPEG"


@pytest.mark.asyncio
async def test_thumbnail_is_downscaled_to_requested_size(tmp_path: Path) -> None:
    """The returned image fits within the requested bounding box (no upscaling beyond it)."""
    await _init_db(str(tmp_path))
    img_path = tmp_path / "big.jpg"
    _write_jpeg(img_path, size=(2000, 1000))
    await _insert_photo(1, str(img_path))

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/photos/1/thumbnail?size=128")

    assert r.status_code == 200
    out = Image.open(io.BytesIO(r.content))
    assert max(out.size) <= 128
    # Aspect ratio preserved: 2:1 source → width is the long edge.
    assert out.size[0] >= out.size[1]


@pytest.mark.asyncio
async def test_thumbnail_unknown_photo_returns_404(tmp_path: Path) -> None:
    await _init_db(str(tmp_path))

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/photos/999/thumbnail")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_missing_file_returns_404(tmp_path: Path) -> None:
    """A DB row pointing at a deleted file yields 404, not a 500."""
    await _init_db(str(tmp_path))
    await _insert_photo(1, str(tmp_path / "does-not-exist.jpg"))

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/photos/1/thumbnail")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_size_out_of_range_rejected(tmp_path: Path) -> None:
    """size is validated to a sane bound (FastAPI returns 422 for out-of-range)."""
    await _init_db(str(tmp_path))
    img_path = tmp_path / "photo.jpg"
    _write_jpeg(img_path)
    await _insert_photo(1, str(img_path))

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        too_big = await ac.get("/photos/1/thumbnail?size=99999")
        too_small = await ac.get("/photos/1/thumbnail?size=1")

    assert too_big.status_code == 422
    assert too_small.status_code == 422
