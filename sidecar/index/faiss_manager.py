"""FAISS index manager with automatic tier promotion.

Tier thresholds (OD-06):
  < 10 000         → IndexFlatIP          (exact cosine; instant at this size)
  10 000 – 250 000 → IndexIVFFlat/256     (IVF partitioning; sub-ms search)
  250 000+         → IndexIVFPQ/2048/PQ16 (product quantisation; ~300 MB at 1.5 M)

All embeddings must be L2-normalised before calling add(); inner-product
search then equals cosine similarity.

During promote() the old index continues answering search() calls — the new
index is trained outside the lock and swapped atomically when ready.
"""

import os
import threading
from typing import Literal

import faiss  # type: ignore[import-untyped]
import numpy as np

_DIM_DEFAULT = 512

_FLAT_LIMIT = 10_000
_IVF_FLAT_LIMIT = 250_000
_IVF_FLAT_NLIST = 256
_IVF_PQ_NLIST = 2048
_IVF_PQ_M = 16   # sub-quantizers
_IVF_PQ_NBITS = 8

Tier = Literal["flat", "ivf_flat", "ivf_pq"]


def _normalize(vec: np.ndarray) -> np.ndarray:
    """Return a copy of vec normalised to unit L2 length."""
    norm = float(np.linalg.norm(vec))
    return (vec / norm).astype(np.float32) if norm > 0 else vec.astype(np.float32)


class FAISSManager:
    """Manages a FAISS cosine-similarity index with automatic tier promotion.

    Thread-safe: add/search/save/load/promote may be called from any thread.
    """

    def __init__(self, data_dir: str, dim: int = _DIM_DEFAULT) -> None:
        self._dim = dim
        self._path = os.path.join(data_dir, "faces.index")
        self._lock = threading.RLock()
        self._tier: Tier = "flat"
        self._ids: list[int] = []
        self._vecs: list[np.ndarray] = []
        self._index: faiss.Index = self._new_flat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, embedding_id: int, embedding: np.ndarray) -> None:
        """Add one embedding with its database row ID to the index."""
        vec = _normalize(embedding)
        with self._lock:
            self._index.add_with_ids(  # type: ignore[attr-defined]
                vec.reshape(1, -1), np.array([embedding_id], dtype=np.int64)
            )
            self._ids.append(embedding_id)
            self._vecs.append(vec)

    def search(
        self, embedding: np.ndarray, k: int = 10
    ) -> list[tuple[int, float]]:
        """Return up to k (embedding_id, cosine_similarity) pairs, descending."""
        vec = _normalize(embedding).reshape(1, -1)
        with self._lock:
            ntotal = self._index.ntotal  # type: ignore[attr-defined]
            if ntotal == 0:
                return []
            k_actual = min(k, ntotal)
            distances, indices = self._index.search(vec, k_actual)  # type: ignore[attr-defined]
        pairs = [
            (int(idx), float(dist))
            for dist, idx in zip(distances[0], indices[0])
            if idx != -1
        ]
        return sorted(pairs, key=lambda x: x[1], reverse=True)

    def save(self) -> None:
        """Write the current index to {data_dir}/faces.index."""
        with self._lock:
            faiss.write_index(self._index, self._path)

    def load(self) -> None:
        """Load the index from disk. No-op if the file does not exist."""
        if not os.path.exists(self._path):
            return
        with self._lock:
            loaded = faiss.read_index(self._path)
            self._index = loaded
            self._tier = self._detect_tier(loaded)

    def needs_promotion(self) -> bool:
        """True when the active index tier has grown past its threshold."""
        ntotal = self._index.ntotal  # type: ignore[attr-defined]
        if self._tier == "flat":
            return ntotal >= _FLAT_LIMIT
        if self._tier == "ivf_flat":
            return ntotal >= _IVF_FLAT_LIMIT
        return False

    def promote(self) -> None:
        """Rebuild to the next tier. Old index is live until the atomic swap."""
        # Snapshot the data without holding the lock during training
        with self._lock:
            if not self.needs_promotion():
                return
            vecs = np.vstack(self._vecs).astype(np.float32)
            ids = np.array(self._ids, dtype=np.int64)
            current_tier = self._tier

        # Train + build OUTSIDE the lock — old index stays usable
        if current_tier == "flat":
            new_index = self._build_ivf_flat(vecs, ids)
            new_tier: Tier = "ivf_flat"
        else:
            new_index = self._build_ivf_pq(vecs, ids)
            new_tier = "ivf_pq"

        # Atomic swap
        with self._lock:
            self._index = new_index
            self._tier = new_tier

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _new_flat(self) -> faiss.Index:
        return faiss.IndexIDMap(faiss.IndexFlatIP(self._dim))

    def _build_ivf_flat(
        self, vecs: np.ndarray, ids: np.ndarray
    ) -> faiss.Index:
        quantizer = faiss.IndexFlatIP(self._dim)
        idx = faiss.IndexIVFFlat(
            quantizer, self._dim, _IVF_FLAT_NLIST, faiss.METRIC_INNER_PRODUCT
        )
        idx.train(vecs)
        idx.nprobe = min(32, _IVF_FLAT_NLIST)
        wrapped: faiss.Index = faiss.IndexIDMap(idx)
        wrapped.add_with_ids(vecs, ids)  # type: ignore[attr-defined]
        return wrapped

    def _build_ivf_pq(
        self, vecs: np.ndarray, ids: np.ndarray
    ) -> faiss.Index:
        quantizer = faiss.IndexFlatIP(self._dim)
        idx = faiss.IndexIVFPQ(
            quantizer, self._dim, _IVF_PQ_NLIST, _IVF_PQ_M, _IVF_PQ_NBITS
        )
        idx.train(vecs)
        idx.nprobe = min(32, _IVF_PQ_NLIST)
        wrapped = faiss.IndexIDMap(idx)
        wrapped.add_with_ids(vecs, ids)  # type: ignore[attr-defined]
        return wrapped

    @staticmethod
    def _detect_tier(index: faiss.Index) -> Tier:
        """Infer tier from a freshly loaded FAISS index."""
        inner = index.index if isinstance(index, faiss.IndexIDMap) else index  # type: ignore[attr-defined]
        inner = faiss.downcast_index(inner)
        if isinstance(inner, faiss.IndexIVFPQ):
            return "ivf_pq"
        if isinstance(inner, faiss.IndexIVFFlat):
            return "ivf_flat"
        return "flat"
