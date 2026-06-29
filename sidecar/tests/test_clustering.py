"""Tests for the clustering service and API reliability rules."""

import os
import time
from pathlib import Path

import aiosqlite
import numpy as np
import pytest

from db.schema import ALL_TABLES, INDEXES
from services.clustering import (
    ClusteringService,
    _deserialize_centroid,
    _serialize_centroid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_vec(dim: int = 512, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _vec_at_sim(centroid: np.ndarray, target_sim: float, perp_seed: int = 99) -> np.ndarray:
    """Return a unit vector with cosine similarity *target_sim* to *centroid*."""
    perp = _unit_vec(seed=perp_seed)
    perp = perp - np.dot(perp, centroid) * centroid
    perp = perp / np.linalg.norm(perp)
    v = (centroid * target_sim + perp * np.sqrt(max(0.0, 1 - target_sim**2))).astype(np.float32)
    return v / np.linalg.norm(v)


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


async def _insert_photo(conn: aiosqlite.Connection, path: str = "/test/img.jpg") -> int:
    cur = await conn.execute(
        "INSERT INTO photos (path, mtime) VALUES (?, ?)", (path, int(time.time()))
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


async def _insert_face(conn: aiosqlite.Connection, photo_id: int) -> int:
    cur = await conn.execute(
        "INSERT INTO faces (photo_id, detection_conf, assign_status) VALUES (?, ?, ?)",
        (photo_id, 0.99, "unreviewed"),
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


async def _insert_person(
    conn: aiosqlite.Connection,
    name: str,
    centroid: np.ndarray,
) -> int:
    cur = await conn.execute(
        "INSERT INTO people (name, created_at, centroid) VALUES (?, ?, ?)",
        (name, int(time.time()), _serialize_centroid(centroid)),
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


async def _insert_assigned_face(
    conn: aiosqlite.Connection,
    photo_id: int,
    person_id: int,
    conf: float = 0.80,
) -> int:
    cur = await conn.execute(
        """
        INSERT INTO faces
               (photo_id, detection_conf, person_id, assign_conf, assign_status)
        VALUES (?, ?, ?, ?, 'assigned')
        """,
        (photo_id, 0.99, person_id, conf),
    )
    await conn.commit()
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Threshold / reliability rule tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_above_auto_threshold_is_assigned(tmp_path: Path) -> None:
    """assign_conf >= 0.68 → assign_status = 'assigned' (Rule 1)."""
    svc = ClusteringService()
    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    photo_id = await _insert_photo(conn)
    face_id = await _insert_face(conn, photo_id)
    person_id = await _insert_person(conn, "Alice", centroid)

    # Embedding identical to centroid → similarity = 1.0
    status = await svc.assign_face(face_id, centroid.copy(), conn)
    assert status == "assigned"

    row = await (
        await conn.execute(
            "SELECT assign_status, assign_conf, person_id FROM faces WHERE id = ?", (face_id,)
        )
    ).fetchone()
    assert row is not None
    assert row["assign_status"] == "assigned"
    assert row["assign_conf"] >= 0.68
    assert row["person_id"] == person_id
    await conn.close()


@pytest.mark.asyncio
async def test_assign_mid_range_is_uncertain(tmp_path: Path) -> None:
    """0.50 <= assign_conf < 0.68 → assign_status = 'uncertain' (Rule 3)."""
    svc = ClusteringService(auto_assign_threshold=0.68, uncertain_threshold=0.50)
    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    embedding = _vec_at_sim(centroid, 0.60)

    photo_id = await _insert_photo(conn)
    face_id = await _insert_face(conn, photo_id)
    await _insert_person(conn, "Bob", centroid)

    status = await svc.assign_face(face_id, embedding, conn)
    assert status == "uncertain"

    row = await (
        await conn.execute(
            "SELECT assign_status, person_id FROM faces WHERE id = ?", (face_id,)
        )
    ).fetchone()
    assert row is not None
    assert row["assign_status"] == "uncertain"
    assert row["person_id"] is None  # Rule 1: uncertain faces are not linked to a person
    await conn.close()


@pytest.mark.asyncio
async def test_assign_below_uncertain_threshold_is_unreviewed(tmp_path: Path) -> None:
    """assign_conf < 0.50 → assign_status = 'unreviewed'."""
    svc = ClusteringService(auto_assign_threshold=0.68, uncertain_threshold=0.50)
    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    # Nearly orthogonal → similarity near 0
    embedding = _vec_at_sim(centroid, 0.10)

    photo_id = await _insert_photo(conn)
    face_id = await _insert_face(conn, photo_id)
    await _insert_person(conn, "Carol", centroid)

    status = await svc.assign_face(face_id, embedding, conn)
    assert status == "unreviewed"

    row = await (
        await conn.execute(
            "SELECT assign_status FROM faces WHERE id = ?", (face_id,)
        )
    ).fetchone()
    assert row is not None
    assert row["assign_status"] == "unreviewed"
    await conn.close()


@pytest.mark.asyncio
async def test_rule1_never_assigned_below_threshold(tmp_path: Path) -> None:
    """Rule 1: assign_status is never 'assigned' when conf < auto_assign_threshold."""
    svc = ClusteringService(auto_assign_threshold=0.99)  # extremely high threshold
    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    embedding = _vec_at_sim(centroid, 0.80)  # below 0.99 threshold

    photo_id = await _insert_photo(conn)
    face_id = await _insert_face(conn, photo_id)
    await _insert_person(conn, "Dave", centroid)

    status = await svc.assign_face(face_id, embedding, conn)
    assert status != "assigned", "Rule 1 violated: assigned without meeting threshold"
    await conn.close()


# ---------------------------------------------------------------------------
# Centroid update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_centroid_update_moves_toward_new_embedding(tmp_path: Path) -> None:
    """Rolling average centroid moves toward the new embedding after update."""
    svc = ClusteringService()
    conn = await _open_db(tmp_path)

    old_centroid = _unit_vec(seed=1)
    person_id = await _insert_person(conn, "Eve", old_centroid)

    new_embedding = _unit_vec(seed=99)
    await svc.update_centroid(person_id, new_embedding, conn)

    row = await (
        await conn.execute("SELECT centroid FROM people WHERE id = ?", (person_id,))
    ).fetchone()
    assert row is not None
    updated = _deserialize_centroid(row["centroid"])

    sim_after = float(np.dot(updated, new_embedding))
    sim_before = float(np.dot(old_centroid, new_embedding))
    assert sim_after > sim_before, "Centroid did not move toward new embedding"
    assert float(np.linalg.norm(updated)) == pytest.approx(1.0, abs=1e-4)
    await conn.close()


# ---------------------------------------------------------------------------
# Delete person
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_person_returns_faces_to_unreviewed(tmp_path: Path) -> None:
    """DELETE person: all faces go to 'unreviewed'; no face rows deleted."""
    svc = ClusteringService()
    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    person_id = await _insert_person(conn, "Frank", centroid)
    photo_id = await _insert_photo(conn)

    face_ids = [await _insert_assigned_face(conn, photo_id, person_id) for _ in range(3)]

    await svc.delete_person(person_id, conn)

    person_row = await (
        await conn.execute("SELECT id FROM people WHERE id = ?", (person_id,))
    ).fetchone()
    assert person_row is None, "Person record should be deleted"

    for fid in face_ids:
        row = await (
            await conn.execute(
                "SELECT assign_status, person_id FROM faces WHERE id = ?", (fid,)
            )
        ).fetchone()
        assert row is not None, "Face record must not be deleted"
        assert row["assign_status"] == "unreviewed"
        assert row["person_id"] is None
    await conn.close()


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_moves_faces_and_deletes_source(tmp_path: Path) -> None:
    """merge_people: moves all source faces to target; deletes source person."""
    svc = ClusteringService()
    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    source_id = await _insert_person(conn, "Ghost", centroid)
    target_id = await _insert_person(conn, "Real", centroid)
    photo_id = await _insert_photo(conn)

    face_ids = [await _insert_assigned_face(conn, photo_id, source_id) for _ in range(2)]

    await svc.merge_people(source_id, target_id, confirmed=True, db=conn)

    src_row = await (
        await conn.execute("SELECT id FROM people WHERE id = ?", (source_id,))
    ).fetchone()
    assert src_row is None

    for fid in face_ids:
        row = await (
            await conn.execute("SELECT person_id FROM faces WHERE id = ?", (fid,))
        ).fetchone()
        assert row is not None
        assert row["person_id"] == target_id
    await conn.close()


@pytest.mark.asyncio
async def test_merge_requires_confirmed(tmp_path: Path) -> None:
    """merge_people raises ValueError when confirmed=False."""
    svc = ClusteringService()
    conn = await _open_db(tmp_path)

    centroid = _unit_vec()
    source_id = await _insert_person(conn, "A", centroid)
    target_id = await _insert_person(conn, "B", centroid)

    with pytest.raises(ValueError, match="confirmed"):
        await svc.merge_people(source_id, target_id, confirmed=False, db=conn)
    await conn.close()


# ---------------------------------------------------------------------------
# Rule 5 — API endpoint: only assigned faces returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_people_photos_endpoint_excludes_uncertain_and_unreviewed(
    tmp_path: Path,
) -> None:
    """GET /people/{id}/photos never returns uncertain or unreviewed faces (Rule 5)."""
    from httpx import AsyncClient, ASGITransport

    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)

    from main import app

    conn = await _open_db(tmp_path)

    centroid = _unit_vec(seed=1)
    person_id = await _insert_person(conn, "Alice", centroid)
    photo_id = await _insert_photo(conn, "/test/photo1.jpg")

    # Insert one face per status
    assigned_id = await _insert_assigned_face(conn, photo_id, person_id)
    await conn.execute(
        "INSERT INTO faces (photo_id, detection_conf, assign_conf, assign_status) VALUES (?, ?, ?, ?)",
        (photo_id, 0.9, 0.60, "uncertain"),
    )
    await conn.commit()
    await conn.execute(
        "INSERT INTO faces (photo_id, detection_conf, assign_status) VALUES (?, ?, ?)",
        (photo_id, 0.9, "unreviewed"),
    )
    await conn.commit()
    await conn.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/people/{person_id}/photos")

    assert resp.status_code == 200
    photos = resp.json()
    face_ids_returned = [p["face_id"] for p in photos]
    assert assigned_id in face_ids_returned
    assert all(p["face_id"] == assigned_id for p in photos), (
        f"Non-assigned faces returned: {face_ids_returned}"
    )
