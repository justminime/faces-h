"""FastAPI router for people, naming, merge, and gallery endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from services.clustering import ClusteringService

router = APIRouter(prefix="/people", tags=["people"])
_svc = ClusteringService()


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
             ORDER BY p.name
            """
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


@router.get("/{person_id}/photos")
async def list_person_photos(
    person_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return photos for a person — Rule 5: only 'assigned' faces returned."""
    async with get_db() as db:
        row = await (
            await db.execute("SELECT id FROM people WHERE id = ?", (person_id,))
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Person not found")

        async with db.execute(
            """
            SELECT ph.id,
                   ph.path,
                   ph.taken_at,
                   ph.width,
                   ph.height,
                   f.id        AS face_id,
                   f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h,
                   f.assign_conf
              FROM faces f
              JOIN photos ph ON ph.id = f.photo_id
             WHERE f.person_id = ?
               AND f.assign_status = 'assigned'
             ORDER BY ph.taken_at ASC NULLS LAST, ph.id ASC
             LIMIT ? OFFSET ?
            """,
            (person_id, limit, offset),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


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
        await _svc.merge_people(body.source_id, body.target_id, body.confirmed, db)
    return {"merged": True, "target_id": body.target_id}


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
