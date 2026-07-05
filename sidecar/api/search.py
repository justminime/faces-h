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
    # "contains": photo includes all selected people (others allowed, default).
    # "exact": the photo's set of assigned people equals exactly the selection.
    match: str = "contains"
    limit: int = 100
    offset: int = 0


def _date_to_unix(date_str: str, end_of_day: bool = False) -> int:
    """Convert a YYYY-MM-DD string to a UTC Unix timestamp (midnight or 23:59:59)."""
    import calendar
    import datetime
    from fastapi import HTTPException

    try:
        d = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date '{date_str}' — expected YYYY-MM-DD") from exc
    if end_of_day:
        dt = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=datetime.timezone.utc)
    else:
        dt = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    return calendar.timegm(dt.timetuple())


@router.post("")
async def search_photos(body: SearchRequest) -> list[dict[str, Any]]:
    """Return photos matching the requested people (assign_status='assigned').

    - match="contains" (default): every selected person appears in the photo
      (others allowed). AND logic via one nested subquery per person_id so the
      planner can use idx_faces_person on each independently.
    - match="exact": additionally the photo's set of distinct *assigned* people
      equals exactly the selection — no other named person is present. Uncertain
      or unassigned faces don't count, so they never disqualify an exact match.

    Only photos whose taken_at falls within the optional date range are returned.
    """
    if not body.people_ids:
        return []

    # Build one subquery per person for AND semantics (Reliability Rule 5).
    subqueries = " ".join(
        "AND p.id IN (SELECT photo_id FROM faces WHERE person_id = ? AND assign_status = 'assigned')"
        for _ in body.people_ids
    )

    # For exact match, require the photo to contain no *other* assigned people.
    exact_clause = ""
    if body.match == "exact":
        exact_clause = (
            "AND (SELECT COUNT(DISTINCT person_id) FROM faces "
            "WHERE photo_id = p.id AND assign_status = 'assigned') = ?"
        )

    ts_from: int | None = _date_to_unix(body.date_from) if body.date_from else None
    ts_to: int | None = _date_to_unix(body.date_to, end_of_day=True) if body.date_to else None

    sql = f"""
        SELECT p.id, p.path, p.taken_at
          FROM photos p
         WHERE p.missing = 0
        {subqueries}
        {exact_clause}
           AND (p.taken_at >= ? OR ? IS NULL)
           AND (p.taken_at <= ? OR ? IS NULL)
         ORDER BY p.taken_at DESC NULLS LAST
         LIMIT ? OFFSET ?
    """
    params: list[Any] = [
        *body.people_ids,
        *([len(set(body.people_ids))] if body.match == "exact" else []),
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
