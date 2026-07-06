"""Photo image serving endpoints."""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from config import get_config

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from db.database import get_db
from services import image_cache

router = APIRouter(prefix="/photos", tags=["photos"])
logger = logging.getLogger(__name__)

_MAX_THUMB_PX = 1024


@router.get("/{photo_id}/thumbnail")
async def get_photo_thumbnail(
    photo_id: int,
    size: int = Query(256, ge=16, le=_MAX_THUMB_PX),
) -> Response:
    """Serve a downscaled JPEG thumbnail of a photo.

    Generated thumbnails are cached on disk keyed by the photo's DB mtime
    (#114), so repeat requests skip decoding the full-size original entirely.
    The source file is opened read-only — never modified, moved, or deleted —
    so this respects the project rule against touching photo files.
    """
    try:
        import PIL  # type: ignore[import-untyped]  # noqa: F401
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Pillow not installed") from exc

    async with get_db() as db:
        row = await (
            await db.execute("SELECT path, mtime FROM photos WHERE id = ?", (photo_id,))
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")

    cache_path = image_cache.cache_key(
        "thumbs", photo_id, int(row["mtime"]), variant=str(size)
    )
    cached = image_cache.get(cache_path)
    if cached is not None:
        return Response(
            content=cached,
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=86400", "X-Cache": "hit"},
        )

    try:
        # Worker thread: PIL in the async handler serialized every image
        # request behind one core and starved the rest of the API (#150).
        data = await asyncio.to_thread(
            image_cache.generate_thumbnail_bytes, row["path"], size
        )
        image_cache.put(cache_path, data)
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=86400", "X-Cache": "miss"},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Photo file missing") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not generate thumbnail") from exc


@router.get("/blurry")
async def list_blurry_photos(
    limit: int = 100,
    offset: int = 0,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Photos whose sharpness score is below the cutoff (#154), most blurred
    first. `threshold` (the UI slider) overrides config.blur_threshold. NULL
    scores (not yet scanned since the feature shipped) are excluded — they
    get scored on their next scan."""
    if threshold is None or threshold <= 0:
        threshold = get_config().blur_threshold
    async with get_db() as db:
        async with db.execute(
            """
            SELECT id, path, taken_at, blur_score
              FROM photos
             WHERE missing = 0
               AND blur_score IS NOT NULL
               AND blur_score < ?
             ORDER BY blur_score ASC
             LIMIT ? OFFSET ?
            """,
            (threshold, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "id": int(r["id"]),
            "path": r["path"],
            "taken_at": r["taken_at"],
            "blur_score": r["blur_score"],
        }
        for r in rows
    ]


class TrashRequest(BaseModel):
    photo_ids: list[int]
    confirmed: bool = False


@router.post("/trash")
async def trash_photos(body: TrashRequest) -> dict[str, Any]:
    """Move photos to the OS Recycle Bin — the ONLY file-modifying action in
    the product (#154). Requires explicit confirmation; never a permanent
    delete. Trashed photos are marked missing (#105), so restoring the file
    from the Recycle Bin + rescanning revives it with its faces intact.
    """
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="confirmed must be true")
    if not body.photo_ids:
        return {"trashed": 0, "failed": []}

    try:
        from send2trash import send2trash  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="send2trash not installed") from exc

    trashed = 0
    failed: list[dict[str, Any]] = []
    async with get_db() as db:
        for photo_id in body.photo_ids:
            row = await (
                await db.execute(
                    "SELECT path FROM photos WHERE id = ? AND missing = 0",
                    (photo_id,),
                )
            ).fetchone()
            if row is None:
                failed.append({"id": photo_id, "error": "not found"})
                continue
            try:
                await asyncio.to_thread(send2trash, row["path"])
            except Exception as exc:  # noqa: BLE001 — report per file, keep going
                logger.warning("recycle-bin move failed for %s: %s", row["path"], exc)
                failed.append({"id": photo_id, "error": str(exc.__class__.__name__)})
                continue
            await db.execute(
                "UPDATE photos SET missing = 1 WHERE id = ?", (photo_id,)
            )
            trashed += 1
        await db.commit()

    logger.info("moved %d photo(s) to the Recycle Bin (%d failed)", trashed, len(failed))
    return {"trashed": trashed, "failed": failed}
