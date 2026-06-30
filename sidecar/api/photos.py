"""Photo image serving endpoints."""

import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from db.database import get_db

router = APIRouter(prefix="/photos", tags=["photos"])

_MAX_THUMB_PX = 1024


@router.get("/{photo_id}/thumbnail")
async def get_photo_thumbnail(
    photo_id: int,
    size: int = Query(256, ge=16, le=_MAX_THUMB_PX),
) -> Response:
    """Serve a downscaled JPEG thumbnail of a photo.

    The source file is opened read-only — never modified, moved, or deleted —
    so this respects the project rule against touching photo files.
    """
    try:
        from PIL import Image, ImageOps  # type: ignore[import-untyped]
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Pillow not installed") from exc

    async with get_db() as db:
        row = await (
            await db.execute("SELECT path FROM photos WHERE id = ?", (photo_id,))
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")

    try:
        with Image.open(row["path"]) as src_img:
            oriented = ImageOps.exif_transpose(src_img) or src_img  # honour orientation tag
            rgb = oriented.convert("RGB")
            rgb.thumbnail((size, size))
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=85)
        return Response(
            content=buf.getvalue(),
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=86400"},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Photo file missing") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
