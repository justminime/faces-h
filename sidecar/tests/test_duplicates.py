"""Tests for duplicate detection (#155)."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from services import image_cache


def _photo_bytes(seed: int, size: int = 128, quality: int = 90) -> bytes:
    """Smooth synthetic 'photo' (angled gradients) — dHash-stable across
    resizes, unlike random noise which is resampling-pathological."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    r = (np.sin(x * (2 + seed) + seed) * 0.5 + 0.5) * 255
    g = (np.cos(y * (3 + seed)) * 0.5 + 0.5) * 255
    b = ((x + y) / 2) * 255
    arr = np.stack([r, g, b], axis=-1).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def test_dhash_matches_across_resize() -> None:
    """The same shot at different resolutions hashes identically (dHash)."""
    original = _photo_bytes(1)
    with Image.open(io.BytesIO(original)) as img:
        small = io.BytesIO()
        img.resize((48, 48), Image.Resampling.LANCZOS).save(small, format="JPEG")
    h1 = image_cache.dhash_from_jpeg(original)
    h2 = image_cache.dhash_from_jpeg(small.getvalue())
    h3 = image_cache.dhash_from_jpeg(_photo_bytes(2))
    assert h1 is not None and h1 == h2, "resized copy must hash the same"
    assert h1 != h3, "different photos must not collide"


async def _seed_photo(
    db, pid: int, path: Path, data: bytes, phash: int | None
) -> None:
    path.write_bytes(data)
    await db.execute(
        "INSERT INTO photos (id, path, mtime, file_size, phash) VALUES (?, ?, 1, ?, ?)",
        (pid, str(path), len(data), phash),
    )


@pytest.mark.asyncio
async def test_duplicates_groups_exact_and_similar(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)
    lib = tmp_path / "lib"
    sub = lib / "backup"
    lib.mkdir()
    sub.mkdir()

    from db.database import get_db

    a = _photo_bytes(1)
    similar = _photo_bytes(1, quality=60)  # same shot, re-encoded → same phash, different bytes
    unique = _photo_bytes(7)

    async with get_db() as db:
        await _seed_photo(db, 1, lib / "IMG_001.jpg", a, phash=111)
        await _seed_photo(db, 2, sub / "IMG_001 (copy).jpg", a, phash=111)  # exact copy
        await _seed_photo(db, 3, lib / "resized.jpg", similar, phash=111)   # similar only
        await _seed_photo(db, 4, lib / "unique.jpg", unique, phash=999)
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/photos/duplicates")
    assert r.status_code == 200
    groups = r.json()

    exact = [g for g in groups if g["kind"] == "exact"]
    similar_groups = [g for g in groups if g["kind"] == "similar"]
    assert len(exact) == 1
    exact_ids = {p["id"] for p in exact[0]["photos"]}
    assert exact_ids == {1, 2}, "byte-identical files group as exact"

    entry = next(p for p in exact[0]["photos"] if p["id"] == 2)
    assert entry["filename"] == "IMG_001 (copy).jpg"
    assert entry["folder"].endswith("backup"), "each copy shows its folder"

    assert len(similar_groups) == 1
    sim_ids = {p["id"] for p in similar_groups[0]["photos"]}
    assert 3 in sim_ids and 4 not in sim_ids, "same-phash photos group as similar"

    # content_hash was cached — a second call must not need to re-hash.
    from db.database import get_db as gdb

    async with gdb() as db:
        row = await (
            await db.execute("SELECT content_hash FROM photos WHERE id = 1")
        ).fetchone()
    assert row is not None and row["content_hash"], "hashes cached for instant re-runs"


@pytest.mark.asyncio
async def test_no_duplicates_returns_empty(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO photos (id, path, mtime, file_size, phash) VALUES (1, '/a.jpg', 1, 100, 5)"
        )
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/photos/duplicates")
    assert r.status_code == 200
    assert r.json() == []
