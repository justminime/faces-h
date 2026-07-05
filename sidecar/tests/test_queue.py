"""Tests for the uncertain face review queue API."""

import os

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from db.schema import ALL_TABLES, INDEXES


async def _init_db(tmp_path: str) -> None:
    """Create schema in the temp database."""
    os.environ["FACES_H_DATA_DIR"] = tmp_path
    from db.database import get_db

    async with get_db() as db:
        for stmt in ALL_TABLES:
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


async def _seed_uncertain_face(tmp_path: str) -> np.ndarray:
    """Insert a photo, person with centroid, and one uncertain face."""
    from db.database import get_db

    embedding = np.random.randn(512).astype(np.float32)
    norm = float(np.linalg.norm(embedding))
    embedding = (embedding / norm).astype(np.float32)

    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO photos (id, path, mtime, scanned_at) VALUES (1, '/fake/img.jpg', 0, 0)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO people (id, name, created_at, centroid) VALUES (1, 'Alice', 0, ?)",
            (embedding.tobytes(),),
        )
        await db.execute(
            """
            INSERT OR IGNORE INTO faces (id, photo_id, detection_conf, assign_status,
                               assign_conf, suggested_person_id, embedding)
            VALUES (1, 1, 0.99, 'uncertain', 0.60, 1, ?)
            """,
            (embedding.tobytes(),),
        )
        await db.commit()

    return embedding


async def test_get_uncertain_returns_only_uncertain(tmp_path: pytest.TempPathFactory) -> None:
    """GET /queue/uncertain returns only faces with assign_status='uncertain'."""
    data_dir = str(tmp_path)
    await _init_db(data_dir)
    await _seed_uncertain_face(data_dir)

    from db.database import get_db

    # insert an assigned face — should NOT appear
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO faces (id, photo_id, detection_conf, assign_status, person_id, assign_conf)
            VALUES (2, 1, 0.99, 'assigned', 1, 0.90)
            """
        )
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/queue/uncertain")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["face_id"] == 1
    assert items[0]["suggested_person_id"] == 1
    assert items[0]["face_crop_url"] == "/faces/1/crop"


async def test_confirm_promotes_to_assigned(tmp_path: pytest.TempPathFactory) -> None:
    """POST /queue/{face_id}/confirm sets assign_status='assigned' and person_id."""
    data_dir = str(tmp_path)
    await _init_db(data_dir)
    await _seed_uncertain_face(data_dir)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/queue/1/confirm", json={"person_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["assign_status"] == "assigned"
    assert body["person_id"] == 1

    from db.database import get_db

    async with get_db() as db:
        row = await (
            await db.execute(
                "SELECT assign_status, person_id, suggested_person_id FROM faces WHERE id = 1"
            )
        ).fetchone()
    assert row is not None
    assert row["assign_status"] == "assigned"
    assert row["person_id"] == 1
    assert row["suggested_person_id"] is None


async def test_confirm_recomputes_conf_against_confirmed_person(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Rule 2 (#103): confirming stores cosine similarity to the *confirmed*
    person's centroid, not the stale suggestion-time value (seeded 0.60)."""
    data_dir = str(tmp_path)
    await _init_db(data_dir)
    # Seeded face embedding equals Alice's centroid → similarity 1.0.
    await _seed_uncertain_face(data_dir)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/queue/1/confirm", json={"person_id": 1})
    assert r.status_code == 200
    assert r.json()["assign_conf"] == pytest.approx(1.0, abs=1e-4)

    from db.database import get_db

    async with get_db() as db:
        row = await (
            await db.execute("SELECT assign_conf FROM faces WHERE id = 1")
        ).fetchone()
    assert row is not None
    assert row["assign_conf"] == pytest.approx(1.0, abs=1e-4)


async def test_confirm_to_other_person_uses_that_centroid(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Confirming to someone other than the suggestion computes conf vs. that
    person's centroid (near-orthogonal here → conf far from the stale 0.60)."""
    data_dir = str(tmp_path)
    await _init_db(data_dir)
    embedding = await _seed_uncertain_face(data_dir)

    # A second person with an orthogonal centroid.
    perp = np.random.randn(512).astype(np.float32)
    perp -= np.dot(perp, embedding) * embedding
    perp /= float(np.linalg.norm(perp))

    from db.database import get_db

    async with get_db() as db:
        await db.execute(
            "INSERT INTO people (id, name, created_at, centroid) VALUES (2, 'Bob', 0, ?)",
            (perp.tobytes(),),
        )
        await db.commit()

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/queue/1/confirm", json={"person_id": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["person_id"] == 2
    assert body["assign_conf"] == pytest.approx(0.0, abs=1e-3)


async def test_confirm_unknown_person_returns_404(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Confirming to a nonexistent person is a 404, not an FK 500 (#103)."""
    data_dir = str(tmp_path)
    await _init_db(data_dir)
    await _seed_uncertain_face(data_dir)

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/queue/1/confirm", json={"person_id": 9999})
    assert r.status_code == 404
