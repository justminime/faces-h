"""File scanner service.

Walks a directory tree, discovers supported images, persists records to SQLite,
runs face detection on new/unindexed photos, and streams progress events via a
caller-supplied broadcast callback.

Incremental: files already recorded with the same mtime are skipped.
Network-safe: UNC paths (\\\\server\\share) and mapped network drives are
detected automatically. On disconnection the scanner pauses, retries up to
three times, then emits a drive_offline event and stops cleanly without
corrupting the DB. The app NEVER writes to, moves, or deletes any photo file.
"""

import asyncio
import logging
import os
import sys
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

_PIL_VALIDATED: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif"}
)

# How many consecutive per-file OS errors on a network path before we treat
# the drive as offline and stop the scan.
_NETWORK_ERROR_LIMIT = 5
# Seconds to wait between reconnection attempts when a network drive drops.
_NETWORK_RETRY_DELAY = 5.0
_NETWORK_RETRY_ATTEMPTS = 3

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None]]
ProcessResult = Literal["ok", "skip", "error"]


@dataclass
class ScanStatus:
    running: bool = False
    paused: bool = False
    root_path: str = ""
    total: int = 0
    scanned: int = 0
    skipped: int = 0
    error_count: int = 0
    # Detections dropped by the OD-04 size/confidence floor this scan (#111).
    skipped_faces: int = 0
    start_time: float = 0.0

    def eta_seconds(self) -> int:
        # Rate counts skipped files too — incremental rescans are dominated by
        # near-instant skips, and a scanned-only rate inflated the ETA by
        # orders of magnitude on mostly-unchanged libraries (#113).
        processed = self.scanned + self.skipped
        if processed == 0:
            return 0
        elapsed = time.monotonic() - self.start_time
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = max(0, self.total - processed - self.error_count)
        return int(remaining / rate) if rate > 0 else 0


_status = ScanStatus()


def get_status() -> ScanStatus:
    return _status


def reset_status() -> None:
    global _status
    _status = ScanStatus()


def begin_scan(root_path: str) -> None:
    """Mark a scan as running, synchronously.

    Called from the request handler BEFORE the scan task is scheduled: the
    old pattern set `running` inside the task, so two rapid /scan/start
    calls could both pass the already-running check (#113).
    """
    global _status
    _status = ScanStatus(running=True, root_path=root_path, start_time=time.monotonic())


def end_scan() -> None:
    """Mark the current scan finished. Callers using preset=True own this."""
    _status.running = False


# ── Network path detection ────────────────────────────────────────────────────

def is_network_path(path: str) -> bool:
    """Return True if path is on a network share (UNC or mapped network drive).

    Purely a classification helper — never reads from the path itself.
    """
    # UNC paths: \\server\share or //server/share
    if path.startswith(("\\\\", "//")):
        return True
    # On Windows, check the drive-type of the root letter via Win32 API.
    if sys.platform == "win32" and len(path) >= 2 and path[1] == ":":
        try:
            import ctypes
            DRIVE_REMOTE = 4
            drive_root = path[:3] if len(path) >= 3 else path[:2] + "\\"
            return int(ctypes.windll.kernel32.GetDriveTypeW(drive_root)) == DRIVE_REMOTE  # type: ignore[attr-defined]
        except Exception:
            pass
    return False


def check_reachable(path: str) -> bool:
    """Return True if path exists and is accessible right now."""
    try:
        return os.path.isdir(path)
    except OSError:
        return False


# ── Directory walk ────────────────────────────────────────────────────────────

def _walk_onerror(exc: OSError) -> None:
    """Called by os.walk when a directory can't be read — log and continue."""
    logger.warning("Cannot read directory during walk: %s", exc)


def _collect_files(root: str) -> list[str]:
    """Synchronously walk root and return all supported image paths.

    Per-directory OSErrors (e.g. permission denied on a sub-folder) are logged
    and skipped; the walk continues. If the root itself is unreachable the
    function returns an empty list rather than raising.
    """
    result: list[str] = []
    try:
        for dirpath, _, filenames in os.walk(root, onerror=_walk_onerror):
            for name in filenames:
                if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                    result.append(os.path.join(dirpath, name))
    except OSError as exc:
        logger.warning("Cannot walk root %s: %s", root, exc)
    return result


# ── Image helpers ─────────────────────────────────────────────────────────────

def _open_image(path: str) -> bool:
    from PIL import Image
    try:
        with Image.open(path):
            pass
        return True
    except Exception:
        return False


def _read_taken_at(path: str) -> int | None:
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
            return None
        raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal) or exif.get(
            "0th", {}
        ).get(piexif.ImageIFD.DateTime)
        if not raw:
            return None
        dt_str = raw.decode("ascii") if isinstance(raw, bytes) else str(raw)
        return int(datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").timestamp())
    except Exception:
        return None


# ── Per-file processing ───────────────────────────────────────────────────────

async def _process_file(path: str, db: aiosqlite.Connection) -> ProcessResult:
    """Insert/update one image in the DB. Never modifies the source file."""
    try:
        mtime = int(os.path.getmtime(path))
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", path, exc)
        return "error"

    cur = await db.execute(
        "SELECT id FROM photos WHERE path=? AND mtime=?", (path, mtime)
    )
    if await cur.fetchone():
        return "skip"

    ext = Path(path).suffix.lower()
    if ext in _PIL_VALIDATED:
        valid = await asyncio.to_thread(_open_image, path)
        if not valid:
            logger.warning("Skipping corrupt image: %s", path)
            return "error"

    taken_at = await asyncio.to_thread(_read_taken_at, path)

    try:
        # A changed file invalidates any previously extracted faces, so the
        # extraction-complete flag is reset; _extract_faces sets it back to 1
        # once the new faces are fully committed.
        await db.execute(
            """
            INSERT INTO photos (path, mtime, taken_at)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE
                SET mtime           = excluded.mtime,
                    taken_at        = excluded.taken_at,
                    faces_extracted = 0
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
    """Detect and persist all faces for one photo, then mark it complete.

    Any pre-existing face rows for the photo are stale — partial rows left by
    a mid-extraction crash, or faces from an older version of a modified file
    — and are deleted before the new detections are inserted, so a rescan
    never duplicates faces (#104). Centroids of the people who lost faces are
    rebuilt afterwards so deleted embeddings stop voting (#104).

    `photos.faces_extracted` is set to 1 only after ALL faces are committed —
    including when zero faces were detected. If detection fails, the flag
    stays 0 and the photo is retried on the next scan (#90).
    """
    try:
        results = await asyncio.to_thread(recognizer.detect_and_embed, path)
    except Exception as exc:
        logger.warning("detect_and_embed failed for %s: %s", path, exc)
        return

    # OD-04 (#111): drop detections that are too small to embed meaningfully
    # or below the detector-confidence floor; junk embeddings otherwise seed
    # singleton clusters and pollute the uncertain queue. size_px == 0 means
    # the backend didn't report a pixel size — exempt from the size filter.
    from config import get_config  # noqa: PLC0415
    cfg = get_config()
    kept: list[Any] = []
    for face in results:
        size_px = float(getattr(face, "size_px", 0.0) or 0.0)
        if 0.0 < size_px < cfg.min_face_px:
            _status.skipped_faces += 1
            continue
        if face.detection_confidence < cfg.min_detection_confidence:
            _status.skipped_faces += 1
            continue
        kept.append(face)
    if len(kept) < len(results):
        logger.debug(
            "skipped %d small/low-confidence detection(s) in %s",
            len(results) - len(kept), path,
        )
    results = kept

    # Clear stale face rows for this photo, remembering whose centroids are
    # affected. corrections.face_id has an FK to faces, so matching correction
    # rows must go first or the DELETE aborts with foreign_keys=ON.
    cur = await db.execute(
        "SELECT DISTINCT person_id FROM faces WHERE photo_id = ? AND person_id IS NOT NULL",
        (photo_id,),
    )
    affected_people = [int(row["person_id"]) for row in await cur.fetchall()]
    await db.execute(
        "DELETE FROM corrections WHERE face_id IN (SELECT id FROM faces WHERE photo_id = ?)",
        (photo_id,),
    )
    await db.execute("DELETE FROM faces WHERE photo_id = ?", (photo_id,))

    for face in results:
        x, y, w, h = face.bbox
        cur = await db.execute(
            """INSERT INTO faces
               (photo_id, bbox_x, bbox_y, bbox_w, bbox_h, detection_conf, embedding, assign_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed')""",
            (photo_id, x, y, w, h, face.detection_confidence,
             face.embedding.astype(np.float32).tobytes()),
        )
        assert cur.lastrowid is not None
        await clustering.assign_face(int(cur.lastrowid), face.embedding, db, commit=False)

    for person_id in affected_people:
        await clustering.rebuild_centroid(person_id, db, commit=False)

    await db.execute(
        "UPDATE photos SET faces_extracted = 1 WHERE id = ?", (photo_id,)
    )
    # One commit per photo (#113): the stale-row deletes, all face inserts,
    # assignments, and the extraction flag land atomically — a crash anywhere
    # above rolls back to flag 0 and the photo is retried cleanly (#90).
    await db.commit()


# ── Main scan loop ────────────────────────────────────────────────────────────

async def run_scan(
    root_path: str,
    broadcast: BroadcastFn,
    db: aiosqlite.Connection,
    preset: bool = False,
) -> None:
    """Walk root_path, persist new/changed images to DB, run face detection.

    Network drives: if root_path is on a network share and is unreachable at
    scan start, emits drive_offline and returns immediately. If the drive
    disconnects mid-scan, pauses and retries up to three times before emitting
    drive_offline and stopping cleanly. The DB is never left in a corrupt state.
    """
    global _status
    network = is_network_path(root_path)
    if preset:
        # Caller already ran begin_scan() and owns the running flag (end_scan)
        # — keep accumulating totals so a multi-root rescan reports coherent
        # aggregate progress instead of resetting per root (#113).
        _status.running = True
        _status.root_path = root_path
    else:
        _status = ScanStatus(running=True, root_path=root_path, start_time=time.monotonic())

    # Reachability check — bail early rather than hanging on an offline share.
    if not check_reachable(root_path):
        logger.warning("run_scan: root unreachable at start: %s", root_path)
        if not preset:
            _status.running = False
        await broadcast({"type": "drive_offline", "path": root_path})
        return

    paths = await asyncio.to_thread(_collect_files, root_path)
    _status.total += len(paths)

    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    recognizer = None
    clustering = None
    try:
        from config import get_config  # noqa: PLC0415
        from ml.factory import get_recognizer  # noqa: PLC0415
        from services.clustering import ClusteringService  # noqa: PLC0415
        recognizer = await asyncio.to_thread(get_recognizer, get_config(), data_dir)
        clustering = ClusteringService()
        logger.info("face recognizer loaded — face detection active")
    except Exception as exc:
        logger.warning("face recognizer unavailable, metadata-only scan: %s", exc)

    unindexed: dict[str, int] = {}
    if recognizer is not None:
        cur = await db.execute(
            "SELECT id, path FROM photos WHERE faces_extracted = 0"
        )
        unindexed = {row["path"]: int(row["id"]) for row in await cur.fetchall()}

    consecutive_errors = 0

    for i, path in enumerate(paths, 1):
        while _status.paused:
            await asyncio.sleep(0.1)

        result = await _process_file(path, db)

        if result == "ok":
            _status.scanned += 1
            consecutive_errors = 0
            if recognizer is not None:
                row = await (await db.execute(
                    "SELECT id FROM photos WHERE path = ?", (path,)
                )).fetchone()
                if row:
                    await _extract_faces(path, int(row["id"]), recognizer, clustering, db)
        elif result == "skip":
            _status.skipped += 1
            consecutive_errors = 0
            if recognizer is not None and path in unindexed:
                await _extract_faces(path, unindexed[path], recognizer, clustering, db)
        else:
            _status.error_count += 1
            consecutive_errors += 1

            # On network drives, many consecutive errors likely means the share
            # dropped. Pause and retry before giving up.
            if network and consecutive_errors >= _NETWORK_ERROR_LIMIT:
                logger.warning(
                    "%d consecutive errors on network path — checking reachability", consecutive_errors
                )
                recovered = False
                for attempt in range(1, _NETWORK_RETRY_ATTEMPTS + 1):
                    logger.info("Network reconnect attempt %d/%d for %s", attempt, _NETWORK_RETRY_ATTEMPTS, root_path)
                    await asyncio.sleep(_NETWORK_RETRY_DELAY)
                    if check_reachable(root_path):
                        logger.info("Network path reachable again — resuming scan")
                        consecutive_errors = 0
                        recovered = True
                        break
                if not recovered:
                    logger.error("Network path offline after %d retries: %s", _NETWORK_RETRY_ATTEMPTS, root_path)
                    if not preset:
                        _status.running = False
                    await broadcast({"type": "drive_offline", "path": root_path})
                    return

        if i % 10 == 0 or i == len(paths):
            await broadcast(
                {
                    "type": "scan_progress",
                    "scanned": _status.scanned,
                    "total": _status.total,
                    "eta_seconds": _status.eta_seconds(),
                    "current_file": os.path.basename(path),
                }
            )

        if i % 50 == 0:
            await asyncio.sleep(0)

    if not preset:
        _status.running = False
    if _status.skipped_faces:
        logger.info("scan skipped %d too-small/low-confidence face detection(s)", _status.skipped_faces)
    await broadcast({
        "type": "scan_complete",
        "scanned": _status.scanned,
        "total": _status.total,
        "skipped_faces": _status.skipped_faces,
    })
