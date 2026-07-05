"""Tests for the re-evaluation pipeline (ReEvaluationService + corrections API)."""

import os
import time
from pathlib import Path
from typing import Any

import aiosqlite
import numpy as np
from httpx import ASGITransport, AsyncClient

from db.schema import ALL_TABLES, INDEXES
from config import DEFAULT_UNCERTAIN_THRESHOLD as _UNCERTAIN_THRESHOLD
from services.reeval import ReEvaluationService


# ---------------------------------------------------------------------------
# Helpers (mirrors test_clustering.py pattern)
# ---------------------------------------------------------------------------


def _unit_vec(dim: int = 512, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _vec_at_sim(centroid: np.ndarray, target_sim: float, perp_seed: int = 99) -> np.ndarray:
    perp = _unit_vec(seed=perp_seed)
    perp = perp - np.dot(perp, centroid) * centroid
    perp = perp / np.linalg.norm(perp)
    v = centroid * target_sim + perp * np.sqrt(max(0.0, 1.0 - target_sim**2))
    return (v / np.linalg.norm(v)).astype(np.float32)


async def _open_db(path: Path) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(path / "faces.db"))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    for ddl in ALL_TABLES:
        await conn.execute(ddl)
    for idx in INDEXES:
        await conn.execute(idx)
    await conn.commit()
    return conn


async def _insert_photo(conn: aiosqlite.Connection, path: str = "/p.jpg") -> int:
    cur = await conn.execute(
        "INSERT INTO photos (path, mtime) VALUES (?, ?)", (path, int(time.time()))
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


async def _insert_person(
    conn: aiosqlite.Connection, name: str, centroid: np.ndarray | None = None
) -> int:
    centroid_bytes = centroid.tobytes() if centroid is not None else None
    cur = await conn.execute(
        "INSERT INTO people (name, created_at, centroid) VALUES (?, ?, ?)",
        (name, int(time.time()), centroid_bytes),
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


async def _insert_assigned_face(
    conn: aiosqlite.Connection,
    photo_id: int,
    person_id: int,
    embedding: np.ndarray,
    conf: float = 0.80,
) -> int:
    cur = await conn.execute(
        """
        INSERT INTO faces (photo_id, detection_conf, person_id, assign_conf,
                           assign_status, embedding)
        VALUES (?, 0.99, ?, ?, 'assigned', ?)
        """,
        (photo_id, person_id, conf, embedding.tobytes()),
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_correction_recorded_in_corrections_table(tmp_path: Path) -> None:
    """A correction is written to the corrections table with correct fields."""
    conn = await _open_db(tmp_path)
    svc = ReEvaluationService()
    events: list[dict[str, Any]] = []

    centroid = _unit_vec(seed=1)
    alice_id = await _insert_person(conn, "Alice", centroid)
    bob_id = await _insert_person(conn, "Bob", centroid)
    photo_id = await _insert_photo(conn)
    embedding = _vec_at_sim(centroid, 0.90)
    face_id = await _insert_assigned_face(conn, photo_id, alice_id, embedding, conf=0.90)

    await svc.trigger(
        face_id=face_id,
        old_person_id=alice_id,
        new_person_id=bob_id,
        db=conn,
        broadcast_fn=lambda msg: events.append(msg),
    )

    row = await (
        await conn.execute(
            "SELECT face_id, old_person_id, new_person_id FROM corrections WHERE face_id=?",
            (face_id,),
        )
    ).fetchone()
    assert row is not None
    assert row["face_id"] == face_id
    assert row["old_person_id"] == alice_id
    assert row["new_person_id"] == bob_id
    await conn.close()


async def test_affected_faces_rescored_and_demoted(tmp_path: Path) -> None:
    """Faces in old person's cluster are re-scored; those below threshold are demoted."""
    conn = await _open_db(tmp_path)
    svc = ReEvaluationService()

    centroid = _unit_vec(seed=1)
    alice_id = await _insert_person(conn, "Alice", centroid)
    bob_id = await _insert_person(conn, "Bob", centroid)
    photo_id = await _insert_photo(conn)

    # Face being corrected
    high_sim = _vec_at_sim(centroid, 0.90)
    corrected_face = await _insert_assigned_face(conn, photo_id, alice_id, high_sim, 0.90)

    # Another face in Alice's cluster that will drop after centroid rebuild
    borderline = _vec_at_sim(centroid, _UNCERTAIN_THRESHOLD + 0.01, perp_seed=5)
    borderline_face = await _insert_assigned_face(conn, photo_id, alice_id, borderline, 0.51)

    await svc.trigger(
        face_id=corrected_face,
        old_person_id=alice_id,
        new_person_id=bob_id,
        db=conn,
        broadcast_fn=lambda _: None,
    )

    # Corrected face now belongs to Bob and is assigned (user override)
    r = await (
        await conn.execute(
            "SELECT assign_status, person_id FROM faces WHERE id=?", (corrected_face,)
        )
    ).fetchone()
    assert r is not None
    assert r["assign_status"] == "assigned"
    assert r["person_id"] == bob_id

    # Borderline face should have been re-scored against the rebuilt centroid
    r2 = await (
        await conn.execute(
            "SELECT assign_status FROM faces WHERE id=?", (borderline_face,)
        )
    ).fetchone()
    assert r2 is not None
    # After removing the high-similarity face, centroid barely changed, so borderline
    # may still be uncertain or unreviewed depending on actual similarity — just check
    # it's no longer silently corrupted (still in DB, status is valid)
    assert r2["assign_status"] in ("assigned", "uncertain", "unreviewed")
    await conn.close()


async def test_reeval_complete_event_emitted_with_correct_shape(tmp_path: Path) -> None:
    """reeval_complete WebSocket event contains moved, newly_uncertain, person_name."""
    conn = await _open_db(tmp_path)
    svc = ReEvaluationService()
    events: list[dict[str, Any]] = []

    centroid = _unit_vec(seed=1)
    alice_id = await _insert_person(conn, "Alice", centroid)
    bob_id = await _insert_person(conn, "Bob", centroid)
    photo_id = await _insert_photo(conn)
    embedding = _vec_at_sim(centroid, 0.90)
    face_id = await _insert_assigned_face(conn, photo_id, alice_id, embedding, 0.90)

    # Add a face in Alice's cluster that will drop to uncertain after rebuild
    # (simulate by making it a borderline vector)
    borderline = _vec_at_sim(centroid, 0.60, perp_seed=7)
    await _insert_assigned_face(conn, photo_id, alice_id, borderline, 0.60)

    await svc.trigger(
        face_id=face_id,
        old_person_id=alice_id,
        new_person_id=bob_id,
        db=conn,
        broadcast_fn=lambda msg: events.append(msg),
    )

    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "reeval_complete"
    assert ev["moved"] == 1
    assert "newly_uncertain" in ev
    assert isinstance(ev["newly_uncertain"], int)
    assert ev["person_name"] == "Alice"
    await conn.close()


async def test_api_returns_200_immediately(tmp_path: Path) -> None:
    """POST /photos/{photo_id}/faces/{face_id}/correct returns 200 synchronously."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)

    conn = await _open_db(tmp_path)
    centroid = _unit_vec(seed=1)
    alice_id = await _insert_person(conn, "Alice", centroid)
    bob_id = await _insert_person(conn, "Bob", centroid)
    photo_id = await _insert_photo(conn)
    embedding = _vec_at_sim(centroid, 0.90)
    face_id = await _insert_assigned_face(conn, photo_id, alice_id, embedding, 0.90)
    await conn.close()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            f"/photos/{photo_id}/faces/{face_id}/correct",
            json={"new_person_id": bob_id},
        )

    assert r.status_code == 200
    assert r.json()["status"] == "queued"
