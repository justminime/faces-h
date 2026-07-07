"""Re-evaluation service: propagates a user correction through a person cluster.

All six reliability rules from docs/ARCHITECTURE.md § Reliability Rules are
respected:
- Rule 1/Rule 3: only automatic assignments are threshold-gated; user
  corrections set assign_status='assigned' directly (explicit user intent).
- Rule 2: assign_conf is always cosine similarity to the relevant centroid.
- Rule 4: uncertain queue count is visible (maintained by demoting faces).
- Rule 5: search only uses 'assigned' faces (unchanged here).
- Rule 6: re-evaluation never auto-promotes uncertain faces; demotion only.
"""

import inspect
import time
from collections.abc import Callable
from typing import Any

import aiosqlite
import numpy as np

from config import get_config


def _auto_assign_threshold() -> float:
    """Threshold from config.json (#107), read lazily per operation."""
    return get_config().auto_assign_threshold


def _uncertain_threshold() -> float:
    return get_config().uncertain_threshold


def _deserialize(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).copy()


class ReEvaluationService:
    """Processes a face correction and re-scores the affected person cluster."""

    async def trigger(
        self,
        face_id: int,
        old_person_id: int | None,
        new_person_id: int | None,
        db: aiosqlite.Connection,
        broadcast_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Apply a user correction and re-evaluate the old person's cluster.

        Steps:
        1. Fetch face embedding.
        2. Record correction in `corrections` table.
        3. Update face assignment (user override → always 'assigned' when
           new_person_id is provided, 'unreviewed' when null).
        4. Rebuild centroid for old person from all remaining assigned faces.
        5. Re-score old person's cluster; demote faces that drop below threshold.
        6. Update new person's centroid (rolling average).
        7. Emit `reeval_complete` WebSocket event.
        """
        # 1. Face embedding
        emb_row = await (
            await db.execute("SELECT embedding FROM faces WHERE id = ?", (face_id,))
        ).fetchone()
        embedding: np.ndarray | None = (
            _deserialize(emb_row["embedding"]) if emb_row and emb_row["embedding"] else None
        )

        # 2. Record correction
        await db.execute(
            "INSERT INTO corrections (face_id, old_person_id, new_person_id, corrected_at)"
            " VALUES (?, ?, ?, ?)",
            (face_id, old_person_id, new_person_id, int(time.time())),
        )

        # 3. Update face (user-explicit — bypass conf threshold per queue.confirm pattern)
        if new_person_id is not None:
            new_conf = await self._cosine_to_centroid(new_person_id, embedding, db)
            await db.execute(
                "UPDATE faces SET person_id=?, assign_conf=?, assign_status='assigned',"
                " suggested_person_id=NULL WHERE id=?",
                (new_person_id, new_conf, face_id),
            )
        else:
            await db.execute(
                "UPDATE faces SET person_id=NULL, assign_conf=NULL,"
                " assign_status='unreviewed', suggested_person_id=NULL WHERE id=?",
                (face_id,),
            )

        # 4. Rebuild centroid for old person (without the corrected face)
        newly_uncertain = 0
        if old_person_id is not None:
            old_centroid = await self._rebuild_centroid(old_person_id, db)
            if old_centroid is not None:
                await db.execute(
                    "UPDATE people SET centroid=? WHERE id=?",
                    (old_centroid.tobytes(), old_person_id),
                )

                # 5. Re-score every assigned face in old person's cluster
                async with db.execute(
                    "SELECT id, embedding FROM faces"
                    " WHERE person_id=? AND assign_status='assigned' AND embedding IS NOT NULL",
                    (old_person_id,),
                ) as cur:
                    cluster = await cur.fetchall()

                for f in cluster:
                    emb = _deserialize(f["embedding"])
                    conf = float(np.dot(emb, old_centroid))
                    if conf < _uncertain_threshold():
                        # Unassigned faces carry no confidence (Rule 2 hygiene —
                        # matches delete_person's convention, #103).
                        await db.execute(
                            "UPDATE faces SET assign_status='unreviewed',"
                            " person_id=NULL, assign_conf=NULL WHERE id=?",
                            (int(f["id"]),),
                        )
                    elif conf < _auto_assign_threshold():
                        # Demote to uncertain (Rule 6: never auto-promote back)
                        await db.execute(
                            "UPDATE faces SET assign_status='uncertain',"
                            " suggested_person_id=?, assign_conf=? WHERE id=?",
                            (old_person_id, conf, int(f["id"])),
                        )
                        newly_uncertain += 1

        # 6. Update new person's centroid
        if new_person_id is not None and embedding is not None:
            await self._rolling_centroid_update(new_person_id, embedding, db)

        await db.commit()

        # 7. Emit reeval_complete
        old_name: str | None = None
        if old_person_id is not None:
            name_row = await (
                await db.execute("SELECT name FROM people WHERE id=?", (old_person_id,))
            ).fetchone()
            if name_row:
                old_name = str(name_row["name"])

        result = broadcast_fn(
            {
                "type": "reeval_complete",
                "moved": 1,
                "newly_uncertain": newly_uncertain,
                "person_name": old_name,
            }
        )
        if inspect.isawaitable(result):
            await result

    async def sweep_for_person(
        self,
        person_id: int,
        db: aiosqlite.Connection,
        broadcast_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Sweep the library for faces that belong to person_id but were missed.

        Three passes (all threshold-gated — Rule 6 respected):
        1. Uncertain faces whose suggested_person_id = person_id and conf >= threshold
        2. Unreviewed faces that score >= auto_assign_threshold against this centroid
        3. Faces in *unnamed* other clusters that score higher here than there

        Never touches faces in named clusters (too risky without user confirmation).
        """
        centroid_row = await (
            await db.execute("SELECT centroid, name FROM people WHERE id=?", (person_id,))
        ).fetchone()
        if centroid_row is None or centroid_row["centroid"] is None:
            return
        centroid = _deserialize(centroid_row["centroid"])
        person_name = centroid_row["name"] if centroid_row["name"] else None

        # Emit sweep_started as the very first visible signal that a sweep is
        # underway (#184). This is broadcast-only — it does not change what
        # gets promoted or when (Rules 1/6 untouched); it just gives the
        # frontend something to show between "user named/confirmed a face"
        # and the eventual sweep_complete, which previously could be several
        # seconds of silence on a large library.
        started_result = broadcast_fn(
            {"type": "sweep_started", "person_id": person_id, "person_name": person_name}
        )
        if inspect.isawaitable(started_result):
            await started_result

        moved = 0

        # Pass 1: uncertain faces already pointing at this person
        async with db.execute(
            "SELECT id, embedding FROM faces"
            " WHERE suggested_person_id=? AND assign_status='uncertain'"
            "   AND embedding IS NOT NULL",
            (person_id,),
        ) as cur:
            uncertain = await cur.fetchall()

        for row in uncertain:
            emb = _deserialize(row["embedding"])
            conf = float(np.dot(emb, centroid))
            if conf >= _auto_assign_threshold():
                await db.execute(
                    "UPDATE faces SET person_id=?, assign_conf=?,"
                    " assign_status='assigned', suggested_person_id=NULL WHERE id=?",
                    (person_id, conf, int(row["id"])),
                )
                moved += 1

        # Pass 2: unreviewed faces
        async with db.execute(
            "SELECT id, embedding FROM faces"
            " WHERE assign_status='unreviewed' AND embedding IS NOT NULL",
        ) as cur:
            unreviewed = await cur.fetchall()

        for row in unreviewed:
            emb = _deserialize(row["embedding"])
            conf = float(np.dot(emb, centroid))
            if conf >= _auto_assign_threshold():
                await db.execute(
                    "UPDATE faces SET person_id=?, assign_conf=?,"
                    " assign_status='assigned', suggested_person_id=NULL WHERE id=?",
                    (person_id, conf, int(row["id"])),
                )
                moved += 1

        # Pass 3: faces in unnamed clusters that score higher against this centroid
        async with db.execute(
            """SELECT f.id, f.embedding, f.assign_conf, f.person_id
                 FROM faces f
                 JOIN people p ON p.id = f.person_id
                WHERE f.assign_status = 'assigned'
                  AND f.person_id != ?
                  AND (p.name IS NULL OR p.name = '')
                  AND f.embedding IS NOT NULL""",
            (person_id,),
        ) as cur:
            other = await cur.fetchall()

        for row in other:
            emb = _deserialize(row["embedding"])
            conf = float(np.dot(emb, centroid))
            current_conf = float(row["assign_conf"]) if row["assign_conf"] is not None else 0.0
            if conf >= _auto_assign_threshold() and conf > current_conf:
                await db.execute(
                    "UPDATE faces SET person_id=?, assign_conf=?,"
                    " assign_status='assigned', suggested_person_id=NULL WHERE id=?",
                    (person_id, conf, int(row["id"])),
                )
                moved += 1

        if moved > 0:
            await self._rolling_centroid_update_bulk(person_id, db)

        await db.commit()

        result = broadcast_fn(
            {"type": "sweep_complete", "person_id": person_id, "moved": moved}
        )
        if inspect.isawaitable(result):
            await result

    async def _rolling_centroid_update_bulk(
        self, person_id: int, db: aiosqlite.Connection
    ) -> None:
        """Rebuild centroid from all currently-assigned faces for this person."""
        async with db.execute(
            "SELECT embedding FROM faces"
            " WHERE person_id=? AND assign_status='assigned' AND embedding IS NOT NULL"
            " AND photo_id IN (SELECT id FROM photos WHERE missing = 0)",
            (person_id,),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return
        vecs = [_deserialize(r["embedding"]) for r in rows]
        mean = np.mean(vecs, axis=0).astype(np.float32)
        norm = float(np.linalg.norm(mean))
        new_c = mean / norm if norm > 0 else mean
        await db.execute(
            "UPDATE people SET centroid=? WHERE id=?", (new_c.tobytes(), person_id)
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _cosine_to_centroid(
        self,
        person_id: int,
        embedding: np.ndarray | None,
        db: aiosqlite.Connection,
    ) -> float | None:
        if embedding is None:
            return None
        row = await (
            await db.execute("SELECT centroid FROM people WHERE id=?", (person_id,))
        ).fetchone()
        if row is None or row["centroid"] is None:
            return None
        centroid = _deserialize(row["centroid"])
        return float(np.dot(embedding, centroid))

    async def _rebuild_centroid(
        self, person_id: int, db: aiosqlite.Connection
    ) -> np.ndarray | None:
        """Average all currently-assigned embeddings for this person."""
        async with db.execute(
            "SELECT embedding FROM faces"
            " WHERE person_id=? AND assign_status='assigned' AND embedding IS NOT NULL"
            " AND photo_id IN (SELECT id FROM photos WHERE missing = 0)",
            (person_id,),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return None
        vecs = [_deserialize(r["embedding"]) for r in rows]
        mean = np.mean(vecs, axis=0).astype(np.float32)
        norm = float(np.linalg.norm(mean))
        return mean / norm if norm > 0 else mean

    async def _rolling_centroid_update(
        self,
        person_id: int,
        embedding: np.ndarray,
        db: aiosqlite.Connection,
    ) -> None:
        """Add embedding to person's centroid via rolling average."""
        row = await (
            await db.execute("SELECT centroid FROM people WHERE id=?", (person_id,))
        ).fetchone()
        if row is None:
            return
        if row["centroid"] is None:
            new_c = embedding.astype(np.float32)
        else:
            old = _deserialize(row["centroid"])
            combined = old + embedding.astype(np.float32)
            norm = float(np.linalg.norm(combined))
            new_c = (combined / norm).astype(np.float32) if norm > 0 else combined
        norm = float(np.linalg.norm(new_c))
        if norm > 0:
            new_c = new_c / norm
        await db.execute(
            "UPDATE people SET centroid=? WHERE id=?", (new_c.tobytes(), person_id)
        )
