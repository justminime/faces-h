"""Tests for the ML engine interface and InsightFace recognizer.

All tests mock insightface.app.FaceAnalysis so they run in CI without
downloading the 300 MB buffalo_l model files. The _app injection param
on InsightFaceRecognizer enables clean dependency injection without
monkey-patching insightface internals.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from ml.base import FaceRecognizer, FaceResult
from ml.factory import get_recognizer
from ml.insightface_recognizer import InsightFaceRecognizer

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_vec(dim: int = 512, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _make_mock_app(faces: list[Any]) -> MagicMock:
    """Return a mock FaceAnalysis app whose get() returns *faces*."""
    app = MagicMock()
    app.get.return_value = faces
    return app


def _fake_face(
    bbox: tuple[float, float, float, float] = (10.0, 10.0, 90.0, 90.0),
    score: float = 0.97,
    seed: int = 42,
) -> MagicMock:
    f = MagicMock()
    f.bbox = np.array(bbox, dtype=np.float32)
    f.det_score = score
    f.embedding = _unit_vec(seed=seed)
    return f


def _make_recognizer(tmp_path: Path, faces: list[Any]) -> InsightFaceRecognizer:
    return InsightFaceRecognizer(str(tmp_path), _app=_make_mock_app(faces))


# ---------------------------------------------------------------------------
# Base / ABC tests
# ---------------------------------------------------------------------------


def test_face_result_is_dataclass() -> None:
    emb = _unit_vec()
    result = FaceResult(bbox=(0.1, 0.1, 0.5, 0.5), embedding=emb, detection_confidence=0.9)
    assert result.embedding.shape == (512,)
    assert result.detection_confidence == pytest.approx(0.9)


def test_face_recognizer_is_abstract() -> None:
    with pytest.raises(TypeError):
        FaceRecognizer()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# InsightFaceRecognizer — interface contract (mocked)
# ---------------------------------------------------------------------------


def test_blank_image_returns_empty(tmp_path: Path) -> None:
    """A 100×100 white image with no faces detected → empty list, no exception."""
    recognizer = _make_recognizer(tmp_path, faces=[])

    img_path = tmp_path / "blank.jpg"
    Image.new("RGB", (100, 100), color=(255, 255, 255)).save(str(img_path))

    results = recognizer.detect_and_embed(str(img_path))
    assert results == []


def test_real_face_fixture_returns_results(tmp_path: Path) -> None:
    """Face fixture image with one mocked detection → correct FaceResult."""
    recognizer = _make_recognizer(tmp_path, faces=[_fake_face()])

    results = recognizer.detect_and_embed(str(FIXTURES_DIR / "face.jpg"))

    assert len(results) == 1
    r = results[0]
    assert r.embedding.shape == (512,)
    assert float(np.linalg.norm(r.embedding)) == pytest.approx(1.0, abs=1e-4)
    assert 0.0 <= r.detection_confidence <= 1.0
    x, y, w, h = r.bbox
    assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_corrupt_file_path_returns_empty(tmp_path: Path) -> None:
    """Non-existent / corrupt path → [] without exception."""
    recognizer = _make_recognizer(tmp_path, faces=[_fake_face()])
    results = recognizer.detect_and_embed(str(tmp_path / "does_not_exist.jpg"))
    assert results == []


def test_embedding_is_l2_normalised(tmp_path: Path) -> None:
    """Returned embeddings have unit L2 norm regardless of model output scale."""
    raw_emb = np.ones(512, dtype=np.float32)  # intentionally not unit
    face = _fake_face()
    face.embedding = raw_emb

    recognizer = _make_recognizer(tmp_path, faces=[face])

    img_path = tmp_path / "img.jpg"
    Image.new("RGB", (100, 100)).save(str(img_path))

    results = recognizer.detect_and_embed(str(img_path))
    assert len(results) == 1
    assert float(np.linalg.norm(results[0].embedding)) == pytest.approx(1.0, abs=1e-4)


def test_bbox_normalised_to_0_1(tmp_path: Path) -> None:
    """Bounding box values are all in [0, 1] regardless of image dimensions."""
    # Absolute pixel bbox in a 200x100 image
    face = _fake_face(bbox=(20.0, 10.0, 180.0, 90.0))
    recognizer = _make_recognizer(tmp_path, faces=[face])

    img_path = tmp_path / "wide.jpg"
    Image.new("RGB", (200, 100)).save(str(img_path))

    results = recognizer.detect_and_embed(str(img_path))
    assert len(results) == 1
    x, y, w, h = results[0].bbox
    for val in (x, y, w, h):
        assert 0.0 <= val <= 1.0, f"bbox value {val} out of [0, 1]"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_insightface_recognizer(tmp_path: Path) -> None:
    """factory.get_recognizer with 'insightface_buffalo_l' returns InsightFaceRecognizer."""
    from unittest.mock import patch

    mock_app = _make_mock_app(faces=[])

    def _no_download_init(self: InsightFaceRecognizer, data_dir: str, _app: Any = None) -> None:
        self._app = mock_app

    with patch.object(InsightFaceRecognizer, "__init__", _no_download_init):
        recognizer = get_recognizer({"face_model": "insightface_buffalo_l"}, str(tmp_path))

    assert isinstance(recognizer, InsightFaceRecognizer)
    assert isinstance(recognizer, FaceRecognizer)


def test_factory_raises_for_unknown_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown face model"):
        get_recognizer({"face_model": "mystery_model_v99"}, str(tmp_path))
