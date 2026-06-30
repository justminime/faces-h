"""Tests for the models router: download-progress and readiness logic.

These cover the fix where the onboarding progress bar sat at 0 % during the
whole download (it measured the still-empty extracted folder) and where a
partially-extracted model was wrongly reported ready, tripping a premature scan.
"""

import os
from pathlib import Path

import pytest

from api import models as m


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)


# ---------------------------------------------------------------------------
# _download_fraction
# ---------------------------------------------------------------------------


def test_download_fraction_empty_is_zero(tmp_path: Path) -> None:
    """No bytes downloaded yet → 0.0 (not NaN / not crash on missing dir)."""
    assert m._download_fraction(str(tmp_path)) == 0.0


def test_download_fraction_counts_the_zip_during_download(tmp_path: Path) -> None:
    """Progress tracks bytes under models/ — including the streaming zip — so the
    bar moves while buffalo_l/ is still empty (the old bug measured only that)."""
    half = m._BUFFALO_L_DOWNLOAD_BYTES // 2
    _write(tmp_path / "models" / "buffalo_l.zip", half)

    frac = m._download_fraction(str(tmp_path))
    assert 0.45 <= frac <= 0.55


def test_download_fraction_caps_below_one(tmp_path: Path) -> None:
    """Even with more bytes than the estimate, the fraction never reports done."""
    _write(tmp_path / "models" / "buffalo_l.zip", m._BUFFALO_L_DOWNLOAD_BYTES * 2)
    assert m._download_fraction(str(tmp_path)) == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# _is_ready
# ---------------------------------------------------------------------------


def test_is_ready_false_when_missing(tmp_path: Path) -> None:
    assert m._is_ready(str(tmp_path)) is False


def test_is_ready_false_when_partially_extracted(tmp_path: Path) -> None:
    """A non-empty but under-sized buffalo_l/ must NOT be reported ready, or a
    scan starts before the ONNX files are fully written."""
    _write(tmp_path / "models" / "buffalo_l" / "w600k_r50.onnx", 50 * 1024 * 1024)
    assert m._is_ready(str(tmp_path)) is False


def test_is_ready_true_when_fully_extracted(tmp_path: Path) -> None:
    _write(
        tmp_path / "models" / "buffalo_l" / "w600k_r50.onnx",
        m._BUFFALO_L_READY_BYTES + 1024,
    )
    assert m._is_ready(str(tmp_path)) is True


# ---------------------------------------------------------------------------
# /models/status endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_models_status_not_ready_no_download(tmp_path: Path) -> None:
    """Nothing on disk, no preload running → not ready, not downloading, 0 %."""
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    m._preload_running = False
    status = await m.models_status()
    assert status == {"ready": False, "downloading": False, "progress": 0.0}


@pytest.mark.asyncio
async def test_models_status_reports_fraction_while_downloading(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    _write(tmp_path / "models" / "buffalo_l.zip", m._BUFFALO_L_DOWNLOAD_BYTES // 2)
    m._preload_running = True
    try:
        status = await m.models_status()
    finally:
        m._preload_running = False
    assert status["downloading"] is True
    assert status["ready"] is False
    assert 0.4 <= status["progress"] <= 0.6


@pytest.mark.asyncio
async def test_models_status_ready_reports_progress_one(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    _write(
        tmp_path / "models" / "buffalo_l" / "w600k_r50.onnx",
        m._BUFFALO_L_READY_BYTES + 1024,
    )
    m._preload_running = False
    status = await m.models_status()
    assert status["ready"] is True
    assert status["downloading"] is False
    assert status["progress"] == 1.0
