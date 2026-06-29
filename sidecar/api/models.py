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

_MODEL_SUBDIR = os.path.join("models", "buffalo_l")

# buffalo_l pack is ~250 MB total; used to estimate download progress
# from directory size without needing InsightFace download callbacks.
_BUFFALO_L_BYTES = 250 * 1024 * 1024

_preload_lock = threading.Lock()
_preload_running = False


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
    d = _model_dir(data_dir)
    try:
        return os.path.isdir(d) and bool(os.listdir(d))
    except OSError:
        return False


@router.get("/status")
async def models_status() -> dict[str, Any]:
    """Report whether the buffalo_l model is present on disk."""
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    ready = _is_ready(data_dir)
    downloading = _preload_running and not ready
    progress = _dir_size(_model_dir(data_dir)) / _BUFFALO_L_BYTES if downloading else (1.0 if ready else 0.0)
    return {"ready": ready, "downloading": downloading, "progress": min(progress, 1.0)}


@router.post("/preload")
async def preload_models() -> dict[str, str]:
    """Trigger buffalo_l download in a background thread and stream progress via WebSocket.

    Safe to call multiple times — subsequent calls return immediately if a
    download is already running or the model is already present.
    """
    global _preload_running

    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")

    if _is_ready(data_dir):
        return {"status": "ready"}

    with _preload_lock:
        if _preload_running:
            return {"status": "downloading"}
        _preload_running = True

    def _download() -> None:
        global _preload_running
        try:
            from ml.insightface_recognizer import InsightFaceRecognizer  # noqa: PLC0415
            InsightFaceRecognizer(data_dir)
            logger.info("buffalo_l model download complete")
        except Exception:
            logger.exception("buffalo_l model preload failed")
        finally:
            _preload_running = False

    threading.Thread(target=_download, daemon=True, name="model-preload").start()

    # Monitor directory growth and emit WebSocket progress events until done.
    async def _monitor() -> None:
        from api.scan import broadcast_ws  # noqa: PLC0415 — lazy to avoid circular import
        mdir = _model_dir(data_dir)
        while _preload_running:
            size = _dir_size(mdir)
            progress = min(size / _BUFFALO_L_BYTES, 0.99)
            await broadcast_ws({"type": "model_download_progress", "progress": progress})
            await asyncio.sleep(1)
        # Final event: 1.0 so the frontend auto-advances
        await broadcast_ws({"type": "model_download_progress", "progress": 1.0})

    asyncio.create_task(_monitor())
    return {"status": "started"}
