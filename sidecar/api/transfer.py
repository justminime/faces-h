"""Import/export of named identities so recognition carries across libraries.

Export writes a small, portable JSON bundle of the *named* people and their
face-embedding centroids — no image files, no paths (on-device rule preserved).
Import matches each incoming named centroid against the current library's
clusters by cosine similarity and applies the name to the best matching
*unnamed* cluster above a threshold. It only sets `people.name`; it never
changes `assign_status`/`assign_conf`, so the reliability rules are untouched.
"""

import base64
import time
from typing import Any

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from db.database import get_db
from services.clustering import _AUTO_ASSIGN_THRESHOLD

router = APIRouter(tags=["transfer"])

_EXPORT_VERSION = 1


class ExportedPerson(BaseModel):
    name: str
    centroid_b64: str


class ImportBundle(BaseModel):
    version: int = _EXPORT_VERSION
    people: list[ExportedPerson]
    # Cosine-similarity threshold for matching an imported centroid to a cluster.
    match_threshold: float = _AUTO_ASSIGN_THRESHOLD


def _normalise(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    return (v / norm).astype(np.float32) if norm > 0 else v.astype(np.float32)


@router.get("/export")
async def export_library() -> dict[str, Any]:
    """Return a portable bundle of named people and their centroids."""
    people: list[dict[str, str]] = []
    async with get_db() as db:
        async with db.execute(
            "SELECT name, centroid FROM people "
            "WHERE name IS NOT NULL AND TRIM(name) != '' AND centroid IS NOT NULL"
        ) as cur:
            async for row in cur:
                people.append(
                    {
                        "name": row["name"],
                        "centroid_b64": base64.b64encode(row["centroid"]).decode("ascii"),
                    }
                )
    return {"version": _EXPORT_VERSION, "exported_at": int(time.time()), "people": people}


@router.post("/import")
async def import_library(bundle: ImportBundle) -> dict[str, Any]:
    """Apply imported names to matching unnamed clusters (by centroid similarity).

    Returns a summary: how many names were applied, plus the names that had no
    match above threshold and those whose best match was already named (conflict).
    """
    applied = 0
    unmatched: list[str] = []
    conflicts: list[str] = []

    async with get_db() as db:
        rows = list(
            await (
                await db.execute("SELECT id, name, centroid FROM people WHERE centroid IS NOT NULL")
            ).fetchall()
        )
        clusters = [
            (int(r["id"]), r["name"], _normalise(np.frombuffer(r["centroid"], dtype=np.float32).copy()))
            for r in rows
        ]
        # Track names claimed during this import so two imported people don't both
        # land on the same cluster.
        claimed: set[int] = set()

        for person in bundle.people:
            try:
                raw = np.frombuffer(base64.b64decode(person.centroid_b64), dtype=np.float32).copy()
            except Exception:
                unmatched.append(person.name)
                continue
            if raw.size == 0:
                unmatched.append(person.name)
                continue
            emb = _normalise(raw)

            best_id: int | None = None
            best_name: str | None = None
            best_sim = -1.0
            for cid, cname, ccentroid in clusters:
                if cid in claimed or ccentroid.shape != emb.shape:
                    continue
                sim = float(np.dot(emb, ccentroid))
                if sim > best_sim:
                    best_sim, best_id, best_name = sim, cid, cname

            if best_id is None or best_sim < bundle.match_threshold:
                unmatched.append(person.name)
                continue

            if best_name is not None and best_name.strip() != "":
                # Best match is already named — don't overwrite the user's name.
                if best_name.strip() != person.name.strip():
                    conflicts.append(person.name)
                else:
                    claimed.add(best_id)
                continue

            await db.execute(
                "UPDATE people SET name = ? WHERE id = ?", (person.name, best_id)
            )
            claimed.add(best_id)
            applied += 1

        await db.commit()

    return {
        "applied": applied,
        "unmatched": unmatched,
        "conflicts": conflicts,
        "total": len(bundle.people),
    }
