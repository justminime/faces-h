"""File scanner service.

Walks a directory tree, discovers supported images, persists records to SQLite,
runs face detection on new/unindexed photos, and streams progress events via a
caller-supplied broadcast callback.
Incremental: files already recorded with the same mtime are skipped without
re-opening or re-inserting them. Face detection is skipped for photos that
already have face records.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import aiosqlite
import numpy as np
import piexif

try:
    import pillow_heif  # type: ignore[import-untyped]

    pillow_heif.register_heif_opener()
    _HEIC_SUPPORTED = True
except ImportError:
    _HEIC_SUPPORTED = False

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".raw", ".cr2", ".nef", ".arw", ".dng"}
)

# Formats where PIL can validate image integrity via header read
_PIL_VALIDATED: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif"}
)

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None]]
ProcessResult = Literal["ok", "skip", "error"]


@dataclass
class ScanStatus:
    running: bool = False
    paused: bool = False
    root_path: str = ""
    total: int = 0
    scanned: int = 0    # newly inserted or updated
    skipped: int = 0    # already up-to-date (incremental)
    error_count: int = 0
    start_time: float = 0.0

    def eta_seconds(self) -> int:
        """Estimated seconds remaining based on current throughput."""
        if self.scanned == 0:
            return 0
        elapsed = time.monotonic() - self.start_time
        rate = self.scanned / elapsed if elapsed > 0 else 0
        return int((self.total - self.scanned - self.skipped) / rate) if rate > 0 else 0


_status = ScanStatus()


def get_status() -> ScanStatus:
    return _status


def reset_status() -> None:
    """Reset scan state. Only for use in tests."""
    global _status
    _status = ScanStatus()


def _collect_files(root: str) -> list[str]:
    """Synchronously walk root and return all supported image paths."""
    result: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                result.append(os.path.join(dirpath, name))
    return result


def _open_image(path: str) -> bool:
    """Return True if path can be opened as an image (header check only)."""
    from PIL import Image  # lazy import — PIL has startup cost

    try:
        with Image.open(path):
            pass
        return True
    except Exception:
        return False


def _read_taken_at(path: str) -> int | None:
    """Extract DateTimeOriginal from EXIF. Returns Unix timestamp or None."""
    ext = Path(path).suffix.lower()
    try:
        if ext in {".heic", ".heif"}:
            from PIL import Image

            with Image.open(path) as img:
                exif_bytes = img.info.get("exif", b"")
            if not exif_bytes:
                return None
            exif = piexif.load(exif_bytes)
        elif ext in {".jpg", ".jpeg", ".tiff", ".tif"}:
            exif = piexif.load(path)
        else:
            return None  # PNG and RAW formats carry no piexif-accessible EXIF

        raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal) or exif.get(
            "0th", {}
        ).get(piexif.ImageIFD.DateTime)
        if not raw:
            return None
        dt_str = raw.decode("ascii") if isinstance(raw, bytes) else str(raw)
        return int(datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").timestamp())
    except Exception:
        return None


async def _process_file(path: str, db: aiosqlite.Connection) -> ProcessResult:
    """Process one image file against the database.

    Returns 'skip' if already up-to-date, 'ok' if inserted/updated,
    or 'error' if the file is corrupt or the insert fails.
    """
    try:
        mtime = int(os.path.getmtime(path))
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", path, exc)
        return "error"

    # Incremental check — skip if path+mtime already recorded
    cur = await db.execute(
        "SELECT id FROM photos WHERE path=? AND mtime=?", (path, mtime)
    )
    if await cur.fetchone():
        return "skip"

    # Validate image integrity for PIL-supported formats
    ext = Path(path).suffix.lower()
    if ext in _PIL_VALIDATED:
        valid = await asyncio.to_thread(_open_image, path)
        if not valid:
            logger.warning("Skipping corrupt image: %s", path)
            return "error"

    taken_at = await asyncio.to_thread(_read_taken_at, path)

    try:
        await db.execute(
            """
            INSERT INTO photos (path, mtime, taken_at)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE
                SET mtime    = excluded.mtime,
                    taken_at = excluded.taken_at
            """,
            (path, mtime, taken_at),
        )
        await db.commit()
    except Exception as exc:
        logger.warning("DB insert failed for %s: %s", path, exc)
        return "error"

    return "ok"


async def _extract_faces(
    path: str,
    photo_id: int,
    recognizer: Any,
    clustering: Any,
    db: aiosqlite.Connection,
) -> None:
    """Detect faces in path, insert into DB, run clustering assignment."""
    try:
        results = await asyncio.to_thread(recognizer.detect_and_embed, path)
    except Exception as exc:
        logger.warning("detect_and_embed failed for %s: %s", path, exc)
        return

    for face in results:
        x, y, w, h = face.bbox
        cur = await db.execute(
            """INSERT INTO faces
               (photo_id, bbox_x, bbox_y, bbox_w, bbox_h, detection_conf, embedding, assign_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed')""",
            (photo_id, x, y, w, h, face.detection_confidence,
             face.embedding.astype(np.float32).tobytes()),
        )
        await db.commit()
        await clustering.assign_face(int(cur.lastrowid), face.embedding, db)


async def run_scan(
    root_path: str,
    broadcast: BroadcastFn,
    db: aiosqlite.Connection,
) -> None:
    """Walk root_path, record new/changed images in db, run face detection, broadcast progress."""
    global _status
    _status = ScanStatus(running=True, root_path=root_path, start_time=time.monotonic())

    paths = await asyncio.to_thread(_collect_files, root_path)
    _status.total = len(paths)

    # Load the face recognizer once for the whole scan (expensive ONNX init).
    # Falls back to metadata-only mode if the model hasn't been downloaded yet.
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    recognizer = None
    clustering = None
    try:
        from ml.insightface_recognizer import InsightFaceRecognizer  # noqa: PLC0415
        from services.clustering import ClusteringService  # noqa: PLC0415
        recognizer = await asyncio.to_thread(InsightFaceRecognizer, data_dir)
        clustering = ClusteringService()
        logger.info("face recognizer loaded — face detection active")
    except Exception as exc:
        logger.warning("face recognizer unavailable, metadata-only scan: %s", exc)

    # Pre-fetch photos that exist in the DB but have no face records yet so
    # that a rescan after an earlier metadata-only pass fills in face data.
    unindexed: dict[str, int] = {}
    if recognizer is not None:
        cur = await db.execute(
            """SELECT id, path FROM photos
               WHERE NOT EXISTS (SELECT 1 FROM faces WHERE photo_id = photos.id)"""
        )
        unindexed = {row["path"]: int(row["id"]) for row in await cur.fetchall()}

    for i, path in enumerate(paths, 1):
        while _status.paused:
            await asyncio.sleep(0.1)

        result = await _process_file(path, db)
        if result == "ok":
            _status.scanned += 1
            if recognizer is not None:
                row = await (await db.execute(
                    "SELECT id FROM photos WHERE path = ?", (path,)
                )).fetchone()
                if row:
                    await _extract_faces(path, int(row["id"]), recognizer, clustering, db)
        elif result == "skip":
            _status.skipped += 1
            # Run face detection on previously-scanned photos that were missed
            # (e.g., a prior scan ran before the model was downloaded).
            if recognizer is not None and path in unindexed:
                await _extract_faces(path, unindexed[path], recognizer, clustering, db)
        else:
            _status.error_count += 1

        # Broadcast every 100 files and at the very end
        if i % 100 == 0 or i == len(paths):
            await broadcast(
                {
                    "type": "scan_progress",
                    "scanned": _status.scanned,
                    "total": _status.total,
                    "eta_seconds": _status.eta_seconds(),
                }
            )

        # Yield to event loop to avoid starving other coroutines
        if i % 50 == 0:
            await asyncio.sleep(0)

    _status.running = False
    await broadcast({"type": "scan_complete", "scanned": _status.scanned, "total": _status.total})
