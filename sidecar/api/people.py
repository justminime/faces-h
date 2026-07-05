"""FastAPI router for people, naming, merge, and gallery endpoints."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.scan import broadcast_ws
from db.database import get_db
from services.clustering import ClusteringService
from services.reeval import ReEvaluationService

router = APIRouter(prefix="/people", tags=["people"])
_svc = ClusteringService()
_reeval = ReEvaluationService()


class NameRequest(BaseModel):
    name: str


class MergeRequest(BaseModel):
    source_id: int
    target_id: int
    confirmed: bool = False


@router.get("")
async def list_people() -> list[dict[str, Any]]:
    """List all named people with photo count and medallion face ID."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT p.id,
                   p.name,
                   COUNT(DISTINCT ph.id) AS photo_count,
                   MIN(f.id)             AS medallion_face_id
              FROM people p
              LEFT JOIN faces f   ON f.person_id = p.id
                                 AND f.assign_status = 'assigned'
              LEFT JOIN photos ph ON ph.id = f.photo_id
             GROUP BY p.id, p.name
             ORDER BY photo_count DESC, p.name
            """
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


@router.get("/{person_id}/photos")
async def list_person_photos(
    person_id: int,
    limit: int = 50,
    offset: int = 0,
    order: str = "date",
) -> list[dict[str, Any]]:
    """Return photos for a person, grouped with nested faces — Rule 5: only 'assigned'.

    order='random' samples from the full pool using RANDOM() — used for the first
    page so each visit surfaces a different mix of old and new photos.
    order='date' (default) gives stable chronological order for pagination.
    """
    # Only 'random' or 'date' are valid; anything else falls back to 'date'.
    use_random = order == "random"
    inner_order = "RANDOM()" if use_random else "f2.photo_id ASC"

    async with get_db() as db:
        row = await (
            await db.execute("SELECT id FROM people WHERE id = ?", (person_id,))
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Person not found")

        # Page the photos by the selected person (Rule 5: only 'assigned' for
        # the paging query), then return ALL detected faces in those photos —
        # assigned, uncertain, and unreviewed — so the detail panel shows
        # every person present, not only confidently-matched ones.
        async with db.execute(
            f"""
            SELECT ph.id          AS photo_id,
                   ph.path,
                   ph.taken_at,
                   f.id           AS face_id,
                   f.person_id    AS face_person_id,
                   f.assign_conf,
                   f.assign_status
              FROM (
                  SELECT DISTINCT f2.photo_id
                    FROM faces f2
                   WHERE f2.person_id = ?
                     AND f2.assign_status = 'assigned'
                   ORDER BY {inner_order}
                   LIMIT ? OFFSET ?
              ) page
              JOIN photos ph ON ph.id = page.photo_id
              JOIN faces  f  ON f.photo_id = ph.id
             ORDER BY ph.taken_at ASC NULLS LAST, ph.id ASC
            """,
            (person_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()

        photo_map: dict[int, dict[str, Any]] = {}
        for r in rows:
            pid = int(r["photo_id"])
            if pid not in photo_map:
                photo_map[pid] = {
                    "id": pid,
                    "path": r["path"],
                    "taken_at": r["taken_at"],
                    "faces": [],
                }
            photo_map[pid]["faces"].append(
                {
                    "face_id": int(r["face_id"]),
                    "person_id": int(r["face_person_id"]) if r["face_person_id"] is not None else None,
                    "assign_conf": r["assign_conf"],
                    "assign_status": r["assign_status"],
                }
            )
        return list(photo_map.values())


@router.post("/{person_id}/name")
async def set_name(person_id: int, body: NameRequest) -> dict[str, Any]:
    async with get_db() as db:
        row = await (
            await db.execute("SELECT id FROM people WHERE id = ?", (person_id,))
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Person not found")
        await db.execute("UPDATE people SET name = ? WHERE id = ?", (body.name, person_id))
        await db.commit()

    # Sweep library in background — finds uncertain/unreviewed faces that
    # belong to this person now that their centroid is well-defined.
    async def _sweep() -> None:
        async with get_db() as db:
            await _reeval.sweep_for_person(person_id, db, broadcast_ws)

    asyncio.create_task(_sweep())
    return {"id": person_id, "name": body.name}


@router.post("/merge")
async def merge_people_endpoint(body: MergeRequest) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="confirmed must be true")
    async with get_db() as db:
        for pid in (body.source_id, body.target_id):
            row = await (
                await db.execute("SELECT id FROM people WHERE id = ?", (pid,))
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Person {pid} not found")

        count_row = await (
            await db.execute(
                "SELECT COUNT(*) AS cnt FROM faces WHERE person_id = ?",
                (body.source_id,),
            )
        ).fetchone()
        assert count_row is not None
        merged_count = int(count_row["cnt"])

        await _svc.merge_people(body.source_id, body.target_id, body.confirmed, db)

    # Sweep for more photos of the surviving (target) person now that both
    # clusters' faces have been merged and the centroid has been rebuilt.
    target_id = body.target_id

    async def _sweep_after_merge() -> None:
        async with get_db() as db:
            await _reeval.sweep_for_person(target_id, db, broadcast_ws)

    asyncio.create_task(_sweep_after_merge())
    return {"surviving_id": body.target_id, "merged_count": merged_count}


@router.delete("/{person_id}")
async def delete_person_endpoint(person_id: int) -> dict[str, Any]:
    async with get_db() as db:
        row = await (
            await db.execute("SELECT id FROM people WHERE id = ?", (person_id,))
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Person not found")
        await _svc.delete_person(person_id, db)
    return {"deleted": True, "person_id": person_id}
