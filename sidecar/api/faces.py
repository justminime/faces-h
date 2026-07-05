"""Face image serving endpoints."""

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from db.database import get_db
from services import image_cache

router = APIRouter(prefix="/faces", tags=["faces"])


@router.get("/{face_id}/crop")
async def get_face_crop(face_id: int) -> Response:
    """Serve a face bounding-box crop from its source photo as JPEG.

    Crops are cached on disk keyed by the photo's DB mtime (#114) — medallions
    and queue cards re-request the same crops constantly, and regenerating one
    means decoding the full-resolution original each time.
    """
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Pillow not installed") from exc

    async with get_db() as db:
        row = await (
            await db.execute(
                """
                SELECT f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
                       ph.path AS photo_path, ph.mtime AS photo_mtime
                  FROM faces f
                  JOIN photos ph ON ph.id = f.photo_id
                 WHERE f.id = ?
                """,
                (face_id,),
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Face not found")

    if any(row[k] is None for k in ("bbox_x", "bbox_y", "bbox_w", "bbox_h")):
        raise HTTPException(status_code=404, detail="Face has no bounding box")

    cache_path = image_cache.cache_key("faces", face_id, int(row["photo_mtime"]))
    cached = image_cache.get(cache_path)
    if cached is not None:
        return Response(
            content=cached,
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=86400", "X-Cache": "hit"},
        )

    try:
        from PIL import ImageOps
        with Image.open(row["photo_path"]) as src_img:
            img = ImageOps.exif_transpose(src_img) or src_img
            w_img, h_img = img.size
            # Clamp to image bounds so a slightly-out-of-range bbox can't
            # produce black padding in the crop.
            x = max(0, int(row["bbox_x"] * w_img))
            y = max(0, int(row["bbox_y"] * h_img))
            w = int(row["bbox_w"] * w_img)
            h = int(row["bbox_h"] * h_img)
            x2 = min(w_img, x + w)
            y2 = min(h_img, y + h)
            crop = img.convert("RGB").crop((x, y, x2, y2))
            buf = io.BytesIO()
            crop.save(buf, format="JPEG")
        data = buf.getvalue()
        image_cache.put(cache_path, data)
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400", "X-Cache": "miss"})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Photo file missing") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not generate face crop") from exc
