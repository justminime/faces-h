"""Face-embedding FAISS index used to shortlist assignment candidates (#106).

Design: the index holds *face embeddings* keyed by face row id — immutable
entries, unlike person centroids which drift with every rolling update. A new
face queries the top-k most similar known faces; their (fresh, from the DB)
person memberships form the candidate set that assign_face re-checks exactly
against current centroids. Person merges and deletions therefore need no
index rebuild at all: the face→person mapping is resolved live per lookup,
so a deleted or merged-away cluster can never match.

The index is advisory — the database is the source of truth. Stale entries
(faces deleted by a re-extraction) simply resolve to no candidate. If the
shortlist can't produce an auto-assign-level match, assign_face falls back to
the exhaustive centroid scan, so uncertain/new-cluster decisions are exactly
as accurate as before.

Persisted to {data_dir}/faces.index; rebuilt from the faces table when the
file is missing or empty. Tier auto-promotion (Flat → IVFFlat → IVFPQ,
OD-06) happens transparently on add.
"""

from __future__ import annotations

import logging
import os
import threading

import aiosqlite
import numpy as np

from index.faiss_manager import FAISSManager

logger = logging.getLogger(__name__)

# Persist after this many un-saved additions (plus an explicit save() at the
# end of each scan) so a crash loses at most one batch — the rebuild path
# recovers the rest from the DB anyway.
_SAVE_EVERY = 256

# How many nearest faces to shortlist per query. Their distinct owners are
# typically a handful of people, re-checked exactly against live centroids.
_TOP_K = 20


class FaceIndex:
    """Process-wide face-embedding index with DB-backed rebuild."""

    def __init__(self, data_dir: str) -> None:
        self._mgr = FAISSManager(data_dir)
        self._lock = threading.Lock()
        self._ready = False
        self._unsaved = 0

    async def ensure_ready(self, db: aiosqlite.Connection) -> None:
        """Load the persisted index, or rebuild it from the faces table.

        Called at scan start; cheap after the first call.
        """
        with self._lock:
            if self._ready:
                return
            self._mgr.load()
        if self._mgr.ntotal == 0:
            count = 0
            async with db.execute(
                "SELECT id, embedding FROM faces WHERE embedding IS NOT NULL"
            ) as cur:
                async for row in cur:
                    emb = np.frombuffer(row["embedding"], dtype=np.float32).copy()
                    self._mgr.add(int(row["id"]), emb)
                    count += 1
            if count:
                self._mgr.save()
                logger.info("face index rebuilt from DB — %d embeddings", count)
        else:
            logger.info("face index loaded — %d embeddings", self._mgr.ntotal)
        with self._lock:
            self._ready = True

    def add(self, face_id: int, embedding: np.ndarray) -> None:
        """Insert one face embedding; promotes the tier and saves in batches."""
        self._mgr.add(face_id, embedding)
        if self._mgr.needs_promotion():
            logger.info("face index promoting tier at %d embeddings", self._mgr.ntotal)
            self._mgr.promote()
        with self._lock:
            self._unsaved += 1
            should_save = self._unsaved >= _SAVE_EVERY
            if should_save:
                self._unsaved = 0
        if should_save:
            self.save()

    def candidate_face_ids(self, embedding: np.ndarray, k: int = _TOP_K) -> list[int]:
        """Top-k most similar known face ids (advisory — recheck via DB)."""
        return [face_id for face_id, _ in self._mgr.search(embedding, k=k)]

    def remove(self, face_ids: list[int]) -> None:
        """Best-effort removal (stale entries are harmless, see module doc)."""
        self._mgr.remove(face_ids)

    def save(self) -> None:
        try:
            self._mgr.save()
        except Exception as exc:  # noqa: BLE001 — advisory; rebuildable from DB
            logger.warning("face index save failed: %s", exc)

    @property
    def size(self) -> int:
        return self._mgr.ntotal


_instance: FaceIndex | None = None
_instance_dir: str | None = None
_instance_lock = threading.Lock()


def get_face_index() -> FaceIndex:
    """Singleton per data dir; re-created if FACES_H_DATA_DIR changes (tests)."""
    global _instance, _instance_dir
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    with _instance_lock:
        if _instance is None or _instance_dir != data_dir:
            _instance = FaceIndex(data_dir)
            _instance_dir = data_dir
        return _instance


def reset_face_index() -> None:
    """Drop the singleton (tests)."""
    global _instance, _instance_dir
    with _instance_lock:
        _instance = None
        _instance_dir = None
