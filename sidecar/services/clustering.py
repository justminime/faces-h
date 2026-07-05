"""Clustering service: assigns face embeddings to person clusters.

All six reliability rules from docs/ARCHITECTURE.md § Reliability Rules are
enforced here at write time — they cannot be bypassed by callers.
"""

import time
from typing import Literal

import aiosqlite
import numpy as np

from config import get_config

AssignStatus = Literal["assigned", "uncertain", "unreviewed"]


def _serialize_centroid(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def _deserialize_centroid(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).copy()


class ClusteringService:
    """Assigns face embeddings to person clusters with reliability guarantees.

    Thresholds default to config.json (#107), resolved lazily so a service
    constructed at module-import time (before --data-dir is applied) still
    reads the user's configured values.
    """

    def __init__(
        self,
        auto_assign_threshold: float | None = None,
        uncertain_threshold: float | None = None,
    ) -> None:
        self._auto_assign_threshold = auto_assign_threshold
        self._uncertain_threshold = uncertain_threshold

    @property
    def auto_assign_threshold(self) -> float:
        if self._auto_assign_threshold is not None:
            return self._auto_assign_threshold
        return get_config().auto_assign_threshold

    @property
    def uncertain_threshold(self) -> float:
        if self._uncertain_threshold is not None:
            return self._uncertain_threshold
        return get_config().uncertain_threshold

    def _status(self, conf: float) -> AssignStatus:
        """Rule 1 + Rule 3: derive assignment status from cosine similarity."""
        if conf >= self.auto_assign_threshold:
            return "assigned"
        if conf >= self.uncertain_threshold:
            return "uncertain"
        return "unreviewed"

    async def _best_person(
        self,
        embedding: np.ndarray,
        db: aiosqlite.Connection,
    ) -> tuple[int | None, float]:
        """Find the best-matching person for an embedding (#106).

        Fast path: the FAISS face index shortlists the top-k most similar
        known faces; their (live, from the DB) owners are re-checked exactly
        against current centroids. If that shortlist can't produce an
        auto-assign-level match, fall back to the exhaustive centroid scan —
        decisions at or below the threshold (uncertain vs. new cluster) stay
        exactly as accurate as before the index existed.
        """
        best_person_id: int | None = None
        best_conf: float = -1.0

        candidate_people: set[int] = set()
        try:
            from services.face_index import get_face_index  # noqa: PLC0415

            index = get_face_index()
            candidate_faces = (
                index.candidate_face_ids(embedding) if index.size > 0 else []
            )
        except Exception:  # noqa: BLE001 — index is advisory; scan still works
            candidate_faces = []
        if candidate_faces:
            marks = ",".join("?" * len(candidate_faces))
            async with db.execute(
                f"SELECT DISTINCT person_id FROM faces"
                f" WHERE id IN ({marks}) AND person_id IS NOT NULL",
                candidate_faces,
            ) as cur:
                candidate_people = {int(r["person_id"]) for r in await cur.fetchall()}

        if candidate_people:
            marks = ",".join("?" * len(candidate_people))
            async with db.execute(
                f"SELECT id, centroid FROM people"
                f" WHERE id IN ({marks}) AND centroid IS NOT NULL",
                list(candidate_people),
            ) as cur:
                async for row in cur:
                    sim = float(np.dot(embedding, _deserialize_centroid(row["centroid"])))
                    if sim > best_conf:
                        best_conf = sim
                        best_person_id = int(row["id"])
            if best_conf >= self.auto_assign_threshold:
                return best_person_id, best_conf

        # Exhaustive fallback: empty/cold index, or no shortlisted person
        # reached the auto-assign gate.
        async with db.execute(
            "SELECT id, centroid FROM people WHERE centroid IS NOT NULL"
        ) as cur:
            async for row in cur:
                sim = float(np.dot(embedding, _deserialize_centroid(row["centroid"])))
                if sim > best_conf:
                    best_conf = sim
                    best_person_id = int(row["id"])
        return best_person_id, best_conf

    def _index_face(self, face_id: int, embedding: np.ndarray) -> None:
        """Add the face to the FAISS index (best effort — DB is the truth)."""
        try:
            from services.face_index import get_face_index  # noqa: PLC0415

            get_face_index().add(face_id, embedding)
        except Exception:  # noqa: BLE001
            pass

    async def assign_face(
        self,
        face_id: int,
        embedding: np.ndarray,
        db: aiosqlite.Connection,
        commit: bool = True,
    ) -> AssignStatus:
        """Match embedding to a person (FAISS shortlist + exact re-check, #106)
        and update the face row.

        Rule 1: assign_status is never 'assigned' unless
        assign_conf >= auto_assign_threshold.

        When no existing person is a good match (conf < uncertain_threshold),
        a new unnamed person cluster is seeded so the face appears in the
        gallery immediately, ordered by photo count.
        """
        best_person_id, best_conf = await self._best_person(embedding, db)

        if best_person_id is None or best_conf < self.uncertain_threshold:
            # No suitable cluster — seed a new unnamed person with this face as centroid.
            new_id = await self.create_person(
                "", db, initial_embedding=embedding, commit=commit
            )
            await db.execute(
                """UPDATE faces
                      SET person_id = ?,
                          assign_conf = 1.0,
                          assign_status = 'assigned',
                          embedding = ?,
                          embedding_id = ?
                    WHERE id = ?""",
                (new_id, embedding.astype(np.float32).tobytes(), face_id, face_id),
            )
            if commit:
                await db.commit()
            self._index_face(face_id, embedding)
            return "assigned"

        status = self._status(best_conf)
        # Rule 1: only link person_id when definitively assigned
        person_id_out: int | None = best_person_id if status == "assigned" else None
        suggested_person_id_out: int | None = best_person_id if status == "uncertain" else None

        await db.execute(
            """UPDATE faces
                  SET person_id = ?,
                      suggested_person_id = ?,
                      assign_conf = ?,
                      assign_status = ?,
                      embedding = ?,
                      embedding_id = ?
                WHERE id = ?""",
            (
                person_id_out,
                suggested_person_id_out,
                best_conf,
                status,
                embedding.astype(np.float32).tobytes(),
                face_id,
                face_id,
            ),
        )
        if commit:
            await db.commit()

        # Update centroid so future faces cluster more accurately.
        if status == "assigned":
            await self.update_centroid(best_person_id, embedding, db, commit=commit)

        self._index_face(face_id, embedding)
        return status

    async def update_centroid(
        self,
        person_id: int,
        embedding: np.ndarray,
        db: aiosqlite.Connection,
        commit: bool = True,
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
        if commit:
            await db.commit()

    async def rebuild_centroid(
        self,
        person_id: int,
        db: aiosqlite.Connection,
        commit: bool = True,
    ) -> None:
        """Recompute a person's centroid from their remaining assigned faces.

        Used after face rows are deleted (e.g. a photo was modified and its
        faces re-extracted) so stale embeddings stop voting in the centroid.
        The centroid is the L2-normalised mean of the embeddings of the
        person's currently 'assigned' faces. If the person has no remaining
        assigned faces, the existing centroid is left as-is.

        Never changes any face's assign_status or assign_conf (Rules 1-3
        untouched).
        """
        cur = await db.execute(
            """SELECT embedding FROM faces
                WHERE person_id = ?
                  AND assign_status = 'assigned'
                  AND embedding IS NOT NULL
                  AND photo_id IN (SELECT id FROM photos WHERE missing = 0)""",
            (person_id,),
        )
        rows = await cur.fetchall()
        if not rows:
            return

        embeddings = np.stack(
            [_deserialize_centroid(row["embedding"]) for row in rows]
        ).astype(np.float32)
        mean = embeddings.mean(axis=0)
        norm = float(np.linalg.norm(mean))
        if norm > 0:
            mean = mean / norm

        await db.execute(
            "UPDATE people SET centroid = ? WHERE id = ?",
            (_serialize_centroid(mean), person_id),
        )
        if commit:
            await db.commit()

    async def create_person(
        self,
        name: str,
        db: aiosqlite.Connection,
        initial_embedding: np.ndarray | None = None,
        commit: bool = True,
    ) -> int:
        centroid = _serialize_centroid(initial_embedding) if initial_embedding is not None else None
        cur = await db.execute(
            "INSERT INTO people (name, created_at, centroid) VALUES (?, ?, ?)",
            (name, int(time.time()), centroid),
        )
        if commit:
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
        # Re-point uncertain suggestions at the surviving person — the FK on
        # suggested_person_id would otherwise abort the DELETE below.
        await db.execute(
            "UPDATE faces SET suggested_person_id = ? WHERE suggested_person_id = ?",
            (target_id, source_id),
        )

        # Rebuild the surviving centroid from every assigned face and refresh
        # assign_conf against it (Rule 2) — the merged-in faces' stored conf
        # referenced the deleted source centroid (#115). Statuses are left
        # untouched: the user explicitly confirmed the merge, so nothing is
        # demoted here (Rule 6 governs automatic moves only).
        async with db.execute(
            "SELECT id, embedding FROM faces"
            " WHERE person_id = ? AND assign_status = 'assigned'"
            "   AND embedding IS NOT NULL",
            (target_id,),
        ) as cur:
            rows = await cur.fetchall()
        if rows:
            vecs = [_deserialize_centroid(r["embedding"]) for r in rows]
            mean = np.mean(vecs, axis=0).astype(np.float32)
            norm = float(np.linalg.norm(mean))
            new_centroid = (mean / norm).astype(np.float32) if norm > 0 else mean
            await db.execute(
                "UPDATE people SET centroid = ? WHERE id = ?",
                (_serialize_centroid(new_centroid), target_id),
            )
            for r in rows:
                conf = float(np.dot(_deserialize_centroid(r["embedding"]), new_centroid))
                await db.execute(
                    "UPDATE faces SET assign_conf = ? WHERE id = ?",
                    (conf, int(r["id"])),
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
        # Uncertain faces whose suggestion was this person lose the suggestion
        # and return to 'unreviewed' — also required by the FK on
        # suggested_person_id, which would otherwise abort the DELETE below.
        await db.execute(
            """
            UPDATE faces
               SET suggested_person_id = NULL, assign_conf = NULL,
                   assign_status = 'unreviewed'
             WHERE suggested_person_id = ?
            """,
            (person_id,),
        )
        await db.execute("DELETE FROM people WHERE id = ?", (person_id,))
        await db.commit()
