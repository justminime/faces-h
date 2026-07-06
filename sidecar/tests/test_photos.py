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


# ---------------------------------------------------------------------------
# Seeded full-library shuffle (#145)
# ---------------------------------------------------------------------------


async def _seed_person_gallery(data_dir: str, n_photos: int = 12) -> None:
    """One person assigned in n photos with spread-out taken_at dates."""
    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO people (id, name, created_at) VALUES (1, 'Alice', 0)"
        )
        for i in range(1, n_photos + 1):
            await db.execute(
                "INSERT INTO photos (id, path, mtime, taken_at) VALUES (?, ?, 1, ?)",
                (i, f"/g/{i}.jpg", i * 86_400),
            )
            await db.execute(
                """INSERT INTO faces (photo_id, detection_conf, person_id,
                                      assign_conf, assign_status)
                   VALUES (?, 0.9, 1, 0.9, 'assigned')""",
                (i,),
            )
        await db.commit()


@pytest.mark.asyncio
async def test_shuffle_pages_are_stable_and_disjoint(tmp_path: pytest.TempPathFactory) -> None:
    """With a fixed seed, paging walks ONE shuffled order: no repeats across
    pages, all photos covered, and the result is not date-sorted."""
    data_dir = str(tmp_path)
    os.environ["FACES_H_DATA_DIR"] = data_dir
    await _seed_person_gallery(data_dir)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        p1 = await ac.get("/people/1/photos?order=random&seed=7&limit=6&offset=0")
        p2 = await ac.get("/people/1/photos?order=random&seed=7&limit=6&offset=6")
        p1_again = await ac.get("/people/1/photos?order=random&seed=7&limit=6&offset=0")

    ids1 = [p["id"] for p in p1.json()]
    ids2 = [p["id"] for p in p2.json()]
    assert ids1 == [p["id"] for p in p1_again.json()], "same seed → stable page"
    assert not set(ids1) & set(ids2), "pages of one seed must not repeat photos"
    assert sorted(ids1 + ids2) == list(range(1, 13)), "all photos covered"
    assert ids1 != sorted(ids1), "returned order must not collapse to date/id order"


@pytest.mark.asyncio
async def test_different_seeds_give_different_order(tmp_path: pytest.TempPathFactory) -> None:
    data_dir = str(tmp_path)
    os.environ["FACES_H_DATA_DIR"] = data_dir
    await _seed_person_gallery(data_dir)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        a = await ac.get("/people/1/photos?order=random&seed=3&limit=12")
        b = await ac.get("/people/1/photos?order=random&seed=911&limit=12")
    assert [p["id"] for p in a.json()] != [p["id"] for p in b.json()]


@pytest.mark.asyncio
async def test_date_order_unchanged(tmp_path: pytest.TempPathFactory) -> None:
    data_dir = str(tmp_path)
    os.environ["FACES_H_DATA_DIR"] = data_dir
    await _seed_person_gallery(data_dir)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/people/1/photos?order=date&limit=12")
    ids = [p["id"] for p in r.json()]
    assert ids == sorted(ids), "order=date must stay chronological"
