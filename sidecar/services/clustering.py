"""Clustering service: assigns face embeddings to person clusters.

All six reliability rules from docs/ARCHITECTURE.md § Reliability Rules are
enforced here at write time — they cannot be bypassed by callers.
"""

import time
from typing import Literal

import aiosqlite
import numpy as np

AssignStatus = Literal["assigned", "uncertain", "unreviewed"]

_AUTO_ASSIGN_THRESHOLD = 0.68
_UNCERTAIN_THRESHOLD = 0.50


def _serialize_centroid(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def _deserialize_centroid(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).copy()


class ClusteringService:
    """Assigns face embeddings to person clusters with reliability guarantees."""

    def __init__(
        self,
        auto_assign_threshold: float = _AUTO_ASSIGN_THRESHOLD,
        uncertain_threshold: float = _UNCERTAIN_THRESHOLD,
    ) -> None:
        self.auto_assign_threshold = auto_assign_threshold
        self.uncertain_threshold = uncertain_threshold

    def _status(self, conf: float) -> AssignStatus:
        """Rule 1 + Rule 3: derive assignment status from cosine similarity."""
        if conf >= self.auto_assign_threshold:
            return "assigned"
        if conf >= self.uncertain_threshold:
            return "uncertain"
        return "unreviewed"

    async def assign_face(
        self,
        face_id: int,
        embedding: np.ndarray,
        db: aiosqlite.Connection,
    ) -> AssignStatus:
        """Compare embedding against all person centroids; update face row.

        Rule 1: assign_status is never 'assigned' unless
        assign_conf >= auto_assign_threshold.
        """
        best_person_id: int | None = None
        best_conf: float = -1.0

        async with db.execute(
            "SELECT id, centroid FROM people WHERE centroid IS NOT NULL"
        ) as cur:
            async for row in cur:
                centroid = _deserialize_centroid(row["centroid"])
                sim = float(np.dot(embedding, centroid))
                if sim > best_conf:
                    best_conf = sim
                    best_person_id = int(row["id"])

        if best_person_id is None:
            status: AssignStatus = "unreviewed"
            person_id_out: int | None = None
            suggested_person_id_out: int | None = None
            conf_out: float | None = None
        else:
            status = self._status(best_conf)
            # Rule 1: only link person_id when definitively assigned
            person_id_out = best_person_id if status == "assigned" else None
            # Store the best candidate for uncertain faces so the review queue can show it
            suggested_person_id_out = best_person_id if status == "uncertain" else None
            conf_out = best_conf

        await db.execute(
            """
            UPDATE faces
               SET person_id = ?,
                   suggested_person_id = ?,
                   assign_conf = ?,
                   assign_status = ?,
                   embedding = ?
             WHERE id = ?
            """,
            (
                person_id_out,
                suggested_person_id_out,
                conf_out,
                status,
                embedding.astype(np.float32).tobytes(),
                face_id,
            ),
        )
        await db.commit()
        return status

    async def update_centroid(
        self,
        person_id: int,
        embedding: np.ndarray,
        db: aiosqlite.Connection,
    ) -> None:
        """Rolling average: new_centroid = normalise(old + embedding)."""
        row = await (
            await db.execute("SELECT centroid FROM people WHERE id = ?", (person_id,))
        ).fetchone()
        if row is None:
            return

        new_centroid: np.ndarray
        if row["centroid"] is None:
            new_centroid = embedding.astype(np.float32)
        else:
            old = _deserialize_centroid(row["centroid"])
            combined = old + embedding.astype(np.float32)
            norm = float(np.linalg.norm(combined))
            new_centroid = (combined / norm).astype(np.float32) if norm > 0 else combined

        norm = float(np.linalg.norm(new_centroid))
        if norm > 0:
            new_centroid = new_centroid / norm

        await db.execute(
            "UPDATE people SET centroid = ? WHERE id = ?",
            (_serialize_centroid(new_centroid), person_id),
        )
        await db.commit()

    async def create_person(
        self,
        name: str,
        db: aiosqlite.Connection,
        initial_embedding: np.ndarray | None = None,
    ) -> int:
        centroid = _serialize_centroid(initial_embedding) if initial_embedding is not None else None
        cur = await db.execute(
            "INSERT INTO people (name, created_at, centroid) VALUES (?, ?, ?)",
            (name, int(time.time()), centroid),
        )
        await db.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    async def merge_people(
        self,
        source_id: int,
        target_id: int,
        confirmed: bool,
        db: aiosqlite.Connection,
    ) -> None:
        """Move all faces from source_id to target_id; delete source person.

        Requires confirmed=True — callers must not skip the confirmation flag.
        """
        if not confirmed:
            raise ValueError("merge_people requires confirmed=True")

        await db.execute(
            "UPDATE faces SET person_id = ? WHERE person_id = ?",
            (target_id, source_id),
        )
        await db.execute("DELETE FROM people WHERE id = ?", (source_id,))
        await db.commit()

    async def delete_person(self, person_id: int, db: aiosqlite.Connection) -> None:
        """Return all faces to 'unreviewed'; delete person record.

        Face embeddings are never deleted (Rule: no photo data is touched).
        """
        await db.execute(
            """
            UPDATE faces
               SET person_id = NULL, assign_conf = NULL, assign_status = 'unreviewed'
             WHERE person_id = ?
            """,
            (person_id,),
        )
        await db.execute("DELETE FROM people WHERE id = ?", (person_id,))
        await db.commit()
