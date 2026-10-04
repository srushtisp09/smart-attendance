"""Face detection + embedding using InsightFace (ONNX, CPU). Only embeddings are kept, never photos."""
from functools import lru_cache
from threading import Lock

import cv2
import numpy as np

from .config import settings


class FaceError(Exception):
    """Something wrong with the submitted photo. The message is safe to show to the user."""


@lru_cache(maxsize=1)
def _model():
    from insightface.app import FaceAnalysis  # imported lazily: it is slow to import
    app = FaceAnalysis(name=settings.FACE_MODEL, root=settings.FACE_MODEL_DIR,
                       providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


_lock = Lock()  # one inference at a time; keeps memory use predictable


def embedding_from_image(data: bytes) -> np.ndarray:
    """Photo bytes -> normalised 512-d embedding. Raises FaceError with a user-friendly message."""
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise FaceError("Photo is too large (max 5 MB).")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FaceError("Could not read the photo. Upload a JPEG or PNG.")
    h, w = img.shape[:2]
    if max(h, w) > 1280:  # big phone photos: shrink for speed, faces stay detectable
        scale = 1280 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

    with _lock:
        faces = _model().get(img)
    faces = [f for f in faces if float(f.det_score) >= settings.FACE_MIN_DET_SCORE]
    if not faces:
        raise FaceError("No face found. Face the camera in good light.")
    if len(faces) > 1:
        raise FaceError("More than one face in the photo. Only you should be in the frame.")
    face = faces[0]
    if (face.bbox[2] - face.bbox[0]) < settings.FACE_MIN_SIZE_PX:
        raise FaceError("Your face is too small in the photo. Move closer.")
    return face.normed_embedding.astype(np.float32)


def to_bytes(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def from_bytes(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))