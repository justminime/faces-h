"""Corrections router: accept user face-assignment corrections."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.scan import broadcast_ws
from db.database import get_db
from services.reeval import ReEvaluationService

router = APIRouter()
_reeval = ReEvaluationService()


class CorrectionRequest(BaseModel):
    new_person_id: int | None


@router.post("/photos/{photo_id}/faces/{face_id}/correct")
async def correct_face(
    photo_id: int, face_id: int, body: CorrectionRequest
) -> dict[str, Any]:
    """Accept a user correction and kick off re-evaluation in the background.

    Returns 200 immediately; re-evaluation runs asynchronously so the UI
    remains responsive during cluster re-scoring.
    """
    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT person_id FROM faces WHERE id=? AND photo_id=?",
                (face_id, photo_id),
            )
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Face not found in this photo")

    old_person_id: int | None = row["person_id"]
    new_person_id = body.new_person_id

    async def _run() -> None:
        async with get_db() as db:
            await _reeval.trigger(
                face_id=face_id,
                old_person_id=old_person_id,
                new_person_id=new_person_id,
                db=db,
                broadcast_fn=broadcast_ws,
            )
        # Sweep for more photos of the destination person now that the
        # correction has refined their centroid.
        if new_person_id is not None:
            async with get_db() as db:
                await _reeval.sweep_for_person(new_person_id, db, broadcast_ws)

    asyncio.create_task(_run())
    return {"status": "queued", "face_id": face_id}
