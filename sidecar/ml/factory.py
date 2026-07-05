"""Factory for creating the configured FaceRecognizer implementation."""

from config import Config
from ml.base import FaceRecognizer

_KNOWN_MODELS = {"insightface_buffalo_l"}


def get_recognizer(config: Config, data_dir: str) -> FaceRecognizer:
    """Return the FaceRecognizer selected by config.face_model (#107).

    Raises ValueError for unknown model names so mis-configuration fails
    loudly rather than silently falling back to a wrong model.
    """
    model = config.face_model

    if model == "insightface_buffalo_l":
        from ml.insightface_recognizer import InsightFaceRecognizer

        return InsightFaceRecognizer(data_dir)

    raise ValueError(
        f"Unknown face model {model!r}. Known models: {sorted(_KNOWN_MODELS)}"
    )
