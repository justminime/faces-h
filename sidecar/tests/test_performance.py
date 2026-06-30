"""Performance benchmarks for faces-h.

Excluded from CI by default — run manually with:
    pytest -m slow sidecar/tests/test_performance.py -v

All three tests pass on a standard developer laptop (16 GB RAM, modern CPU).
"""

import io
import os
import time
from typing import Any

import aiosqlite
import faiss  # type: ignore[import-untyped]
import numpy as np
import pytest
from PIL import Image

from db.schema import ALL_TABLES, INDEXES
from services.scanner import reset_status, run_scan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color=(128, 128, 128)).save(buf, format="JPEG")
    return buf.getvalue()


async def _open_bench_db(path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA journal_mode=WAL")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


def _random_unit_vecs(n: int, dim: int = 512, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vecs = rng.random((n, dim), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return (vecs / norms).astype(np.float32)


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_scanner_throughput(tmp_path: Any) -> None:
    """Generate 10 000 synthetic JPEGs; scan rate must be >= 500 files/min."""
    reset_status()

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    jpeg = _make_jpeg_bytes()
    n = 10_000
    for i in range(n):
        (photos_dir / f"photo_{i:05d}.jpg").write_bytes(jpeg)

    async def _noop(msg: dict[str, Any]) -> None:
        pass

    db_path = str(tmp_path / "bench.db")
    conn = await _open_bench_db(db_path)
    try:
        start = time.monotonic()
        await run_scan(str(photos_dir), _noop, conn)
        elapsed = time.monotonic() - start
    finally:
        await conn.close()

    rate = n / elapsed * 60
    assert rate >= 500, f"Scanner throughput {rate:.0f} files/min is below 500/min threshold"


@pytest.mark.slow
def test_faiss_search_latency_at_scale() -> None:
    """Add 250 000 embeddings to IVFFlat; p99 search latency must be < 50 ms."""
    dim = 512
    n = 250_000
    nlist = 256
    n_queries = 100

    vecs = _random_unit_vecs(n, dim)

    quantizer = faiss.IndexFlatIP(dim)
    idx = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    idx.train(vecs)
    idx.add(vecs)
    idx.nprobe = 32

    # Warm-up
    idx.search(vecs[:1], 10)

    latencies: list[float] = []
    for i in range(n_queries):
        q = vecs[i : i + 1]
        t0 = time.perf_counter()
        idx.search(q, 10)
        latencies.append(time.perf_counter() - t0)

    latencies.sort()
    p99_ms = latencies[int(n_queries * 0.99) - 1] * 1000

    assert p99_ms < 50, f"p99 search latency {p99_ms:.1f} ms exceeds 50 ms threshold"


@pytest.mark.slow
def test_faiss_memory_at_1m_embeddings() -> None:
    """Build an IVFPQ index with 1 000 000 embeddings; RSS must be < 600 MB."""
    dim = 512
    nlist = 2_048
    pq_m = 16
    pq_nbits = 8
    n_train = 100_000
    n_total = 1_000_000
    batch_size = 10_000

    train_vecs = _random_unit_vecs(n_train, dim, seed=0)

    quantizer = faiss.IndexFlatIP(dim)
    idx = faiss.IndexIVFPQ(quantizer, dim, nlist, pq_m, pq_nbits)
    idx.metric_type = faiss.METRIC_INNER_PRODUCT
    idx.train(train_vecs)
    idx.nprobe = 32

    rng = np.random.default_rng(1)
    for start in range(0, n_total, batch_size):
        batch = rng.random((batch_size, dim), dtype=np.float32)
        norms = np.linalg.norm(batch, axis=1, keepdims=True)
        idx.add((batch / norms).astype(np.float32))

    import psutil  # local: a slow-only dep, not installed in CI's default run

    rss_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    assert rss_mb < 600, f"RSS {rss_mb:.0f} MB exceeds 600 MB threshold"
