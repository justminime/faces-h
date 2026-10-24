"""Import/export of named identities so recognition carries across libraries.

Export writes a small, portable JSON bundle of the *named* people and their
face-embedding centroids — no image files, no paths (on-device rule preserved).
Import matches each incoming named centroid against the current library's
clusters by cosine similarity and applies the name to the best matching
*unnamed* cluster above a threshold. It only sets `people.name`; it never
changes `assign_status`/`assign_conf`, so the reliability rules are untouched.

The tags export (/export/tags, #197) is the one export with paths: photo file
paths relative to their scan root plus the people in each, for an app that
holds the same photos (e.g. a family portal) to tag them. Still no image data.
"""

import base64
import time
from datetime import UTC, datetime
from typing import Any

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from config import get_config
from db.database import get_db

router = APIRouter(tags=["transfer"])

_EXPORT_VERSION = 1


class ExportedPerson(BaseModel):
    name: str
    centroid_b64: str


class ImportBundle(BaseModel):
    version: int = _EXPORT_VERSION
    people: list[ExportedPerson]
    # Cosine-similarity threshold for matching an imported centroid to a
    # cluster. None → the configured auto-assign threshold at request time.
    match_threshold: float | None = None


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


def _relative(path: str, roots: list[str]) -> tuple[str | None, str]:
    """(root, path relative to it with '/' separators) for the longest scan root
    containing `path`; (None, file name) when no root does."""
    norm = path.replace("\\", "/")
    best: str | None = None
    for root in roots:
        prefix = root.replace("\\", "/").rstrip("/") + "/"
        if norm.lower().startswith(prefix.lower()) and (best is None or len(root) > len(best)):
            best = root
    if best is None:
        return None, norm.rsplit("/", 1)[-1]
    return best, norm[len(best.replace("\\", "/").rstrip("/")) + 1 :]


@router.get("/export/tags")
async def export_tags(root: str | None = None) -> dict[str, Any]:
    """Photo ↔ person tags for another app (e.g. a family portal) to import.

    Only faces the reliability rules let through — `assign_status = 'assigned'` —
    on a *named* person; never uncertain, unreviewed, dismissed or unnamed. One
    entry per photo, people de-duplicated; photos gone from disk are left out.
    Paths are relative to the scan root, and no photos, embeddings or face boxes
    are included. `root` limits the export to one scan root.
    """
    async with get_db() as db:
        roots = [r["path"] for r in await (await db.execute("SELECT path FROM scan_roots")).fetchall()]
        rows = await (
            await db.execute(
                "SELECT p.path AS path, pe.name AS name FROM faces f "
                "JOIN photos p ON p.id = f.photo_id "
                "JOIN people pe ON pe.id = f.person_id "
                "WHERE f.assign_status = 'assigned' AND p.missing = 0 "
                "AND pe.name IS NOT NULL AND TRIM(pe.name) != '' "
                "ORDER BY p.path, pe.name"
            )
        ).fetchall()

    photos: dict[str, list[str]] = {}
    for row in rows:
        photo_root, rel = _relative(row["path"], roots)
        if root is not None and (photo_root is None or photo_root.rstrip("/\\") != root.rstrip("/\\")):
            continue
        people = photos.setdefault(rel, [])
        name = row["name"].strip()
        if name not in people:
            people.append(name)

    return {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": root if root is not None else (roots[0] if len(roots) == 1 else None),
        "photos": [{"file": f, "people": p} for f, p in photos.items()],
    }


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

            threshold = (
                bundle.match_threshold
                if bundle.match_threshold is not None
                else get_config().auto_assign_threshold
            )
            if best_id is None or best_sim < threshold:
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
