"""InsightFace buffalo_l implementation of FaceRecognizer.

Model files are downloaded to {data_dir}/models/buffalo_l/ on first call to
__init__(). Downloads are handled by the insightface library itself; no
manual network code required.
"""

import logging
import os
from typing import Any

import numpy as np

from ml.base import FaceRecognizer, FaceResult

logger = logging.getLogger(__name__)


class InsightFaceRecognizer(FaceRecognizer):
    """ArcFace/R100 via ONNX Runtime (buffalo_l pack).

    Detection uses RetinaFace (part of buffalo_l); embeddings are 512-dim
    and L2-normalised. The constructor triggers model download on first use.
    """

    def __init__(self, data_dir: str, _app: Any = None) -> None:
        models_root = os.path.join(data_dir, "models")
        os.makedirs(models_root, exist_ok=True)

        if _app is not None:
            self._app = _app
        else:
            import insightface.app  # lazy — expensive import deferred to first use

            self._app = insightface.app.FaceAnalysis(
                name="buffalo_l",
                root=models_root,
                providers=["CPUExecutionProvider"],
            )
            self._app.prepare(ctx_id=0, det_size=(640, 640))

    def detect_and_embed(self, image_path: str) -> list[FaceResult]:
        try:
            from PIL import Image as _PIL

            try:
                pil_img = _PIL.open(image_path)
            except Exception:
                return []

            # InsightFace expects a uint8 BGR numpy array (OpenCV convention)
            arr = np.array(pil_img.convert("RGB"), dtype=np.uint8)
            img = arr[:, :, ::-1].copy()  # RGB → BGR

            faces = self._app.get(img)
            h, w = img.shape[:2]
            results: list[FaceResult] = []

            for face in faces:
                x1, y1, x2, y2 = map(float, face.bbox)
                bbox = (x1 / w, y1 / h, (x2 - x1) / w, (y2 - y1) / h)

                emb = face.embedding.astype(np.float32)
                norm = float(np.linalg.norm(emb))
                if norm > 0:
                    emb = emb / norm

                results.append(
                    FaceResult(
                        bbox=bbox,
                        embedding=emb,
                        detection_confidence=float(face.det_score),
                    )
                )

            return results

        except Exception as exc:
            logger.warning("detect_and_embed failed for %s: %s", image_path, exc)
            return []
