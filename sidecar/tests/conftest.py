"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest

from config import reset_config_cache
from services.face_index import reset_face_index


@pytest.fixture(autouse=True)
def _fresh_config() -> Iterator[None]:
    """Drop cached per-data-dir state around every test.

    Tests point FACES_H_DATA_DIR at their own tmp dirs; a config or FAISS
    face index cached from a previous test's dir must never leak into the
    next one.
    """
    reset_config_cache()
    reset_face_index()
    yield
    reset_config_cache()
    reset_face_index()
