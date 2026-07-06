"""Rotation suggestions API (#160): find sideways photos, rotate originals."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from services import image_cache
from services.rotation import (
    EXIF_ORIENTATION_TO_DEGREES,
    ROTATABLE_EXTENSIONS,
    probe_rotation,
    rotate_original,
)
from services.scanner import is_network_path

router = APIRouter(prefix="/photos", tags=["rotation"])
logger = logging.getLogger(__name__)

_scan_lock = asyncio.Lock()
_scan_running = False


def _entry(r: Any, degrees: int, source: str) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "path": r["path"],
        "folder": os.path.dirname(r["path"]),
        "filename": os.path.basename(r["path"]),
        "file_size": r["file_size"],
        "degrees": degrees,
        "source": source,
        "is_network": is_network_path(r["path"]),
        "rotatable": os.path.splitext(r["path"])[1].lower() in ROTATABLE_EXTENSIONS,
    }


@router.get("/rotation-suggestions")
async def rotation_suggestions() -> list[dict[str, Any]]:
    """Photos that look sideways: face-probe results plus EXIF-only-rotated
    files (upright in tag-aware viewers only). Probed suggestions first."""
    out: list[dict[str, Any]] = []
    async with get_db() as db:
        async with db.execute(
            """
            SELECT id, path, file_size, suggested_rotation, exif_orientation
              FROM photos
             WHERE missing = 0
               AND (suggested_rotation IS NOT NULL
                    OR (exif_orientation IS NOT NULL AND exif_orientation IN (3, 6, 8)))
             ORDER BY suggested_rotation IS NULL, path
            """
        ) as cur:
            async for r in cur:
                if r["suggested_rotation"] is not None:
                    out.append(_entry(r, int(r["suggested_rotation"]), "faces"))
                else:
                    degrees = EXIF_ORIENTATION_TO_DEGREES.get(int(r["exif_orientation"]))
                    if degrees:
                        out.append(_entry(r, degrees, "exif"))
    return out


@router.post("/rotation-scan")
async def start_rotation_scan() -> dict[str, str]:
    """Probe photos with zero detected faces at 90/180/270° (background).

    Sideways photos are exactly the ones upright detection misses; a rotation
    that reveals faces becomes the suggestion. Progress lands in the activity
    log via the standard engine log stream (#126).
    """
    global _scan_running
    async with _scan_lock:
        if _scan_running:
            return {"status": "already_running"}
        _scan_running = True

    async def _run() -> None:
        global _scan_running
        try:
            data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
            tmp_dir = os.path.join(data_dir, "cache", "tmp")
            from config import get_config  # noqa: PLC0415
            from ml.factory import get_recognizer  # noqa: PLC0415

            recognizer = await asyncio.to_thread(get_recognizer, get_config(), data_dir)

            async with get_db() as db:
                async with db.execute(
                    """
                    SELECT id, path, mtime FROM photos
                     WHERE missing = 0 AND rotation_checked = 0
                       AND NOT EXISTS (SELECT 1 FROM faces WHERE photo_id = photos.id)
                    """
                ) as cur:
                    rows = list(await cur.fetchall())

                logger.info("rotation scan: probing %d faceless photo(s)", len(rows))
                found = 0
                for i, r in enumerate(rows, 1):
                    thumb = await asyncio.to_thread(
                        image_cache.warm_and_get_thumb, int(r["id"]), r["path"], int(r["mtime"])
                    )
                    degrees = None
                    if thumb is not None:
                        degrees = await asyncio.to_thread(
                            probe_rotation, thumb, recognizer, tmp_dir
                        )
                    await db.execute(
                        "UPDATE photos SET rotation_checked = 1, suggested_rotation = ? WHERE id = ?",
                        (degrees, int(r["id"])),
                    )
                    if degrees:
                        found += 1
                    if i % 25 == 0:
                        await db.commit()
                        logger.info("rotation scan: %d/%d probed, %d suggestion(s)", i, len(rows), found)
                await db.commit()
                logger.info("rotation scan complete: %d suggestion(s) from %d photo(s)", found, len(rows))
        except Exception:  # noqa: BLE001
            logger.exception("rotation scan failed")
        finally:
            _scan_running = False

    asyncio.create_task(_run())
    return {"status": "started"}


class RotateItem(BaseModel):
    photo_id: int
    degrees: int


class RotateRequest(BaseModel):
    items: list[RotateItem]
    confirmed: bool = False


@router.post("/rotate")
async def rotate_photos(body: RotateRequest) -> dict[str, Any]:
    """Rotate original files (#160) — undoable everywhere alike (#164): the
    pre-rotation original is always backed up in the app first, then either
    recycled (Windows Recycle Bin) or, if that fails, permanently removed —
    safe either way because the app backup already exists."""
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="confirmed must be true")

    rotated = 0
    recycled = 0
    permanent = 0
    failed: list[dict[str, Any]] = []
    async with get_db() as db:
        for item in body.items:
            row = await (
                await db.execute(
                    "SELECT path FROM photos WHERE id = ? AND missing = 0",
                    (item.photo_id,),
                )
            ).fetchone()
            if row is None:
                failed.append({"id": item.photo_id, "error": "not found"})
                continue
            try:
                mode = await asyncio.to_thread(rotate_original, row["path"], item.degrees)
            except (ValueError, OSError) as exc:
                failed.append({"id": item.photo_id, "error": str(exc)})
                continue
            rotated += 1
            if mode == "recycled":
                recycled += 1
            else:
                permanent += 1
            # Re-enter the scan pipeline: new mtime/size, faces and analysis
            # recomputed on the next scan, caches keyed off the new mtime.
            try:
                st = os.stat(row["path"])
                new_mtime, new_size = int(st.st_mtime), int(st.st_size)
            except OSError:
                new_mtime, new_size = int(time.time()), None
            await db.execute(
                """UPDATE photos
                      SET mtime = ?, file_size = ?, faces_extracted = 0,
                          blur_score = NULL, phash = NULL, content_hash = NULL,
                          exif_orientation = 1, suggested_rotation = NULL,
                          rotation_checked = 1
                    WHERE id = ?""",
                (new_mtime, new_size, item.photo_id),
            )
        await db.commit()

    logger.info(
        "rotated %d photo(s): %d original(s) recycled, %d overwritten on network (%d failed)",
        rotated, recycled, permanent, len(failed),
    )
    return {"rotated": rotated, "recycled": recycled, "permanent": permanent, "failed": failed}
