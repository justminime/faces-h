"""Factory for creating the configured FaceRecognizer implementation."""

from ml.base import FaceRecognizer

_KNOWN_MODELS = {"insightface_buffalo_l"}


def get_recognizer(config: dict[str, str], data_dir: str) -> FaceRecognizer:
    """Return the FaceRecognizer specified by config['face_model'].

    Raises ValueError for unknown model names so mis-configuration fails
    loudly rather than silently falling back to a wrong model.
    """
    model = config.get("face_model", "insightface_buffalo_l")

    if model == "insightface_buffalo_l":
        from ml.insightface_recognizer import InsightFaceRecognizer

        return InsightFaceRecognizer(data_dir)

    raise ValueError(
        f"Unknown face model {model!r}. Known models: {sorted(_KNOWN_MODELS)}"
    )
