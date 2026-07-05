"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest

from config import reset_config_cache


@pytest.fixture(autouse=True)
def _fresh_config() -> Iterator[None]:
    """Drop the cached config around every test.

    Tests point FACES_H_DATA_DIR at their own tmp dirs; a config cached from a
    previous test's dir must never leak into the next one.
    """
    reset_config_cache()
    yield
    reset_config_cache()
