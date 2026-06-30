"""Models router: InsightFace model status and preload trigger."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["models"])
logger = logging.getLogger(__name__)

_MODELS_SUBDIR = "models"
_MODEL_SUBDIR = os.path.join(_MODELS_SUBDIR, "buffalo_l")

# buffalo_l is delivered as a single ~288 MB zip that InsightFace then extracts
# into buffalo_l/. Download progress is tracked against the bytes landing under
# models/ (the growing zip) so the bar advances during the slow network phase,
# instead of sitting at 0 % until extraction begins (the old behaviour measured
# only the still-empty buffalo_l/ folder).
_BUFFALO_L_DOWNLOAD_BYTES = 290 * 1024 * 1024

# The extracted pack is ~333 MB. Require most of it on disk before reporting the
# model "ready", so a partially-extracted buffalo_l/ can't trip a scan that then
# fails to load a half-written ONNX file.
_BUFFALO_L_READY_BYTES = 300 * 1024 * 1024

_preload_lock = threading.Lock()
_preload_running = False


def _models_root(data_dir: str) -> str:
    return os.path.join(data_dir, _MODELS_SUBDIR)


def _model_dir(data_dir: str) -> str:
    return os.path.join(data_dir, _MODEL_SUBDIR)


def _dir_size(directory: str) -> int:
    total = 0
    try:
        for dirpath, _, filenames in os.walk(directory):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _is_ready(data_dir: str) -> bool:
    """True only once the buffalo_l pack is fully extracted.

    Checks the extracted size rather than mere directory existence: InsightFace
    creates buffalo_l/ and writes the ONNX files one at a time, so a non-empty
    folder does not yet mean the model is loadable.
    """
    d = _model_dir(data_dir)
    try:
        return os.path.isdir(d) and _dir_size(d) >= _BUFFALO_L_READY_BYTES
    except OSError:
        return False


def _download_fraction(data_dir: str) -> float:
    """Approximate download progress (0–0.99) from bytes on disk.

    Sums everything under models/ — the streaming zip plus any extracted files —
    so progress climbs steadily during the download instead of jumping from 0 %
    straight to done when extraction finishes.
    """
    size = _dir_size(_models_root(data_dir))
    return min(size / _BUFFALO_L_DOWNLOAD_BYTES, 0.99)


@router.get("/status")
async def models_status() -> dict[str, Any]:
    """Report whether the buffalo_l model is present on disk."""
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    ready = _is_ready(data_dir)
    downloading = _preload_running and not ready
    progress = _download_fraction(data_dir) if downloading else (1.0 if ready else 0.0)
    return {"ready": ready, "downloading": downloading, "progress": progress}


@router.post("/preload")
async def preload_models() -> dict[str, str]:
    """Trigger buffalo_l download in a background thread and stream progress via WebSocket.

    Safe to call multiple times — subsequent calls return immediately if a
    download is already running or the model is already present.
    """
    global _preload_running

    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")

    if _is_ready(data_dir):
        logger.info("models/preload: model already present — skipping")
        return {"status": "ready"}

    with _preload_lock:
        if _preload_running:
            logger.info("models/preload: download already in progress")
            return {"status": "downloading"}
        _preload_running = True

    logger.info("models/preload: starting buffalo_l download into %s", _model_dir(data_dir))

    def _download() -> None:
        global _preload_running
        try:
            from ml.insightface_recognizer import InsightFaceRecognizer  # noqa: PLC0415
            InsightFaceRecognizer(data_dir)
            logger.info("models/preload: buffalo_l download complete")
        except Exception:
            logger.exception("models/preload: buffalo_l download failed")
        finally:
            _preload_running = False

    threading.Thread(target=_download, daemon=True, name="model-preload").start()

    # Monitor directory growth and emit WebSocket progress events until done.
    async def _monitor() -> None:
        from api.scan import broadcast_ws  # noqa: PLC0415 — lazy to avoid circular import
        last_pct = -1
        while _preload_running:
            progress = _download_fraction(data_dir)
            pct = int(progress * 100)
            if pct != last_pct and pct % 10 == 0:
                size = _dir_size(_models_root(data_dir))
                logger.info("models/preload: progress %d%% (%d MB)", pct, size // (1024 * 1024))
                last_pct = pct
            await broadcast_ws({"type": "model_download_progress", "progress": progress})
            await asyncio.sleep(1)
        # Final event: 1.0 so the frontend auto-advances
        logger.info("models/preload: broadcasting completion")
        await broadcast_ws({"type": "model_download_progress", "progress": 1.0})

    asyncio.create_task(_monitor())
    return {"status": "started"}
