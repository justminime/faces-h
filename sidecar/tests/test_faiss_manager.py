"""Tests for the FAISS index manager."""

from pathlib import Path

import numpy as np
import pytest

from index.faiss_manager import FAISSManager, _FLAT_LIMIT


def _rand_unit(dim: int = 512, seed: int | None = None) -> np.ndarray:
    """Return one random unit-length float32 vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _rand_unit_batch(n: int, dim: int = 512, seed: int = 0) -> np.ndarray:
    """Return n random unit-length float32 vectors, shape (n, dim)."""
    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norms


@pytest.mark.asyncio
async def test_nearest_neighbour_found_after_100_adds(tmp_path: Path) -> None:
    """Search on 100 embeddings returns the query itself as the top hit."""
    mgr = FAISSManager(str(tmp_path))
    vecs = _rand_unit_batch(100)
    for i, v in enumerate(vecs):
        mgr.add(i, v)

    # Query using the exact vector at index 42
    results = mgr.search(vecs[42], k=5)
    assert len(results) > 0
    top_id, top_sim = results[0]
    assert top_id == 42
    assert top_sim == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_search_results_sorted_descending(tmp_path: Path) -> None:
    """search() always returns pairs sorted by cosine similarity, descending."""
    mgr = FAISSManager(str(tmp_path))
    vecs = _rand_unit_batch(50)
    for i, v in enumerate(vecs):
        mgr.add(i, v)

    results = mgr.search(vecs[0], k=50)
    sims = [s for _, s in results]
    assert sims == sorted(sims, reverse=True)


@pytest.mark.asyncio
async def test_promotion_to_ivf_flat(tmp_path: Path) -> None:
    """After crossing the flat threshold, needs_promotion() is True and
    promote() rebuilds the index to IndexIVFFlat."""
    mgr = FAISSManager(str(tmp_path))
    n = _FLAT_LIMIT + 1
    vecs = _rand_unit_batch(n)

    for i, v in enumerate(vecs):
        mgr.add(i, v)

    assert mgr.needs_promotion() is True
    assert mgr._tier == "flat"

    mgr.promote()

    assert mgr._tier == "ivf_flat"
    assert mgr.needs_promotion() is False
    # Search must still work after promotion
    results = mgr.search(vecs[0], k=5)
    assert len(results) > 0


@pytest.mark.asyncio
async def test_save_load_round_trip(tmp_path: Path) -> None:
    """Save then load produces identical search results."""
    mgr = FAISSManager(str(tmp_path))
    vecs = _rand_unit_batch(100)
    for i, v in enumerate(vecs):
        mgr.add(i, v)

    query = vecs[7]
    before = mgr.search(query, k=5)
    mgr.save()

    mgr2 = FAISSManager(str(tmp_path))
    mgr2.load()
    after = mgr2.search(query, k=5)

    assert [eid for eid, _ in before] == [eid for eid, _ in after]
    for (_, s1), (_, s2) in zip(before, after):
        assert s1 == pytest.approx(s2, abs=1e-5)


@pytest.mark.asyncio
async def test_load_detects_tier_from_disk(tmp_path: Path) -> None:
    """load() correctly restores the tier that was active when save() was called."""
    mgr = FAISSManager(str(tmp_path))
    vecs = _rand_unit_batch(_FLAT_LIMIT + 1)
    for i, v in enumerate(vecs):
        mgr.add(i, v)
    mgr.promote()
    mgr.save()

    mgr2 = FAISSManager(str(tmp_path))
    mgr2.load()
    assert mgr2._tier == "ivf_flat"


@pytest.mark.asyncio
async def test_search_empty_index_returns_empty(tmp_path: Path) -> None:
    """Searching an empty index returns an empty list, not an error."""
    mgr = FAISSManager(str(tmp_path))
    result = mgr.search(_rand_unit())
    assert result == []


@pytest.mark.asyncio
async def test_old_index_serves_during_promote(tmp_path: Path) -> None:
    """A search issued concurrently with promote() completes without error."""
    import threading

    mgr = FAISSManager(str(tmp_path))
    vecs = _rand_unit_batch(_FLAT_LIMIT + 1)
    for i, v in enumerate(vecs):
        mgr.add(i, v)

    search_results: list = []
    errors: list = []

    def do_search() -> None:
        try:
            search_results.extend(mgr.search(vecs[0], k=5))
        except Exception as exc:
            errors.append(exc)

    searcher = threading.Thread(target=do_search)
    searcher.start()
    mgr.promote()
    searcher.join()

    assert not errors
