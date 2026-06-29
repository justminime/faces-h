"""Abstract ML interface shared by all face-recognition backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class FaceResult:
    bbox: tuple[float, float, float, float]  # x, y, w, h — normalised 0-1
    embedding: np.ndarray                    # shape (512,), L2-normalised
    detection_confidence: float


class FaceRecognizer(ABC):
    @abstractmethod
    def detect_and_embed(self, image_path: str) -> list[FaceResult]:
        """Detect all faces in image_path and return embeddings.

        Never raises; returns [] on corrupt input, unreadable file, or no
        faces detected. Callers must not assume any minimum list length.
        """
