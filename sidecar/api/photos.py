"""Photo image serving endpoints."""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from db.database import get_db
from services import image_cache

router = APIRouter(prefix="/photos", tags=["photos"])

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
