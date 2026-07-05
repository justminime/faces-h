"""Runtime configuration loaded from {data_dir}/config.json (#107).

Single source of truth for the assignment thresholds (OD-02: "tune after
first real-world scan" — now possible without editing code) and the active
face model (D-05 swappable layer, selected via ml.factory).

Missing file → defaults. Corrupt file or invalid values → defaults with a
logged warning; a bad config must never take the engine down. The unknown-
model case is deliberately NOT validated here — ml.factory raises loudly so
a typo'd model name fails at startup instead of silently using the default.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = "config.json"

DEFAULT_FACE_MODEL = "insightface_buffalo_l"
DEFAULT_AUTO_ASSIGN_THRESHOLD = 0.68
DEFAULT_UNCERTAIN_THRESHOLD = 0.50
# OD-04: detections smaller than this (shorter bbox side, source pixels) or
# below the detector-confidence floor are skipped and counted (#111).
DEFAULT_MIN_FACE_PX = 20
DEFAULT_MIN_DETECTION_CONFIDENCE = 0.5


@dataclass(frozen=True)
class Config:
    face_model: str = DEFAULT_FACE_MODEL
    auto_assign_threshold: float = DEFAULT_AUTO_ASSIGN_THRESHOLD
    uncertain_threshold: float = DEFAULT_UNCERTAIN_THRESHOLD
    min_face_px: float = DEFAULT_MIN_FACE_PX
    min_detection_confidence: float = DEFAULT_MIN_DETECTION_CONFIDENCE


_cached: Config | None = None


def _validate(raw: dict[str, object]) -> Config:
    face_model = raw.get("face_model", DEFAULT_FACE_MODEL)
    auto = raw.get("auto_assign_threshold", DEFAULT_AUTO_ASSIGN_THRESHOLD)
    uncertain = raw.get("uncertain_threshold", DEFAULT_UNCERTAIN_THRESHOLD)

    if not isinstance(face_model, str) or not face_model.strip():
        logger.warning("config.json: invalid face_model %r — using default", face_model)
        face_model = DEFAULT_FACE_MODEL

    auto_f = float(auto) if isinstance(auto, (int, float)) else None
    uncertain_f = float(uncertain) if isinstance(uncertain, (int, float)) else None
    if auto_f is None or uncertain_f is None or not (0.0 < uncertain_f < auto_f <= 1.0):
        logger.warning(
            "config.json: invalid thresholds (auto=%r, uncertain=%r) — "
            "require 0 < uncertain < auto_assign <= 1; using defaults",
            auto,
            uncertain,
        )
        auto_f = DEFAULT_AUTO_ASSIGN_THRESHOLD
        uncertain_f = DEFAULT_UNCERTAIN_THRESHOLD

    min_px = raw.get("min_face_px", DEFAULT_MIN_FACE_PX)
    min_px_f = float(min_px) if isinstance(min_px, (int, float)) and float(min_px) >= 0 else None
    if min_px_f is None:
        logger.warning("config.json: invalid min_face_px %r — using default", min_px)
        min_px_f = float(DEFAULT_MIN_FACE_PX)

    min_det = raw.get("min_detection_confidence", DEFAULT_MIN_DETECTION_CONFIDENCE)
    min_det_f = (
        float(min_det)
        if isinstance(min_det, (int, float)) and 0.0 <= float(min_det) <= 1.0
        else None
    )
    if min_det_f is None:
        logger.warning(
            "config.json: invalid min_detection_confidence %r — using default", min_det
        )
        min_det_f = DEFAULT_MIN_DETECTION_CONFIDENCE

    return Config(
        face_model=face_model,
        auto_assign_threshold=auto_f,
        uncertain_threshold=uncertain_f,
        min_face_px=min_px_f,
        min_detection_confidence=min_det_f,
    )


def get_config() -> Config:
    """Return the effective config, loading {data_dir}/config.json once.

    Cached for the process lifetime — call reset_config_cache() in tests.
    """
    global _cached
    if _cached is not None:
        return _cached

    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    path = os.path.join(data_dir, _CONFIG_FILENAME)
    raw: dict[str, object] = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
            else:
                logger.warning("config.json: top level must be an object — using defaults")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("config.json unreadable (%s) — using defaults", exc)

    _cached = _validate(raw)
    logger.info(
        "effective config — face_model=%s auto_assign=%.2f uncertain=%.2f (source: %s)",
        _cached.face_model,
        _cached.auto_assign_threshold,
        _cached.uncertain_threshold,
        path if raw else "defaults",
    )
    return _cached


def reset_config_cache() -> None:
    """Drop the cached config so the next get_config() re-reads the file."""
    global _cached
    _cached = None
