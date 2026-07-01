"""Tests for POST /search: multi-person AND logic with date filter."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from db.schema import ALL_TABLES, INDEXES


async def _setup(tmp_path: str) -> None:
    os.environ["FACES_H_DATA_DIR"] = tmp_path
    from db.database import get_db

    async with get_db() as db:
        for stmt in ALL_TABLES:
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)

        # People
        await db.execute("INSERT INTO people (id, name, created_at) VALUES (1, 'Alice', 0)")
        await db.execute("INSERT INTO people (id, name, created_at) VALUES (2, 'Bob', 0)")

        # Photos: p1 (2012), p2 (2018), p3 (no date)
        await db.execute(
            "INSERT INTO photos (id, path, mtime) VALUES (1, '/p1.jpg', 0)"
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, taken_at) VALUES (2, '/p2.jpg', 0, 1514764800)"  # 2018-01-01
        )
        await db.execute(
            "INSERT INTO photos (id, path, mtime, taken_at) VALUES (3, '/p3.jpg', 0, 1356998400)"  # 2013-01-01
        )

        # Faces
        # Photo 1: Alice only (assigned)
        await db.execute(
            "INSERT INTO faces (id, photo_id, detection_conf, assign_status, person_id, assign_conf)"
            " VALUES (1, 1, 0.99, 'assigned', 1, 0.80)"
        )
        # Photo 2: Alice + Bob (both assigned)
        await db.execute(
            "INSERT INTO faces (id, photo_id, detection_conf, assign_status, person_id, assign_conf)"
            " VALUES (2, 2, 0.99, 'assigned', 1, 0.80)"
        )
        await db.execute(
            "INSERT INTO faces (id, photo_id, detection_conf, assign_status, person_id, assign_conf)"
            " VALUES (3, 2, 0.99, 'assigned', 2, 0.75)"
        )
        # Photo 3: Alice (assigned) + Bob (uncertain — must NOT count)
        await db.execute(
            "INSERT INTO faces (id, photo_id, detection_conf, assign_status, person_id, assign_conf)"
            " VALUES (4, 3, 0.99, 'assigned', 1, 0.80)"
        )
        await db.execute(
            "INSERT INTO faces (id, photo_id, detection_conf, assign_status, assign_conf, suggested_person_id)"
            " VALUES (5, 3, 0.99, 'uncertain', 0.60, 2)"
        )

        await db.commit()


async def test_single_person_returns_all_assigned_photos(tmp_path: pytest.TempPathFactory) -> None:
    """Single-person search returns all photos where that person has assign_status='assigned'."""
    await _setup(str(tmp_path))
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/search", json={"people_ids": [1]})
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    # Alice appears assigned in photos 1, 2, 3
    assert ids == {1, 2, 3}


async def test_two_person_and_returns_only_shared_photos(tmp_path: pytest.TempPathFactory) -> None:
    """Two-person AND search returns only photos where BOTH people are assigned."""
    await _setup(str(tmp_path))
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/search", json={"people_ids": [1, 2]})
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    # Only photo 2 has both Alice AND Bob assigned
    assert ids == {2}


async def test_date_filter_narrows_results(tmp_path: pytest.TempPathFactory) -> None:
    """date_from / date_to filter restricts results to the given window."""
    await _setup(str(tmp_path))
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/search",
            json={"people_ids": [1], "date_from": "2013-01-01", "date_to": "2019-12-31"},
        )
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    # Photos 2 (2018) and 3 (2013) fall in range; photo 1 has no taken_at → excluded
    assert ids == {2, 3}


async def test_uncertain_faces_not_returned(tmp_path: pytest.TempPathFactory) -> None:
    """Photos where a person only appears as uncertain are excluded from AND results."""
    await _setup(str(tmp_path))
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/search", json={"people_ids": [1, 2]})
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    # Photo 3 has Bob only as 'uncertain' → not in AND results
    assert 3 not in ids


async def _add_extra_person_photo(tmp_path: str) -> None:
    """Photo 4: Alice + Bob + Carol, all assigned (a superset of {Alice, Bob})."""
    from db.database import get_db

    async with get_db() as db:
        await db.execute("INSERT INTO people (id, name, created_at) VALUES (3, 'Carol', 0)")
        await db.execute("INSERT INTO photos (id, path, mtime) VALUES (4, '/p4.jpg', 0)")
        for fid, pid in ((6, 1), (7, 2), (8, 3)):
            await db.execute(
                "INSERT INTO faces (id, photo_id, detection_conf, assign_status, person_id, assign_conf)"
                f" VALUES ({fid}, 4, 0.99, 'assigned', {pid}, 0.80)"
            )
        await db.commit()


async def test_exact_excludes_photos_with_an_extra_person(tmp_path: pytest.TempPathFactory) -> None:
    """match='exact' returns only photos whose assigned-people set == the selection."""
    await _setup(str(tmp_path))
    await _add_extra_person_photo(str(tmp_path))
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        contains = await ac.post("/search", json={"people_ids": [1, 2], "match": "contains"})
        exact = await ac.post("/search", json={"people_ids": [1, 2], "match": "exact"})

    # Contains: both photo 2 (Alice+Bob) and photo 4 (Alice+Bob+Carol) match.
    assert {p["id"] for p in contains.json()} == {2, 4}
    # Exact: only photo 2 — photo 4 has the extra person Carol.
    assert {p["id"] for p in exact.json()} == {2}


async def test_exact_ignores_uncertain_faces(tmp_path: pytest.TempPathFactory) -> None:
    """An uncertain face of another person does not disqualify an exact match."""
    await _setup(str(tmp_path))
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/search", json={"people_ids": [1], "match": "exact"})
    ids = {p["id"] for p in r.json()}
    # Photo 1 (Alice only) and photo 3 (Alice assigned, Bob only uncertain) are
    # both "exactly Alice"; photo 2 (Alice + Bob assigned) is excluded.
    assert ids == {1, 3}
