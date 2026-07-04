"""Face image serving endpoints."""

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from db.database import get_db

router = APIRouter(prefix="/faces", tags=["faces"])


@router.get("/{face_id}/crop")
async def get_face_crop(face_id: int) -> Response:
    """Serve a face bounding-box crop from its source photo as JPEG."""
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Pillow not installed") from exc

    async with get_db() as db:
        row = await (
            await db.execute(
                """
                SELECT f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
                       ph.path AS photo_path
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

    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(Image.open(row["photo_path"]))
        w_img, h_img = img.size
        x = int(row["bbox_x"] * w_img)
        y = int(row["bbox_y"] * h_img)
        w = int(row["bbox_w"] * w_img)
        h = int(row["bbox_h"] * h_img)
        crop = img.convert("RGB").crop((x, y, x + w, y + h))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG")
        return Response(content=buf.getvalue(), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not generate face crop") from exc
