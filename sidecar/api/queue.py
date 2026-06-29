"""Queue router: uncertain face review endpoints."""

from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from services.clustering import ClusteringService

router = APIRouter(prefix="/queue", tags=["queue"])
_svc = ClusteringService()


@router.get("/count")
async def queue_count() -> dict[str, int]:
    """Return the number of faces awaiting uncertain-queue review."""
    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT COUNT(*) AS cnt FROM faces WHERE assign_status = 'uncertain'"
            )
        ).fetchone()
        assert row is not None
        return {"count": int(row["cnt"])}


@router.get("/uncertain")
async def list_uncertain(
    limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """Paginated list of uncertain faces with their suggested person."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT f.id        AS face_id,
                   f.photo_id,
                   f.assign_conf,
                   f.suggested_person_id,
                   p.name      AS suggested_person_name
              FROM faces f
              LEFT JOIN people p ON p.id = f.suggested_person_id
             WHERE f.assign_status = 'uncertain'
             ORDER BY f.id ASC
             LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {
            "face_id": int(r["face_id"]),
            "photo_id": int(r["photo_id"]),
            "face_crop_url": f"/faces/{int(r['face_id'])}/crop",
            "suggested_person_id": r["suggested_person_id"],
            "suggested_person_name": r["suggested_person_name"],
            "assign_conf": r["assign_conf"],
        }
        for r in rows
    ]


class ConfirmRequest(BaseModel):
    person_id: int


@router.post("/{face_id}/confirm")
async def confirm_face(face_id: int, body: ConfirmRequest) -> dict[str, Any]:
    """Promote an uncertain face to 'assigned' and update the person's centroid."""
    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT assign_status, embedding FROM faces WHERE id = ?",
                (face_id,),
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Face not found")
        if row["assign_status"] != "uncertain":
            raise HTTPException(status_code=400, detail="Face is not uncertain")

        await db.execute(
            """
            UPDATE faces
               SET assign_status = 'assigned',
                   person_id = ?,
                   suggested_person_id = NULL
             WHERE id = ?
            """,
            (body.person_id, face_id),
        )
        await db.commit()

        embedding_bytes: bytes | None = row["embedding"]
        if embedding_bytes is not None:
            embedding = np.frombuffer(embedding_bytes, dtype=np.float32).copy()
            await _svc.update_centroid(body.person_id, embedding, db)

    return {"face_id": face_id, "person_id": body.person_id, "assign_status": "assigned"}
