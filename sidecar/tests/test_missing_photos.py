"""Tests for deleted/moved photo reconciliation (#105)."""

import io
import os
from pathlib import Path
from typing import Any

import aiosqlite
import numpy as np
import pytest
from PIL import Image

from db.schema import ALL_TABLES, INDEXES
from services.scanner import run_scan


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(120, 80, 200)).save(buf, format="JPEG")
    return buf.getvalue()


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


async def _noop_broadcast(_msg: dict[str, Any]) -> None:
    return None


async def _missing_flag(db: aiosqlite.Connection, path: str) -> int | None:
    row = await (
        await db.execute("SELECT missing FROM photos WHERE path = ?", (path,))
    ).fetchone()
    return int(row["missing"]) if row else None


@pytest.mark.asyncio
async def test_deleted_photo_marked_missing_and_revived(tmp_path: Path) -> None:
    """Delete a file → rescan marks it missing (row kept). Restore it →
    rescan revives it."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    root = tmp_path / "lib"
    root.mkdir()
    keep = root / "keep.jpg"
    gone = root / "gone.jpg"
    keep.write_bytes(_jpeg_bytes())
    gone.write_bytes(_jpeg_bytes())

    db = await _open_db(str(tmp_path / "t.db"))
    try:
        await run_scan(str(root), _noop_broadcast, db)
        assert await _missing_flag(db, str(gone)) == 0

        gone.unlink()
        await run_scan(str(root), _noop_broadcast, db)
        assert await _missing_flag(db, str(gone)) == 1, "deleted photo must be marked missing"
        assert await _missing_flag(db, str(keep)) == 0

        # File restored at the same path → revived on the next scan.
        gone.write_bytes(_jpeg_bytes())
        await run_scan(str(root), _noop_broadcast, db)
        assert await _missing_flag(db, str(gone)) == 0, "restored photo must be revived"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unreachable_root_never_mass_marks(tmp_path: Path) -> None:
    """An offline/unreachable root returns early — its photos stay visible."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    root = tmp_path / "nas"
    db = await _open_db(str(tmp_path / "t.db"))
    try:
        photo = str(root / "img.jpg")
        await db.execute(
            "INSERT INTO photos (path, mtime) VALUES (?, 1)", (photo,)
        )
        await db.commit()

        # Root directory does not exist → run_scan bails before reconciling.
        await run_scan(str(root), _noop_broadcast, db)
        assert await _missing_flag(db, photo) == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_search_and_person_views_exclude_missing(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    from httpx import ASGITransport, AsyncClient

    from db.database import get_db

    async with get_db() as db:
        emb = np.ones(4, dtype=np.float32).tobytes()
        await db.execute(
            "INSERT INTO people (id, name, created_at, centroid) VALUES (1, 'Alice', 0, ?)",
            (emb,),
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, taken_at, missing) VALUES (1, '/x/a.jpg', 1, 100, 1)"
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, taken_at, missing) VALUES (2, '/x/b.jpg', 1, 100, 0)"
        )
        for photo_id, face_id in ((1, 1), (2, 2)):
            await db.execute(
                """INSERT INTO faces (id, photo_id, detection_conf, person_id,
                                      assign_conf, assign_status)
                   VALUES (?, ?, 0.9, 1, 0.9, 'assigned')""",
                (face_id, photo_id),
            )
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/search", json={"people_ids": [1]})
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert ids == [2], "missing photo must not appear in search results"

        r = await ac.get("/people/1/photos")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert ids == [2], "missing photo must not appear in the person gallery"

        r = await ac.get("/people")
        assert r.status_code == 200
        alice = next(p for p in r.json() if p["id"] == 1)
        assert alice["photo_count"] == 1
        assert alice["medallion_face_id"] == 2, "medallion must come from a non-missing photo"


@pytest.mark.asyncio
async def test_rebuild_centroid_ignores_missing_photo_faces(tmp_path: Path) -> None:
    from services.clustering import ClusteringService, _deserialize_centroid

    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    db = await _open_db(str(tmp_path / "t.db"))
    try:
        rng = np.random.default_rng(1)
        keep_emb = rng.standard_normal(8).astype(np.float32)
        keep_emb /= np.linalg.norm(keep_emb)
        gone_emb = rng.standard_normal(8).astype(np.float32)
        gone_emb /= np.linalg.norm(gone_emb)

        await db.execute(
            "INSERT INTO people (id, name, created_at, centroid) VALUES (1, 'A', 0, ?)",
            (keep_emb.tobytes(),),
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, missing) VALUES (1, '/k.jpg', 1, 0)"
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, missing) VALUES (2, '/g.jpg', 1, 1)"
        )
        await db.execute(
            """INSERT INTO faces (photo_id, detection_conf, person_id, assign_status, embedding)
               VALUES (1, 0.9, 1, 'assigned', ?)""",
            (keep_emb.tobytes(),),
        )
        await db.execute(
            """INSERT INTO faces (photo_id, detection_conf, person_id, assign_status, embedding)
               VALUES (2, 0.9, 1, 'assigned', ?)""",
            (gone_emb.tobytes(),),
        )
        await db.commit()

        await ClusteringService().rebuild_centroid(1, db)

        row = await (
            await db.execute("SELECT centroid FROM people WHERE id = 1")
        ).fetchone()
        assert row is not None
        centroid = _deserialize_centroid(row["centroid"])
        assert float(np.dot(centroid, keep_emb)) == pytest.approx(1.0, abs=1e-4), (
            "centroid must be rebuilt from the non-missing face only"
        )
    finally:
        await db.close()
