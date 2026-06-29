"""Search router: multi-person AND search with optional date range filter."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from db.database import get_db

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    people_ids: list[int]
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 100
    offset: int = 0


def _date_to_unix(date_str: str, end_of_day: bool = False) -> int:
    """Convert a YYYY-MM-DD string to a UTC Unix timestamp (midnight or 23:59:59)."""
    import calendar
    import datetime

    d = datetime.date.fromisoformat(date_str)
    if end_of_day:
        dt = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=datetime.timezone.utc)
    else:
        dt = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    return calendar.timegm(dt.timetuple())


@router.post("")
async def search_photos(body: SearchRequest) -> list[dict[str, Any]]:
    """Return photos where ALL requested people appear with assign_status='assigned'.

    AND logic is implemented as nested subqueries — one per person_id — so the
    query planner can use the idx_faces_person index on each subquery independently.
    Only photos whose taken_at falls within the optional date range are returned.
    """
    if not body.people_ids:
        return []

    # Build one subquery per person for AND semantics (Reliability Rule 5).
    subqueries = " ".join(
        "AND p.id IN (SELECT photo_id FROM faces WHERE person_id = ? AND assign_status = 'assigned')"
        for _ in body.people_ids
    )

    ts_from: int | None = _date_to_unix(body.date_from) if body.date_from else None
    ts_to: int | None = _date_to_unix(body.date_to, end_of_day=True) if body.date_to else None

    sql = f"""
        SELECT p.id, p.path, p.taken_at
          FROM photos p
         WHERE 1=1
        {subqueries}
           AND (p.taken_at >= ? OR ? IS NULL)
           AND (p.taken_at <= ? OR ? IS NULL)
         ORDER BY p.taken_at DESC NULLS LAST
         LIMIT ? OFFSET ?
    """
    params: list[Any] = [
        *body.people_ids,
        ts_from, ts_from,
        ts_to, ts_to,
        body.limit,
        body.offset,
    ]

    async with get_db() as db:
        async with db.execute(sql, params) as cur:
            photo_rows = await cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in photo_rows:
            photo_id = int(row["id"])
            async with db.execute(
                """
                SELECT id AS face_id, person_id, assign_conf
                  FROM faces
                 WHERE photo_id = ? AND assign_status = 'assigned'
                """,
                (photo_id,),
            ) as fcur:
                face_rows = await fcur.fetchall()

            results.append(
                {
                    "id": photo_id,
                    "path": row["path"],
                    "taken_at": row["taken_at"],
                    "faces": [
                        {
                            "face_id": int(f["face_id"]),
                            "person_id": int(f["person_id"]) if f["person_id"] is not None else None,
                            "assign_conf": f["assign_conf"],
                        }
                        for f in face_rows
                    ],
                }
            )

    return results
