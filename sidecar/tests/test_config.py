"""Tests for config.json loading and propagation (#107)."""

import json
import os
from pathlib import Path

from config import (
    DEFAULT_AUTO_ASSIGN_THRESHOLD,
    DEFAULT_FACE_MODEL,
    DEFAULT_UNCERTAIN_THRESHOLD,
    get_config,
    reset_config_cache,
)
from services.clustering import ClusteringService


def _set_data_dir(tmp_path: Path) -> None:
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    reset_config_cache()


def _write_config(tmp_path: Path, payload: object) -> None:
    (tmp_path / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def test_defaults_when_file_missing(tmp_path: Path) -> None:
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.face_model == DEFAULT_FACE_MODEL
    assert cfg.auto_assign_threshold == DEFAULT_AUTO_ASSIGN_THRESHOLD
    assert cfg.uncertain_threshold == DEFAULT_UNCERTAIN_THRESHOLD


def test_file_overrides_defaults(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"face_model": "insightface_buffalo_l", "auto_assign_threshold": 0.9, "uncertain_threshold": 0.3},
    )
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.auto_assign_threshold == 0.9
    assert cfg.uncertain_threshold == 0.3


def test_partial_file_keeps_other_defaults(tmp_path: Path) -> None:
    _write_config(tmp_path, {"auto_assign_threshold": 0.75})
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.auto_assign_threshold == 0.75
    assert cfg.uncertain_threshold == DEFAULT_UNCERTAIN_THRESHOLD
    assert cfg.face_model == DEFAULT_FACE_MODEL


def test_corrupt_json_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{not valid json", encoding="utf-8")
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.auto_assign_threshold == DEFAULT_AUTO_ASSIGN_THRESHOLD


def test_invalid_threshold_ordering_falls_back(tmp_path: Path) -> None:
    """uncertain >= auto_assign is rejected as a pair (0 < uncertain < auto <= 1)."""
    _write_config(tmp_path, {"auto_assign_threshold": 0.4, "uncertain_threshold": 0.6})
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.auto_assign_threshold == DEFAULT_AUTO_ASSIGN_THRESHOLD
    assert cfg.uncertain_threshold == DEFAULT_UNCERTAIN_THRESHOLD


def test_config_is_cached_until_reset(tmp_path: Path) -> None:
    _set_data_dir(tmp_path)
    first = get_config()
    _write_config(tmp_path, {"auto_assign_threshold": 0.99, "uncertain_threshold": 0.1})
    assert get_config() is first, "config must be cached for the process lifetime"
    reset_config_cache()
    assert get_config().auto_assign_threshold == 0.99


def test_clustering_service_reads_config_thresholds(tmp_path: Path) -> None:
    """ClusteringService without explicit thresholds resolves them from config
    lazily — Rules 1/3 are then gated by the user's configured values."""
    _write_config(tmp_path, {"auto_assign_threshold": 0.9, "uncertain_threshold": 0.2})
    _set_data_dir(tmp_path)
    svc = ClusteringService()
    assert svc.auto_assign_threshold == 0.9
    assert svc.uncertain_threshold == 0.2
    # Explicit constructor args still win (used by tests and callers).
    svc2 = ClusteringService(auto_assign_threshold=0.5, uncertain_threshold=0.4)
    assert svc2.auto_assign_threshold == 0.5
    assert svc2.uncertain_threshold == 0.4


def test_detection_filter_defaults_and_overrides(tmp_path: Path) -> None:
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.min_face_px == 20
    assert cfg.min_detection_confidence == 0.5

    _write_config(tmp_path, {"min_face_px": 32, "min_detection_confidence": 0.7})
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.min_face_px == 32
    assert cfg.min_detection_confidence == 0.7


def test_detection_filter_invalid_values_fall_back(tmp_path: Path) -> None:
    _write_config(tmp_path, {"min_face_px": -3, "min_detection_confidence": 4})
    _set_data_dir(tmp_path)
    cfg = get_config()
    assert cfg.min_face_px == 20
    assert cfg.min_detection_confidence == 0.5
