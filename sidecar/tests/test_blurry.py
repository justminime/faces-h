"""Tests for blur scoring and the Recycle-Bin trash flow (#154)."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageFilter

from services import image_cache


def _sharp_jpeg() -> bytes:
    """High-frequency checkerboard — strongly sharp."""
    arr = (np.indices((64, 64)).sum(axis=0) % 2 * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(arr, mode="L").convert("RGB").save(buf, format="JPEG")
    return buf.getvalue()


def _blurry_jpeg() -> bytes:
    arr = (np.indices((64, 64)).sum(axis=0) % 2 * 255).astype("uint8")
    img = Image.fromarray(arr, mode="L").convert("RGB").filter(
        ImageFilter.GaussianBlur(radius=8)
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def _seed(data_dir: str, photos: list[tuple[int, str, float | None]]) -> None:
    from db.database import get_db

    async with get_db() as db:
        for pid, path, score in photos:
            await db.execute(
                "INSERT INTO photos (id, path, mtime, blur_score) VALUES (?, ?, 1, ?)",
                (pid, path, score),
            )
        await db.commit()


def test_blur_score_separates_sharp_from_blurry() -> None:
    sharp = image_cache.blur_score_from_jpeg(_sharp_jpeg())
    blurry = image_cache.blur_score_from_jpeg(_blurry_jpeg())
    assert sharp is not None and blurry is not None
    assert sharp > blurry * 5, f"sharp={sharp:.1f} must dwarf blurry={blurry:.1f}"


@pytest.mark.asyncio
async def test_blurry_endpoint_filters_and_sorts(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    await _seed(
        str(tmp_path),
        [
            (1, "/g/sharp.jpg", 500.0),
            (2, "/g/soft.jpg", 40.0),
            (3, "/g/very-blurry.jpg", 5.0),
            (4, "/g/unscored.jpg", None),
        ],
    )

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/photos/blurry")  # default threshold 60
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert ids == [3, 2], "most blurred first; sharp and unscored excluded"

        # Slider override: tighter cutoff keeps only the severe one.
        r = await ac.get("/photos/blurry?threshold=20")
        assert [p["id"] for p in r.json()] == [3]


@pytest.mark.asyncio
async def test_trash_requires_confirmation(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    await _seed(str(tmp_path), [(1, "/g/a.jpg", 5.0)])

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/photos/trash", json={"photo_ids": [1], "confirmed": False})
        assert r.status_code == 400, "deletion without confirmation must be refused"


@pytest.mark.asyncio
async def test_trash_moves_file_backs_up_and_marks_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file leaves its folder via send2trash (mocked to a holding dir so
    the test doesn't touch the real Recycle Bin), an app backup is ALSO made
    (#164 — every delete is backed up, local or network alike), and the row
    goes missing."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)

    photo = tmp_path / "lib" / "shaky.jpg"
    photo.parent.mkdir()
    photo.write_bytes(_blurry_jpeg())
    await _seed(str(tmp_path / "data"), [(1, str(photo), 5.0)])

    holding = tmp_path / "bin"
    holding.mkdir()

    import send2trash as s2t

    def _fake_trash(path: str) -> None:
        os.replace(path, holding / os.path.basename(path))

    monkeypatch.setattr(s2t, "send2trash", _fake_trash)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/photos/trash", json={"photo_ids": [1], "confirmed": True})
    assert r.status_code == 200
    body = r.json()
    assert body["trashed"] == 1 and body["deleted_permanently"] == 0 and body["failed"] == []

    assert not photo.exists(), "the real file must leave its folder"
    assert (holding / "shaky.jpg").exists(), "…into the (mock) recycle bin"

    from services import backup as backup_mod

    hits = list(Path(backup_mod.backup_dir()).rglob("shaky.jpg"))
    assert len(hits) == 1, "an app backup must exist even though send2trash succeeded"

    from db.database import get_db

    async with get_db() as db:
        row = await (
            await db.execute("SELECT missing FROM photos WHERE id = 1")
        ).fetchone()
    assert row is not None and row["missing"] == 1, "trashed photo hidden via #105"


@pytest.mark.asyncio
async def test_trash_falls_back_to_permanent_delete_when_recycle_bin_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#164: local and network folders behave identically — whenever
    send2trash fails, for ANY reason, the file falls back to a permanent
    removal because the app already backed it up first. No special flag."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)

    photo = tmp_path / "lib" / "shot.jpg"  # a perfectly ordinary local file
    photo.parent.mkdir()
    photo.write_bytes(_blurry_jpeg())
    await _seed(str(tmp_path / "data"), [(1, str(photo), 5.0)])

    import send2trash as s2t

    def _no_bin(path: str) -> None:
        raise OSError("locked or unsupported")

    monkeypatch.setattr(s2t, "send2trash", _no_bin)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/photos/trash", json={"photo_ids": [1], "confirmed": True})
    body = r.json()
    assert body["trashed"] == 0
    assert body["deleted_permanently"] == 1
    assert body["failed"] == []
    assert not photo.exists(), "must be removed once backed up"

    from services import backup as backup_mod

    hits = list(Path(backup_mod.backup_dir()).rglob("shot.jpg"))
    assert len(hits) == 1, "permanent removal is only safe because of this backup"

    from db.database import get_db

    async with get_db() as db:
        row = await (
            await db.execute("SELECT missing FROM photos WHERE id = 1")
        ).fetchone()
    assert row is not None and row["missing"] == 1


@pytest.mark.asyncio
async def test_trash_aborts_when_backup_itself_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the app can't make its own safety copy, the delete must not proceed
    at all — the photo stays on disk and visible."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    await _seed(str(tmp_path), [(1, "/g/gone.jpg", 5.0)])

    import api.photos as photos_api

    def _boom(path: str) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(photos_api, "backup_file", _boom)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/photos/trash", json={"photo_ids": [1], "confirmed": True})
    body = r.json()
    assert body["trashed"] == 0 and body["deleted_permanently"] == 0
    assert body["failed"][0]["id"] == 1

    from db.database import get_db

    async with get_db() as db:
        row = await (
            await db.execute("SELECT missing FROM photos WHERE id = 1")
        ).fetchone()
    assert row is not None and row["missing"] == 0, "failed backup must not hide the photo"
