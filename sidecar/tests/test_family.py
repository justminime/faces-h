"""Tests for the family list (#198): import, ranked candidates, list-only
naming, guided review, and member ids in the tags export."""

import os
from pathlib import Path
from typing import Any

import numpy as np
from httpx import ASGITransport, AsyncClient

from db.schema import ALL_TABLES, INDEXES

FAMILY = {
    "version": 1,
    "members": [
        {"id": 12, "name": "Daniel Heilweil", "heb_name": "דניאל", "birth_year": 2007},
        {"id": 13, "name": "Ayelet Heilweil", "heb_name": "איילת", "birth_year": 1975},
        {"id": 14, "name": "Ziv Heilweil", "heb_name": "זיו", "birth_year": 2010},
    ],
}


def _unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(512).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _near(v: np.ndarray, seed: int, noise: float) -> np.ndarray:
    w = v + noise * _unit(seed)
    return (w / np.linalg.norm(w)).astype(np.float32)


async def _init(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    from db.database import get_db

    async with get_db() as db:
        for stmt in ALL_TABLES:
            await db.execute(stmt)
        for stmt in INDEXES:
            await db.execute(stmt)
        await db.commit()


async def _exec(sql: str, params: tuple[Any, ...] = ()) -> None:
    from db.database import get_db

    async with get_db() as db:
        await db.execute(sql, params)
        await db.commit()


async def _one(sql: str, params: tuple[Any, ...] = ()) -> Any:
    from db.database import get_db

    async with get_db() as db:
        return await (await db.execute(sql, params)).fetchone()


async def _person(pid: int, name: str, centroid: np.ndarray | None, member: int | None = None) -> None:
    blob = centroid.tobytes() if centroid is not None else None
    await _exec(
        "INSERT INTO people (id, name, created_at, centroid, list_member_id) VALUES (?, ?, 0, ?, ?)",
        (pid, name, blob, member),
    )


async def _face(fid: int, emb: np.ndarray, status: str, person: int | None = None,
                suggested: int | None = None, conf: float | None = None) -> None:
    await _exec("INSERT OR IGNORE INTO photos (id, path, mtime) VALUES (?, ?, 0)", (fid, f"/p/{fid}.jpg"))
    await _exec(
        "INSERT INTO faces (id, photo_id, detection_conf, embedding, person_id, suggested_person_id,"
        " assign_conf, assign_status) VALUES (?, ?, 0.9, ?, ?, ?, ?, ?)",
        (fid, fid, emb.tobytes(), person, suggested, conf, status),
    )


def _client() -> AsyncClient:
    from main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_import_validates_version_and_unique_ids(tmp_path: Path) -> None:
    await _init(tmp_path)
    async with _client() as ac:
        assert (await ac.post("/family/import", json={**FAMILY, "version": 2})).status_code == 400
        dup = {"version": 1, "members": [{"id": 1, "name": "A"}, {"id": 1, "name": "B"}]}
        assert (await ac.post("/family/import", json=dup)).status_code == 400
        assert (await ac.post("/family/import", json={"version": 1, "members": []})).status_code == 400
        assert (await ac.get("/family")).json()["loaded"] is False


async def test_import_links_exact_names_and_reimport_keeps_people(tmp_path: Path) -> None:
    await _init(tmp_path)
    await _person(1, "Daniel Heilweil", _unit(1))   # English name → linked
    await _person(2, "איילת", _unit(2))             # Hebrew name → linked
    await _person(3, "Grandpa", _unit(3))           # not on the list → stays as-is
    async with _client() as ac:
        r = await ac.post("/family/import", json=FAMILY)
        assert r.status_code == 200
        assert r.json()["linked"] == 2
        assert (await _one("SELECT name, list_member_id FROM people WHERE id = 2"))["name"] == "Ayelet Heilweil"

        # Re-import: Daniel renamed, Ayelet dropped from the list.
        again = {"version": 1, "members": [{"id": 12, "name": "Dani Heilweil"}, {"id": 14, "name": "Ziv Heilweil"}]}
        body = (await ac.post("/family/import", json=again)).json()
    assert body["renamed"] == 1 and body["unlinked"] == 1
    rows = {r: await _one("SELECT name, list_member_id FROM people WHERE id = ?", (r,)) for r in (1, 2, 3)}
    assert (rows[1]["name"], rows[1]["list_member_id"]) == ("Dani Heilweil", 12)
    assert (rows[2]["name"], rows[2]["list_member_id"]) == ("Ayelet Heilweil", None)  # kept, unlinked
    assert rows[3]["name"] == "Grandpa"


async def test_candidates_ranked_by_similarity_then_name(tmp_path: Path) -> None:
    await _init(tmp_path)
    daniel, ayelet = _unit(1), _unit(2)
    await _person(1, "Daniel Heilweil", daniel, member=12)
    await _person(2, "Ayelet Heilweil", ayelet, member=13)
    await _face(100, _near(ayelet, 9, 0.3), "unreviewed")
    async with _client() as ac:
        await ac.post("/family/import", json=FAMILY)
        cands = (await ac.get("/family/candidates", params={"face_id": 100})).json()
        assert (await ac.get("/family/candidates")).status_code == 400

        # Naming a cluster: itself is 'current', unscored.
        own = (await ac.get("/family/candidates", params={"person_id": 1})).json()

    assert [c["id"] for c in cands] == [13, 12, 14]          # Ayelet (closest), Daniel, Ziv (no faces)
    assert cands[0]["similarity"] > cands[1]["similarity"]
    assert cands[2]["similarity"] is None and cands[2]["heb_name"] == "זיו"
    current = [c for c in own if c["current"]]
    assert [c["id"] for c in current] == [12] and current[0]["similarity"] is None


async def test_no_free_text_names_when_list_loaded(tmp_path: Path) -> None:
    await _init(tmp_path)
    await _person(1, "", _unit(1))
    await _person(2, "Daniel Heilweil", _unit(2), member=12)
    async with _client() as ac:
        await ac.post("/family/import", json=FAMILY)
        assert (await ac.post("/people/1/name", json={"name": "Somebody New"})).status_code == 409

        taken = await ac.post("/people/1/member", json={"member_id": 12})
        assert taken.status_code == 409
        assert taken.json()["detail"]["person_id"] == 2      # → client offers the merge

        ok = await ac.post("/people/1/member", json={"member_id": 14})
        assert ok.status_code == 200
    assert (await _one("SELECT name, list_member_id FROM people WHERE id = 1"))["list_member_id"] == 14


async def test_person_for_member_is_created_once(tmp_path: Path) -> None:
    await _init(tmp_path)
    async with _client() as ac:
        await ac.post("/family/import", json=FAMILY)
        a = (await ac.post("/family/14/person")).json()["person_id"]
        b = (await ac.post("/family/14/person")).json()["person_id"]
        assert (await ac.post("/family/999/person")).status_code == 404
    assert a == b
    assert (await _one("SELECT name FROM people WHERE id = ?", (a,)))["name"] == "Ziv Heilweil"


async def test_review_queue_order_and_progress(tmp_path: Path) -> None:
    await _init(tmp_path)
    big, small = _unit(1), _unit(2)
    await _person(1, "Daniel Heilweil", big, member=12)
    await _person(2, "Ayelet Heilweil", small, member=13)
    await _person(3, "", _unit(3))                            # unlisted cluster
    for i in range(3):
        await _face(10 + i, big, "assigned", person=1, conf=0.9)
    await _face(20, small, "assigned", person=2, conf=0.9)
    await _face(30, small, "uncertain", suggested=2, conf=0.40)
    await _face(31, big, "uncertain", suggested=1, conf=0.55)
    await _face(32, big, "uncertain", suggested=1, conf=0.45)
    await _face(33, _unit(3), "uncertain", suggested=3, conf=0.5)  # not listed → not in review
    async with _client() as ac:
        await ac.post("/family/import", json=FAMILY)
        queue = (await ac.get("/review/queue")).json()
        progress = (await ac.get("/review/progress")).json()

    # Biggest cluster (Daniel, 3 faces) first, least-sure first within it.
    assert [q["face_id"] for q in queue] == [32, 31, 30]
    by_member = {p["member_id"]: p for p in progress["people"]}
    assert (by_member[12]["assigned"], by_member[12]["uncertain"]) == (3, 2)
    assert (by_member[13]["assigned"], by_member[13]["uncertain"]) == (1, 1)
    assert progress["remaining"] == 3 and progress["done"] is False
    assert progress["members_without_faces"] == 1               # Ziv


async def test_tags_export_carries_member_id(tmp_path: Path) -> None:
    await _init(tmp_path)
    await _person(1, "Daniel Heilweil", _unit(1), member=12)
    await _person(2, "Grandpa", _unit(2))
    await _face(10, _unit(1), "assigned", person=1, conf=0.9)
    await _exec("INSERT INTO faces (id, photo_id, detection_conf, person_id, assign_status)"
                " VALUES (11, 10, 0.9, 2, 'assigned')")
    async with _client() as ac:
        await ac.post("/family/import", json=FAMILY)
        body = (await ac.get("/export/tags")).json()
    people = body["photos"][0]["people"]
    assert {"name": "Daniel Heilweil", "member_id": 12} in people
    assert "Grandpa" in people


async def test_merge_keeps_family_link(tmp_path: Path) -> None:
    await _init(tmp_path)
    await _person(1, "Daniel Heilweil", _unit(1), member=12)
    await _person(2, "", _unit(2))
    async with _client() as ac:
        await ac.post("/family/import", json=FAMILY)
        r = await ac.post("/people/merge", json={"source_id": 1, "target_id": 2, "confirmed": True})
        assert r.status_code == 200
    row = await _one("SELECT name, list_member_id FROM people WHERE id = 2")
    assert (row["name"], row["list_member_id"]) == ("Daniel Heilweil", 12)
