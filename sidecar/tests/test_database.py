import os
from pathlib import Path

import aiosqlite
import pytest

from db.database import get_db


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
async def test_db_file_created_in_data_dir(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    async with get_db():
        pass
    assert (tmp_path / "faces.db").exists()
