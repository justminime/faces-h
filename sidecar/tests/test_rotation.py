"""Tests for rotation suggestions and safe original rotation (#160/#161)."""

import io
import os
import time
from pathlib import Path

import piexif
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from services import backup, rotation


def _jpeg_with_exif(path: Path, size: tuple[int, int] = (80, 40), orientation: int = 6) -> None:
    img = Image.new("RGB", size, (90, 120, 200))
    exif = piexif.dump(
        {"0th": {piexif.ImageIFD.Orientation: orientation, piexif.ImageIFD.Make: b"testcam"}}
    )
    img.save(path, format="JPEG", exif=exif)


# ---------------------------------------------------------------------------
# rotate_original
# ---------------------------------------------------------------------------


def test_rotate_original_pixels_exif_recycle_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """90° CW: dimensions swap, EXIF preserved with orientation reset to 1;
    the untouched original lands in the (mocked) Recycle Bin AND an app
    backup is made too (#164 — every rotation is backed up, local included)."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)

    photo = tmp_path / "sideways.jpg"
    _jpeg_with_exif(photo, size=(80, 40), orientation=6)
    original_bytes = photo.read_bytes()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    import send2trash as s2t

    monkeypatch.setattr(
        s2t, "send2trash", lambda p: os.replace(p, bin_dir / os.path.basename(p))
    )

    mode = rotation.rotate_original(str(photo), 90)
    assert mode == "recycled"

    with Image.open(photo) as img:
        assert img.size == (40, 80), "90° must swap dimensions"
        exif = piexif.load(img.info["exif"])
        assert exif["0th"][piexif.ImageIFD.Orientation] == 1, "orientation reset"
        assert exif["0th"][piexif.ImageIFD.Make] == b"testcam", "EXIF preserved"

    recycled_copy = bin_dir / "sideways.jpg"
    assert recycled_copy.read_bytes() == original_bytes, "original untouched in the Bin"

    app_backups = list(Path(backup.backup_dir()).rglob("sideways.jpg"))
    assert len(app_backups) == 1, "an app backup must exist alongside the Recycle Bin copy"
    assert app_backups[0].read_bytes() == original_bytes


def test_rotate_refuses_unsupported_format(tmp_path: Path) -> None:
    raw = tmp_path / "shot.nef"
    raw.write_bytes(b"rawdata")
    with pytest.raises(ValueError, match="not safely rewritable"):
        rotation.rotate_original(str(raw), 90)
    assert raw.read_bytes() == b"rawdata"


def test_rotate_aborts_when_backup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the app can't make its own safety copy, rotation must not proceed —
    the file on disk stays byte-identical and no temp file lingers."""
    photo = tmp_path / "local.jpg"
    _jpeg_with_exif(photo)
    before = photo.read_bytes()

    monkeypatch.setattr(
        rotation, "backup_file", lambda p: (_ for _ in ()).throw(OSError("disk full"))
    )

    with pytest.raises(OSError, match="could not back up"):
        rotation.rotate_original(str(photo), 90)
    assert photo.read_bytes() == before
    assert not (tmp_path / "local.jpg.rotating.tmp").exists()


def test_rotate_falls_back_to_permanent_delete_with_mirrored_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#164: local and network folders behave identically — whenever
    send2trash fails, for ANY reason, rotation falls back to permanently
    removing the original because it was already backed up (mirroring the
    source folder structure) first."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)

    photo = tmp_path / "share" / "album" / "pic.jpg"
    photo.parent.mkdir(parents=True)
    _jpeg_with_exif(photo, size=(60, 30))
    before = photo.read_bytes()

    import send2trash as s2t

    monkeypatch.setattr(s2t, "send2trash", lambda p: (_ for _ in ()).throw(OSError("no bin")))

    mode = rotation.rotate_original(str(photo), 90)
    assert mode == "permanent"
    with Image.open(photo) as img:
        assert img.size == (30, 60)

    # Mirrored structure: .../trash-backup/<drive-or-share>/.../album/pic.jpg
    hits = list(Path(backup.backup_dir()).rglob("pic.jpg"))
    assert len(hits) == 1
    assert hits[0].parent.name == "album", "backup mirrors the folder structure"
    assert hits[0].read_bytes() == before


# ---------------------------------------------------------------------------
# backup retention
# ---------------------------------------------------------------------------


def test_purge_removes_only_expired_and_empty_dirs(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    old_file = Path(backup.backup_dir()) / "nas" / "old" / "a.jpg"
    new_file = Path(backup.backup_dir()) / "nas" / "new" / "b.jpg"
    old_file.parent.mkdir(parents=True)
    new_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"x")
    new_file.write_bytes(b"y")
    expired = time.time() - 8 * 86_400
    os.utime(old_file, (expired, expired))

    removed = backup.purge_old_backups(retention_days=7)
    assert removed == 1
    assert not old_file.exists()
    assert not old_file.parent.exists(), "emptied folders are cleaned up"
    assert new_file.exists(), "fresh backups stay"


# ---------------------------------------------------------------------------
# suggestions + endpoints
# ---------------------------------------------------------------------------


class _RotationAwareRecognizer:
    """Fake recognizer: 'detects' one face only in the 90°-rotated probe."""

    def detect_and_embed(self, image_path: str) -> list[object]:
        return [object()] if "probe_90" in image_path else []


def test_probe_rotation_finds_the_right_angle(tmp_path: Path) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 10, 10)).save(buf, format="JPEG")
    degrees = rotation.probe_rotation(buf.getvalue(), _RotationAwareRecognizer(), str(tmp_path))
    assert degrees == 90
    assert list(tmp_path.glob("probe_*.jpg")) == [], "probe temp files cleaned up"


@pytest.mark.asyncio
async def test_suggestions_endpoint_exif_and_probe(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO photos (id, path, mtime, exif_orientation) VALUES (1, 'C:/g/tagged.jpg', 1, 6)"
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, suggested_rotation, rotation_checked)"
            " VALUES (2, 'C:/g/probed.jpg', 1, 270, 1)"
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, exif_orientation) VALUES (3, 'C:/g/fine.jpg', 1, 1)"
        )
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/photos/rotation-suggestions")
    assert r.status_code == 200
    body = r.json()
    by_id = {p["id"]: p for p in body}
    assert set(by_id) == {1, 2}, "upright photos are not suggested"
    assert by_id[1]["degrees"] == 90 and by_id[1]["source"] == "exif"
    assert by_id[2]["degrees"] == 270 and by_id[2]["source"] == "faces"
    assert by_id[1]["filename"] == "tagged.jpg" and by_id[1]["folder"].endswith("g")
    assert body[0]["id"] == 2, "face-probed suggestions come first"


@pytest.mark.asyncio
async def test_rotate_endpoint_updates_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)
    photo = tmp_path / "lib" / "s.jpg"
    photo.parent.mkdir()
    _jpeg_with_exif(photo, size=(80, 40), orientation=6)

    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO photos (id, path, mtime, exif_orientation, faces_extracted, blur_score)"
            " VALUES (1, ?, 1, 6, 1, 42.0)",
            (str(photo),),
        )
        await db.commit()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    import send2trash as s2t

    monkeypatch.setattr(
        s2t, "send2trash", lambda p: os.replace(p, bin_dir / os.path.basename(p))
    )

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/photos/rotate", json={"items": [{"photo_id": 1, "degrees": 90}], "confirmed": False})
        assert r.status_code == 400, "rotation without confirmation must be refused"

        r = await ac.post(
            "/photos/rotate",
            json={"items": [{"photo_id": 1, "degrees": 90}], "confirmed": True},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["rotated"] == 1 and body["recycled"] == 1 and body["failed"] == []

    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT faces_extracted, blur_score, suggested_rotation, exif_orientation"
                " FROM photos WHERE id = 1"
            )
        ).fetchone()
    assert row is not None
    assert row["faces_extracted"] == 0, "rotated photo re-enters the scan pipeline"
    assert row["blur_score"] is None
    assert row["suggested_rotation"] is None
    assert row["exif_orientation"] == 1


# ---------------------------------------------------------------------------
# Backup manifest + restore (#161/#162)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_list_and_restore_roundtrip(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(str(tmp_path / "data"), exist_ok=True)

    original = tmp_path / "share" / "album" / "keeper.jpg"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original-bytes")

    rel_backup = backup.backup_file(str(original))
    original.unlink()  # simulate the deletion that followed the backup

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/backups")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["filename"] == "keeper.jpg"
        assert entry["original_path"] == str(original)
        assert entry["expires_in_days"] > 6

        r = await ac.post("/backups/restore", json={"backup": entry["backup"], "confirmed": False})
        assert r.status_code == 400

        r = await ac.post("/backups/restore", json={"backup": entry["backup"], "confirmed": True})
        assert r.status_code == 200

    assert original.read_bytes() == b"original-bytes", "restored to the original location"
    assert Path(rel_backup).exists(), "backup copy kept until natural expiry"


@pytest.mark.asyncio
async def test_restore_unknown_backup_404(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/backups/restore", json={"backup": "nope/x.jpg", "confirmed": True})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_scan_commits_per_photo_not_in_one_long_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for #174: each photo's per-thumbnail decode + ML probe
    can take real time, so the scan must commit after every row instead of
    batching commits — otherwise it holds the write lock long enough that an
    unrelated concurrent write (e.g. dismissing a queue face) fails with
    "database is locked"."""
    import asyncio
    import time as time_mod

    import ml.factory as ml_factory
    import api.rotation as rotation_api

    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    from db.database import get_db

    n_photos = 4
    # Simulates real decode + ML inference time. Generous on purpose: the
    # assertion below only needs a large gap between "commits every photo"
    # (should clear in well under this even under heavy machine load) and
    # "commits every 25" (would need n_photos * per_photo_delay ≈ 8s here) —
    # it's not measuring an exact duration.
    per_photo_delay = 2.0
    async with get_db() as db:
        for i in range(1, n_photos + 1):
            await db.execute(
                "INSERT INTO photos (id, path, mtime) VALUES (?, ?, 1)",
                (i, f"C:/lib/faceless_{i}.jpg"),
            )
        await db.execute(
            "INSERT INTO people (id, name, created_at) VALUES (1, 'Alice', 0)"
        )
        await db.commit()

    monkeypatch.setattr(ml_factory, "get_recognizer", lambda *a, **kw: object())
    monkeypatch.setattr(
        rotation_api.image_cache, "warm_and_get_thumb", lambda *a, **kw: b"fake"
    )

    def _slow_probe(thumb: bytes, recognizer: object, tmp_dir: str) -> int | None:
        time_mod.sleep(per_photo_delay)  # runs in a worker thread via to_thread
        return None

    monkeypatch.setattr(rotation_api, "probe_rotation", _slow_probe)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/photos/rotation-scan")
        assert r.status_code == 200

        # Give the scan a moment to start and get into its per-photo loop.
        await asyncio.sleep(per_photo_delay * 1.5)

        # A genuine concurrent WRITE from a fresh connection — unrelated to
        # the scan's own rows, but it still needs the single WAL writer lock.
        start = time_mod.monotonic()
        async with get_db() as concurrent_conn:
            await concurrent_conn.execute(
                "UPDATE people SET name = 'Alice (updated)' WHERE id = 1"
            )
            await concurrent_conn.commit()
        elapsed = time_mod.monotonic() - start

    assert elapsed < per_photo_delay, (
        f"concurrent write took {elapsed:.2f}s — the scan is holding the "
        "write lock across multiple photos instead of committing each one"
    )

    # Let the scan finish, then confirm it actually completed its work.
    for _ in range(100):
        async with get_db() as db:
            row = await (
                await db.execute(
                    "SELECT COUNT(*) AS n FROM photos WHERE rotation_checked = 1"
                )
            ).fetchone()
        if row is not None and int(row["n"]) == n_photos:
            break
        await asyncio.sleep(0.1)
    assert row is not None and int(row["n"]) == n_photos
