"""Models router: reports InsightFace model availability."""

import os

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["models"])

_MODEL_SUBDIR = os.path.join("models", "buffalo_l")


@router.get("/status")
async def models_status() -> dict[str, object]:
    """Return whether the InsightFace buffalo_l model is present on disk.

    The model is downloaded automatically by InsightFace on first use.
    This endpoint lets the frontend decide whether to show the download
    progress screen during onboarding.
    """
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    model_dir = os.path.join(data_dir, _MODEL_SUBDIR)
    try:
        ready = os.path.isdir(model_dir) and bool(os.listdir(model_dir))
    except OSError:
        ready = False
    return {"ready": ready, "downloading": False, "progress": 0.0}
