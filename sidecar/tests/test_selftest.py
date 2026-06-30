"""Tests for the `--selftest` diagnostic entry point in main.py.

--selftest runs face detection on one image and logs the outcome, so a frozen
build's ML stack can be verified from the command line without a full scan.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from main import _run_selftest
from ml.base import FaceResult


def _face() -> FaceResult:
    emb = np.ones(512, dtype=np.float32)
    return FaceResult(bbox=(0.1, 0.1, 0.2, 0.2), embedding=emb / np.linalg.norm(emb),
                      detection_confidence=0.9)


def test_selftest_logs_detected_face_count(tmp_path: Path) -> None:
    fake_recognizer = MagicMock()
    fake_recognizer.detect_and_embed.return_value = [_face(), _face()]
    logger = MagicMock()

    with patch("ml.insightface_recognizer.InsightFaceRecognizer", return_value=fake_recognizer):
        _run_selftest("photo.jpg", str(tmp_path), logger)

    fake_recognizer.detect_and_embed.assert_called_once_with("photo.jpg")
    # One info call reports the count (2) for the image.
    assert any(
        "detected" in str(c.args[0]) and 2 in c.args
        for c in logger.info.call_args_list
    ), logger.info.call_args_list


def test_selftest_logs_traceback_when_recognizer_fails(tmp_path: Path) -> None:
    """If the recognizer can't initialise, --selftest logs the exception rather
    than crashing — the traceback is the diagnostic payload."""
    logger = MagicMock()

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("model not bundled")

    with patch("ml.insightface_recognizer.InsightFaceRecognizer", side_effect=_boom):
        _run_selftest("photo.jpg", str(tmp_path), logger)

    logger.exception.assert_called_once()
