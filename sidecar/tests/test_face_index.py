"""Tests for the FAISS-backed assignment shortlist (#106)."""

import os
import time
from pathlib import Path

import aiosqlite
import numpy as np
import pytest

from db.schema import ALL_TABLES, INDEXES
from services.clustering import ClusteringService, _serialize_centroid
from services.face_index import FaceIndex, get_face_index, reset_face_index


def _unit(seed: int, dim: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _near(base: np.ndarray, sim: float, seed: int = 99) -> np.ndarray:
    perp = _unit(seed)
    perp = perp - np.dot(perp, base) * base
    perp = perp / np.linalg.norm(perp)
    v = (base * sim + perp * np.sqrt(max(0.0, 1 - sim**2))).astype(np.float32)
    return v / np.linalg.norm(v)


async def _open_db(path: Path) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(path / "faces.db"))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


@pytest.fixture(autouse=True)
def _fresh_index(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    reset_face_index()


# ---------------------------------------------------------------------------
# FaceIndex behavior
# ---------------------------------------------------------------------------


def test_add_and_candidates(tmp_path: Path) -> None:
    idx = FaceIndex(str(tmp_path))
    base = _unit(1)
    idx.add(1, base)
    idx.add(2, _near(base, 0.9, seed=5))
    idx.add(3, _unit(7))  # dissimilar

    candidates = idx.candidate_face_ids(base, k=2)
    assert candidates[0] == 1
    assert 2 in candidates
    assert idx.size == 3


def test_persist_and_reload(tmp_path: Path) -> None:
    idx = FaceIndex(str(tmp_path))
    idx.add(42, _unit(1))
    idx.save()

    idx2 = FaceIndex(str(tmp_path))
    idx2._mgr.load()
    assert idx2.candidate_face_ids(_unit(1), k=1) == [42]


@pytest.mark.asyncio
async def test_ensure_ready_rebuilds_from_db(tmp_path: Path) -> None:
    """Missing index file → rebuilt from the faces table (DB is the truth)."""
    db = await _open_db(tmp_path)
    try:
        emb = _unit(3)
        await db.execute(
            "INSERT INTO photos (id, path, mtime) VALUES (1, '/a.jpg', 1)"
        )
        await db.execute(
            """INSERT INTO faces (id, photo_id, detection_conf, assign_status, embedding)
               VALUES (7, 1, 0.9, 'unreviewed', ?)""",
            (emb.tobytes(),),
        )
        await db.commit()

        idx = get_face_index()
        await idx.ensure_ready(db)
        assert idx.size == 1
        assert idx.candidate_face_ids(emb, k=1) == [7]
    finally:
        await db.close()


def test_remove_drops_candidates(tmp_path: Path) -> None:
    idx = FaceIndex(str(tmp_path))
    idx.add(1, _unit(1))
    idx.add(2, _unit(2))
    idx.remove([1])
    assert 1 not in idx.candidate_face_ids(_unit(1), k=2)


# ---------------------------------------------------------------------------
# assign_face equivalence with the index active
# ---------------------------------------------------------------------------


async def _seed_person_with_face(
    db: aiosqlite.Connection, name: str, centroid: np.ndarray, face_id: int
) -> int:
    cur = await db.execute(
        "INSERT INTO people (name, created_at, centroid) VALUES (?, ?, ?)",
        (name, int(time.time()), _serialize_centroid(centroid)),
    )
    person_id = int(cur.lastrowid or 0)
    await db.execute(
        "INSERT OR IGNORE INTO photos (id, path, mtime) VALUES (1, '/p.jpg', 1)"
    )
    await db.execute(
        """INSERT INTO faces (id, photo_id, detection_conf, person_id,
                              assign_conf, assign_status, embedding, embedding_id)
           VALUES (?, 1, 0.9, ?, 0.95, 'assigned', ?, ?)""",
        (face_id, person_id, centroid.tobytes(), face_id),
    )
    await db.commit()
    get_face_index().add(face_id, centroid)
    return person_id


@pytest.mark.asyncio
async def test_assign_uses_index_shortlist_for_strong_match(tmp_path: Path) -> None:
    """A face similar to an indexed person's face is assigned to that person
    via the shortlist path, with correct conf and embedding_id set."""
    db = await _open_db(tmp_path)
    try:
        centroid = _unit(1)
        person_id = await _seed_person_with_face(db, "Alice", centroid, face_id=100)

        emb = _near(centroid, 0.9, seed=11)
        cur = await db.execute(
            "INSERT INTO faces (photo_id, detection_conf, assign_status) VALUES (1, 0.9, 'unreviewed')"
        )
        await db.commit()
        new_face = int(cur.lastrowid or 0)

        status = await ClusteringService().assign_face(new_face, emb, db)
        assert status == "assigned"

        row = await (
            await db.execute(
                "SELECT person_id, assign_conf, embedding_id FROM faces WHERE id = ?",
                (new_face,),
            )
        ).fetchone()
        assert row is not None
        assert row["person_id"] == person_id
        assert row["assign_conf"] == pytest.approx(0.9, abs=0.02)
        assert row["embedding_id"] == new_face, "embedding_id must track the index entry"
        assert new_face in get_face_index().candidate_face_ids(emb, k=3)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fallback_scan_when_shortlist_misses(tmp_path: Path) -> None:
    """A person whose faces are NOT in the index (cold index) is still found
    via the exhaustive fallback — no behavior change below the fast path."""
    db = await _open_db(tmp_path)
    try:
        centroid = _unit(2)
        # Person exists in DB with no indexed faces at all.
        cur = await db.execute(
            "INSERT INTO people (name, created_at, centroid) VALUES ('Bob', 0, ?)",
            (_serialize_centroid(centroid),),
        )
        person_id = int(cur.lastrowid or 0)
        await db.execute(
            "INSERT OR IGNORE INTO photos (id, path, mtime) VALUES (1, '/p.jpg', 1)"
        )
        cur = await db.execute(
            "INSERT INTO faces (photo_id, detection_conf, assign_status) VALUES (1, 0.9, 'unreviewed')"
        )
        await db.commit()
        face_id = int(cur.lastrowid or 0)

        emb = _near(centroid, 0.8, seed=13)
        status = await ClusteringService().assign_face(face_id, emb, db)
        assert status == "assigned"
        row = await (
            await db.execute("SELECT person_id FROM faces WHERE id = ?", (face_id,))
        ).fetchone()
        assert row is not None and row["person_id"] == person_id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_merged_away_person_cannot_match(tmp_path: Path) -> None:
    """After a merge, index entries of the source's faces resolve to the
    surviving person — a deleted cluster can never be matched (#106 AC)."""
    db = await _open_db(tmp_path)
    try:
        centroid = _unit(1)
        source_id = await _seed_person_with_face(db, "Ghost", centroid, face_id=200)
        cur = await db.execute(
            "INSERT INTO people (name, created_at, centroid) VALUES ('Real', 0, ?)",
            (_serialize_centroid(centroid),),
        )
        target_id = int(cur.lastrowid or 0)
        await db.commit()

        svc = ClusteringService()
        await svc.merge_people(source_id, target_id, confirmed=True, db=db)

        emb = _near(centroid, 0.9, seed=17)
        cur = await db.execute(
            "INSERT INTO faces (photo_id, detection_conf, assign_status) VALUES (1, 0.9, 'unreviewed')"
        )
        await db.commit()
        new_face = int(cur.lastrowid or 0)

        status = await svc.assign_face(new_face, emb, db)
        assert status == "assigned"
        row = await (
            await db.execute("SELECT person_id FROM faces WHERE id = ?", (new_face,))
        ).fetchone()
        assert row is not None
        assert row["person_id"] == target_id, "must resolve to the surviving person"
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Scale benchmark (slow — not in CI)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_shortlist_stays_fast_as_index_grows(tmp_path: Path) -> None:
    """#106 AC: candidate lookup cost stays roughly flat as the library grows
    (top-k FAISS query), unlike the O(n) centroid scan it replaces. Also
    exercises tier auto-promotion (flat → ivf_flat at 10k)."""
    idx = FaceIndex(str(tmp_path))
    rng = np.random.default_rng(0)

    def _grow(to_size: int) -> None:
        while idx.size < to_size:
            v = rng.standard_normal(512).astype(np.float32)
            idx.add(idx.size + 1, v / np.linalg.norm(v))

    def _avg_query_ms(n: int = 50) -> float:
        probe = rng.standard_normal(512).astype(np.float32)
        probe /= np.linalg.norm(probe)
        start = time.perf_counter()
        for _ in range(n):
            idx.candidate_face_ids(probe)
        return (time.perf_counter() - start) / n * 1000

    _grow(1_000)
    t_small = _avg_query_ms()
    _grow(12_000)  # crosses the 10k flat→ivf_flat promotion threshold
    t_large = _avg_query_ms()

    assert idx._mgr._tier == "ivf_flat", "tier promotion must have happened"
    # IVF at 12x the size must not be dramatically slower than flat at 1k.
    assert t_large < max(t_small * 10, 5.0), (
        f"query time grew too much: {t_small:.2f}ms → {t_large:.2f}ms"
    )
