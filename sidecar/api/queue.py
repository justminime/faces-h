"""Queue router: uncertain face review endpoints."""

import asyncio
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.scan import broadcast_ws
from db.database import get_db
from services.clustering import ClusteringService
from services.reeval import ReEvaluationService

router = APIRouter(prefix="/queue", tags=["queue"])
_svc = ClusteringService()
_reeval = ReEvaluationService()


@router.get("/count")
async def queue_count() -> dict[str, int]:
    """Return the number of faces awaiting uncertain-queue review."""
    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT COUNT(*) AS cnt FROM faces f"
                " JOIN photos ph ON ph.id = f.photo_id AND ph.missing = 0"
                " WHERE f.assign_status = 'uncertain'"
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
              JOIN photos ph ON ph.id = f.photo_id AND ph.missing = 0
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
    """Promote an uncertain face to 'assigned' and update the person's centroid.

    Rule 2 (#103): assign_conf is recomputed as cosine similarity to the
    *confirmed* person's centroid at confirmation time — the stored value
    referenced the suggested person, who may not be the one the user picked.
    """
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

        person_row = await (
            await db.execute(
                "SELECT centroid FROM people WHERE id = ?", (body.person_id,)
            )
        ).fetchone()
        if person_row is None:
            raise HTTPException(status_code=404, detail="Person not found")

        embedding_bytes: bytes | None = row["embedding"]
        embedding: np.ndarray | None = (
            np.frombuffer(embedding_bytes, dtype=np.float32).copy()
            if embedding_bytes is not None
            else None
        )

        # Similarity to the centroid as it is *before* this face is folded in.
        new_conf: float | None = None
        if embedding is not None and person_row["centroid"] is not None:
            centroid = np.frombuffer(person_row["centroid"], dtype=np.float32).copy()
            if centroid.shape == embedding.shape:
                new_conf = float(np.dot(embedding, centroid))

        await db.execute(
            """
            UPDATE faces
               SET assign_status = 'assigned',
                   person_id = ?,
                   assign_conf = ?,
                   suggested_person_id = NULL
             WHERE id = ?
            """,
            (body.person_id, new_conf, face_id),
        )
        await db.commit()

        if embedding is not None:
            await _svc.update_centroid(body.person_id, embedding, db)

    # Sweep in the background for more uncertain/unreviewed faces that now
    # match this person's refreshed centroid (#169) — same pattern as naming
    # and merging, so confirming one face can surface several more at once.
    person_id = body.person_id

    async def _sweep() -> None:
        async with get_db() as db2:
            await _reeval.sweep_for_person(person_id, db2, broadcast_ws)

    asyncio.create_task(_sweep())

    return {
        "face_id": face_id,
        "person_id": body.person_id,
        "assign_status": "assigned",
        "assign_conf": new_conf,
    }


@router.post("/{face_id}/dismiss")
async def dismiss_face(face_id: int) -> dict[str, Any]:
    """Mark an uncertain face as 'not relevant' (#168) — a persistent decision,
    unlike the client-only 'Skip' which just hides the card for the session.

    Dismissed faces never reappear in the main review queue (they carry a
    dedicated assign_status, not 'uncertain') but stay reviewable from the
    secondary Not Relevant view and can be restored to 'unreviewed' there.
    """
    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT assign_status FROM faces WHERE id = ?", (face_id,)
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Face not found")
        if row["assign_status"] != "uncertain":
            raise HTTPException(status_code=400, detail="Face is not uncertain")

        await db.execute(
            """
            UPDATE faces
               SET assign_status = 'dismissed',
                   person_id = NULL,
                   suggested_person_id = NULL,
                   assign_conf = NULL
             WHERE id = ?
            """,
            (face_id,),
        )
        await db.commit()

    return {"face_id": face_id, "assign_status": "dismissed"}


@router.get("/dismissed")
async def list_dismissed(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Paginated list of faces dismissed as 'not relevant' (#168) — the
    secondary review window, separate from the main To-review queue."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT f.id AS face_id, f.photo_id
              FROM faces f
              JOIN photos ph ON ph.id = f.photo_id AND ph.missing = 0
             WHERE f.assign_status = 'dismissed'
             ORDER BY f.id DESC
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
        }
        for r in rows
    ]


@router.post("/{face_id}/restore")
async def restore_dismissed_face(face_id: int) -> dict[str, Any]:
    """Bring a dismissed face back into normal evaluation (#168) —
    'unreviewed' so it is picked up by future sweeps/manual naming like any
    other never-reviewed face; it is not silently re-promoted to a person."""
    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT assign_status FROM faces WHERE id = ?", (face_id,)
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Face not found")
        if row["assign_status"] != "dismissed":
            raise HTTPException(status_code=400, detail="Face is not dismissed")

        await db.execute(
            "UPDATE faces SET assign_status = 'unreviewed' WHERE id = ?",
            (face_id,),
        )
        await db.commit()

    return {"face_id": face_id, "assign_status": "unreviewed"}
