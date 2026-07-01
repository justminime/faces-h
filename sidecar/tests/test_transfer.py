"""Tests for /export and /import: carrying names across libraries (#80)."""

import base64
import os
from pathlib import Path

import numpy as np
from httpx import ASGITransport, AsyncClient

from db.schema import ALL_TABLES, INDEXES


def _unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(512).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


async def _init(tmp_path: str) -> None:
    os.environ["FACES_H_DATA_DIR"] = tmp_path
    from db.database import get_db

    async with get_db() as db:
        for stmt in ALL_TABLES:
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


async def _add_person(pid: int, name: str, centroid: np.ndarray | None) -> None:
    """Insert a person. Unnamed clusters use name='' (schema: name is NOT NULL)."""
    from db.database import get_db

    blob = centroid.astype(np.float32).tobytes() if centroid is not None else None
    async with get_db() as db:
        await db.execute(
            "INSERT INTO people (id, name, created_at, centroid) VALUES (?, ?, 0, ?)",
            (pid, name, blob),
        )
        await db.commit()


async def test_export_returns_only_named_people_with_centroids(tmp_path: Path) -> None:
    await _init(str(tmp_path))
    await _add_person(1, "Alice", _unit(1))
    await _add_person(2, "", _unit(2))         # unnamed → excluded
    await _add_person(3, "Bob", None)          # no centroid → excluded
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/export")

    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    names = {p["name"] for p in body["people"]}
    assert names == {"Alice"}
    # centroid round-trips as base64 of the float32 blob.
    raw = base64.b64decode(body["people"][0]["centroid_b64"])
    assert np.frombuffer(raw, dtype=np.float32).shape == (512,)


async def test_import_names_matching_unnamed_cluster(tmp_path: Path) -> None:
    """An imported name lands on the unnamed cluster with a near-identical centroid."""
    await _init(str(tmp_path))
    alice = _unit(1)
    await _add_person(1, "", alice)            # same person, unnamed, in this library
    await _add_person(2, "", _unit(99))        # unrelated cluster
    from main import app

    bundle = {
        "people": [{"name": "Alice", "centroid_b64": base64.b64encode(alice.tobytes()).decode()}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/import", json=bundle)
        assert r.status_code == 200
        assert r.json()["applied"] == 1

        from db.database import get_db

        async with get_db() as db:
            row = await (await db.execute("SELECT name FROM people WHERE id = 1")).fetchone()
            other = await (await db.execute("SELECT name FROM people WHERE id = 2")).fetchone()
    assert row is not None and other is not None
    assert row["name"] == "Alice"
    assert other["name"] == ""        # unrelated cluster untouched


async def test_import_reports_unmatched_when_no_similar_cluster(tmp_path: Path) -> None:
    await _init(str(tmp_path))
    await _add_person(1, "", _unit(1))
    from main import app

    bundle = {
        "people": [{"name": "Stranger", "centroid_b64": base64.b64encode(_unit(500).tobytes()).decode()}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/import", json=bundle)

    body = r.json()
    assert body["applied"] == 0
    assert body["unmatched"] == ["Stranger"]


async def test_import_does_not_overwrite_an_existing_name(tmp_path: Path) -> None:
    """If the best match is already named differently, it's a conflict, not an overwrite."""
    await _init(str(tmp_path))
    alice = _unit(1)
    await _add_person(1, "Alicia", alice)      # already named by the user
    from main import app

    bundle = {
        "people": [{"name": "Alice", "centroid_b64": base64.b64encode(alice.tobytes()).decode()}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/import", json=bundle)
        assert r.json()["applied"] == 0
        assert r.json()["conflicts"] == ["Alice"]

        from db.database import get_db

        async with get_db() as db:
            row = await (await db.execute("SELECT name FROM people WHERE id = 1")).fetchone()
    assert row is not None
    assert row["name"] == "Alicia"     # user's name preserved


async def test_export_import_round_trip(tmp_path: Path) -> None:
    """Export from a library, then import the bundle into a fresh library."""
    # Library A: Alice named.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    await _init(str(tmp_path / "a"))
    alice = _unit(7)
    await _add_person(1, "Alice", alice)
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        bundle = (await ac.get("/export")).json()

    # Library B: same person present but unnamed.
    await _init(str(tmp_path / "b"))
    await _add_person(1, "", alice)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/import", json=bundle)
        assert r.json()["applied"] == 1
        from db.database import get_db

        async with get_db() as db:
            row = await (await db.execute("SELECT name FROM people WHERE id = 1")).fetchone()
    assert row is not None
    assert row["name"] == "Alice"
