import os
from pathlib import Path

import aiosqlite
import pytest

from db.database import get_db
from db.schema import FACES, PEOPLE

# The photos table as it existed before the faces_extracted column (#90),
# used to simulate a user's pre-migration database file.
_OLD_PHOTOS = """
CREATE TABLE photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT    NOT NULL UNIQUE,
    mtime       INTEGER NOT NULL,
    scanned_at  INTEGER,
    width       INTEGER,
    height      INTEGER,
    taken_at    INTEGER
)
"""


async def _seed_pre_migration_db(tmp_path: Path) -> None:
    """Create faces.db with the old photos schema: photo 1 has a face, photo 2 has none."""
    conn = await aiosqlite.connect(str(tmp_path / "faces.db"))
    try:
        await conn.execute(_OLD_PHOTOS)
        await conn.execute(PEOPLE)
        await conn.execute(FACES)
        await conn.execute("INSERT INTO photos (id, path, mtime) VALUES (1, '/a.jpg', 0)")
        await conn.execute("INSERT INTO photos (id, path, mtime) VALUES (2, '/b.jpg', 0)")
        await conn.execute(
            """INSERT INTO faces (photo_id, detection_conf, assign_status)
               VALUES (1, 0.9, 'assigned')"""
        )
        await conn.commit()
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)


@pytest.mark.asyncio
async def test_all_tables_created() -> None:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in await cursor.fetchall()}

    assert tables == {"corrections", "faces", "people", "photos", "scan_state", "scan_roots"}


@pytest.mark.asyncio
async def test_all_indexes_created() -> None:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indexes = {row[0] for row in await cursor.fetchall()}

    assert indexes == {
        "idx_faces_photo",
        "idx_faces_person",
        "idx_faces_status",
        "idx_photos_path",
        "idx_photos_taken_at",
        "idx_scan_roots_path",
    }


@pytest.mark.asyncio
async def test_wal_mode_enabled() -> None:
    async with get_db() as conn:
        cursor = await conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()

    assert row is not None and row[0] == "wal"


@pytest.mark.asyncio
async def test_foreign_key_enforcement() -> None:
    """Inserting a face that references a non-existent photo must raise."""
    async with get_db() as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                """
                INSERT INTO faces
                    (photo_id, detection_conf, assign_status)
                VALUES (9999, 0.99, 'unreviewed')
                """
            )
            await conn.commit()


@pytest.mark.asyncio
async def test_schema_is_idempotent() -> None:
    """Calling get_db() twice on the same file must not raise."""
    async with get_db():
        pass
    async with get_db():
        pass


@pytest.mark.asyncio
async def test_faces_extracted_migration_backfills_existing_faces(tmp_path: Path) -> None:
    """Upgrading a pre-#90 DB adds faces_extracted and backfills it to 1 for
    photos that already have face rows, so they are NOT re-extracted (which
    would destroy named assignments). Photos without faces stay 0."""
    await _seed_pre_migration_db(tmp_path)

    async with get_db() as conn:
        rows = await (
            await conn.execute("SELECT id, faces_extracted FROM photos ORDER BY id")
        ).fetchall()

    flags = {row["id"]: row["faces_extracted"] for row in rows}
    assert flags == {1: 1, 2: 0}


@pytest.mark.asyncio
async def test_faces_extracted_backfill_runs_only_once(tmp_path: Path) -> None:
    """The backfill is one-shot: after the column exists, a photo with face
    rows but flag 0 (crash mid-extraction) must NOT be flipped to 1 by a
    later connection."""
    await _seed_pre_migration_db(tmp_path)

    async with get_db() as conn:
        # Simulate a crash mid-extraction after the migration: photo 2 gains a
        # partial face row while its flag is still 0.
        await conn.execute(
            """INSERT INTO faces (photo_id, detection_conf, assign_status)
               VALUES (2, 0.8, 'unreviewed')"""
        )
        await conn.commit()

    async with get_db() as conn:
        row = await (
            await conn.execute("SELECT faces_extracted FROM photos WHERE id = 2")
        ).fetchone()

    assert row is not None and row["faces_extracted"] == 0


@pytest.mark.asyncio
async def test_db_file_created_in_data_dir(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    async with get_db():
        pass
    assert (tmp_path / "faces.db").exists()
