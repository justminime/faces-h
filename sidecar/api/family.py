"""Family list (#198): name people only from another app's member list.

The list comes from the family portal (Admin → Import face tags → Download
family list). Once it's loaded, a person is named by *linking* it to a member
(`people.list_member_id`), never by free text, so every name faces-h hands back
in a tags export is one the portal already knows — with its id.

Linking only sets `people.name`/`list_member_id`; it never changes
`assign_status`/`assign_conf`, so the reliability rules are untouched. The
guided review (/review) only *orders* the existing uncertain queue — faces
still need the user's confirmation to become 'assigned' (Rule 6).
"""

import asyncio
import time
from typing import Any

import aiosqlite
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.scan import broadcast_ws
from db.database import get_db
from services.reeval import ReEvaluationService

router = APIRouter(tags=["family"])
_reeval = ReEvaluationService()

_LIST_VERSION = 1


class FamilyMember(BaseModel):
    id: int
    name: str
    heb_name: str | None = None
    birth_year: int | None = None
    death_year: int | None = None


class FamilyList(BaseModel):
    version: int
    members: list[FamilyMember]


class LinkRequest(BaseModel):
    member_id: int


async def family_list_loaded(db: aiosqlite.Connection) -> bool:
    row = await (await db.execute("SELECT 1 FROM family_members LIMIT 1")).fetchone()
    return row is not None


def _vec(blob: bytes | None) -> np.ndarray | None:
    if blob is None:
        return None
    v = np.frombuffer(blob, dtype=np.float32).copy()
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else None


async def _members(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Members with the person linked to each (lowest id if, oddly, several)."""
    rows = await (
        await db.execute(
            "SELECT m.id, m.name, m.heb_name, m.birth_year, m.death_year,"
            "       MIN(p.id) AS person_id"
            "  FROM family_members m"
            "  LEFT JOIN people p ON p.list_member_id = m.id"
            " GROUP BY m.id ORDER BY m.name"
        )
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/family")
async def get_family() -> dict[str, Any]:
    async with get_db() as db:
        members = await _members(db)
    return {"loaded": bool(members), "members": members}


@router.post("/family/import")
async def import_family(body: FamilyList) -> dict[str, Any]:
    """Replace the family list. People are never deleted: linked people take
    their member's (possibly new) name; people whose member left the list keep
    their name but are unlinked. Named, unlinked people whose name matches
    exactly one member (English or Hebrew) are linked to it."""
    if body.version != _LIST_VERSION:
        raise HTTPException(status_code=400, detail=f"Unsupported family list version {body.version}")
    if not body.members:
        raise HTTPException(status_code=400, detail="The family list is empty")
    ids = [m.id for m in body.members]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="Member ids must be unique")
    if any(not m.name.strip() for m in body.members):
        raise HTTPException(status_code=400, detail="Every member needs a name")

    now = int(time.time())
    async with get_db() as db:
        await db.execute("DELETE FROM family_members")
        await db.executemany(
            "INSERT INTO family_members (id, name, heb_name, birth_year, death_year, imported_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(m.id, m.name.strip(), m.heb_name, m.birth_year, m.death_year, now) for m in body.members],
        )
        unlinked = (
            await db.execute(
                "UPDATE people SET list_member_id = NULL WHERE list_member_id IS NOT NULL"
                " AND list_member_id NOT IN (SELECT id FROM family_members)"
            )
        ).rowcount
        renamed = (
            await db.execute(
                "UPDATE people SET name = (SELECT name FROM family_members m WHERE m.id = list_member_id)"
                " WHERE list_member_id IS NOT NULL"
                "   AND name != (SELECT name FROM family_members m WHERE m.id = list_member_id)"
            )
        ).rowcount

        # Auto-link by exact name — only when unambiguous on both sides.
        by_name: dict[str, list[int]] = {}
        for m in body.members:
            for n in {m.name, m.heb_name or ""}:
                if n.strip():
                    by_name.setdefault(n.strip().casefold(), []).append(m.id)
        taken = {
            int(r["list_member_id"])
            for r in await (
                await db.execute("SELECT list_member_id FROM people WHERE list_member_id IS NOT NULL")
            ).fetchall()
        }
        people = await (
            await db.execute(
                "SELECT id, name FROM people WHERE list_member_id IS NULL AND TRIM(name) != ''"
            )
        ).fetchall()
        name_counts: dict[str, int] = {}
        for p in people:
            key = p["name"].strip().casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
        linked = 0
        for p in people:
            key = p["name"].strip().casefold()
            matches = set(by_name.get(key, []))
            if len(matches) != 1 or name_counts[key] != 1:
                continue
            member_id = matches.pop()
            if member_id in taken:
                continue
            await db.execute(
                "UPDATE people SET list_member_id = ?,"
                " name = (SELECT name FROM family_members WHERE id = ?) WHERE id = ?",
                (member_id, member_id, int(p["id"])),
            )
            taken.add(member_id)
            linked += 1
        await db.commit()

    return {"members": len(body.members), "linked": linked, "renamed": renamed, "unlinked": unlinked}


@router.get("/family/candidates")
async def candidates(face_id: int | None = None, person_id: int | None = None) -> list[dict[str, Any]]:
    """Members ranked for naming a face or a whole cluster.

    Members whose linked person's centroid is closest to the face embedding
    (or the cluster centroid) come first, with `similarity`; members with no
    centroid yet follow, by name (`similarity` null). The person being named
    is marked `current` and gets no score (it would always match itself).
    """
    if (face_id is None) == (person_id is None):
        raise HTTPException(status_code=400, detail="Give exactly one of face_id or person_id")
    async with get_db() as db:
        if face_id is not None:
            row = await (await db.execute("SELECT embedding, person_id FROM faces WHERE id = ?", (face_id,))).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Face not found")
            query, self_id = _vec(row["embedding"]), None
        else:
            row = await (await db.execute("SELECT centroid FROM people WHERE id = ?", (person_id,))).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Person not found")
            query, self_id = _vec(row["centroid"]), person_id
        members = await _members(db)
        centroids = {
            int(r["id"]): _vec(r["centroid"])
            for r in await (
                await db.execute("SELECT id, centroid FROM people WHERE list_member_id IS NOT NULL")
            ).fetchall()
        }

    out: list[dict[str, Any]] = []
    for m in members:
        pid = m["person_id"]
        centroid = centroids.get(int(pid)) if pid is not None else None
        sim: float | None = None
        if query is not None and centroid is not None and pid != self_id and centroid.shape == query.shape:
            sim = round(float(np.dot(query, centroid)), 4)
        out.append({**m, "similarity": sim, "current": pid is not None and pid == self_id})
    out.sort(key=lambda c: (c["similarity"] is None, -(c["similarity"] or 0.0), c["name"].casefold()))
    return out


@router.post("/family/{member_id}/person")
async def person_for_member(member_id: int) -> dict[str, int]:
    """The person linked to a member, created (with no faces yet) if there is
    none — so a face can be confirmed/corrected to a member never seen before."""
    async with get_db() as db:
        member = await (await db.execute("SELECT name FROM family_members WHERE id = ?", (member_id,))).fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="Member not found")
        row = await (
            await db.execute("SELECT MIN(id) AS id FROM people WHERE list_member_id = ?", (member_id,))
        ).fetchone()
        if row is not None and row["id"] is not None:
            return {"person_id": int(row["id"])}
        cur = await db.execute(
            "INSERT INTO people (name, created_at, centroid, list_member_id) VALUES (?, ?, NULL, ?)",
            (member["name"], int(time.time()), member_id),
        )
        await db.commit()
        assert cur.lastrowid is not None
        return {"person_id": int(cur.lastrowid)}


@router.post("/people/{person_id}/member")
async def link_person(person_id: int, body: LinkRequest) -> dict[str, Any]:
    """Name a cluster by linking it to a member. 409 when another cluster is
    already that member — the client offers the existing merge instead."""
    async with get_db() as db:
        if (await (await db.execute("SELECT id FROM people WHERE id = ?", (person_id,))).fetchone()) is None:
            raise HTTPException(status_code=404, detail="Person not found")
        member = await (await db.execute("SELECT name FROM family_members WHERE id = ?", (body.member_id,))).fetchone()
        if member is None:
            raise HTTPException(status_code=404, detail="Member not found")
        other = await (
            await db.execute(
                "SELECT id FROM people WHERE list_member_id = ? AND id != ?", (body.member_id, person_id)
            )
        ).fetchone()
        if other is not None:
            raise HTTPException(
                status_code=409,
                detail={"message": f"{member['name']} is already another group", "person_id": int(other["id"])},
            )
        await db.execute(
            "UPDATE people SET list_member_id = ?, name = ? WHERE id = ?",
            (body.member_id, member["name"], person_id),
        )
        await db.commit()

    # Same as naming by text: sweep for more faces of this person.
    async def _sweep() -> None:
        async with get_db() as db2:
            await _reeval.sweep_for_person(person_id, db2, broadcast_ws)

    asyncio.create_task(_sweep())
    return {"id": person_id, "name": member["name"], "member_id": body.member_id}


@router.get("/review/queue")
async def review_queue(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Guided review: uncertain faces suggested as a *listed* person — biggest
    clusters first, and within one, the faces faces-h is least sure of first.
    Same items as /queue/uncertain, so the same confirm/dismiss calls apply."""
    async with get_db() as db, db.execute(
        """
            SELECT f.id AS face_id, f.photo_id, f.assign_conf,
                   f.suggested_person_id, p.name AS suggested_person_name
              FROM faces f
              JOIN photos ph ON ph.id = f.photo_id AND ph.missing = 0
              JOIN people p  ON p.id = f.suggested_person_id AND p.list_member_id IS NOT NULL
              LEFT JOIN (SELECT person_id, COUNT(*) AS n FROM faces
                          WHERE assign_status = 'assigned' GROUP BY person_id) sz
                     ON sz.person_id = p.id
             WHERE f.assign_status = 'uncertain'
             ORDER BY COALESCE(sz.n, 0) DESC, p.id, f.assign_conf ASC NULLS FIRST, f.id
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


@router.get("/review/progress")
async def review_progress() -> dict[str, Any]:
    """Per listed person: faces assigned vs still uncertain. Done when no
    uncertain face is suggested as a listed person."""
    async with get_db() as db:
        rows = await (
            await db.execute(
                """
                SELECT m.id AS member_id, m.name, m.heb_name, p.id AS person_id,
                       SUM(CASE WHEN f.assign_status = 'assigned' AND f.person_id = p.id THEN 1 ELSE 0 END) AS assigned,
                       SUM(CASE WHEN f.assign_status = 'uncertain' AND f.suggested_person_id = p.id THEN 1 ELSE 0 END)
                           AS uncertain
                  FROM family_members m
                  JOIN people p ON p.list_member_id = m.id
                  LEFT JOIN faces f ON (f.person_id = p.id OR f.suggested_person_id = p.id)
                  LEFT JOIN photos ph ON ph.id = f.photo_id
                 WHERE f.id IS NULL OR ph.missing = 0
                 GROUP BY m.id, p.id
                 ORDER BY uncertain DESC, assigned DESC, m.name
                """
            )
        ).fetchall()
        unlinked = await (
            await db.execute("SELECT COUNT(*) AS n FROM family_members WHERE id NOT IN"
                             " (SELECT list_member_id FROM people WHERE list_member_id IS NOT NULL)")
        ).fetchone()
    people = [
        {**dict(r), "assigned": int(r["assigned"] or 0), "uncertain": int(r["uncertain"] or 0)} for r in rows
    ]
    remaining = sum(p["uncertain"] for p in people)
    return {
        "people": people,
        "remaining": remaining,
        "members_without_faces": int(unlinked["n"]) if unlinked else 0,
        "done": remaining == 0,
    }
