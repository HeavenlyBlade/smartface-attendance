"""
services/face_service.py -- SmartFace facial encoding cache and recognition pipeline

Backend: face_recognition + dlib-bin (pre-compiled, no build required).
Uses Euclidean distance with TOLERANCE=0.45.
Memory footprint: ~150 MB (vs ~400 MB for DeepFace/TensorFlow).
"""

import base64
import logging
import threading
from typing import Optional

import cv2
import numpy as np

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None
    FACE_RECOGNITION_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "face_recognition not available -- recognition will return all faces as Unknown"
    )

import config

logger = logging.getLogger(__name__)

known_encodings: list[np.ndarray] = []
known_user_ids:  list[int]        = []
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_encoding(enc: np.ndarray) -> bytes:
    return enc.tobytes()

def deserialize_encoding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def load_known_faces() -> None:
    global known_encodings, known_user_ids
    try:
        from models.db import execute_query
        rows = execute_query(
            "SELECT user_id, encoding FROM face_encodings WHERE encoding IS NOT NULL",
            fetchall=True
        )
    except Exception as exc:
        logger.error("load_known_faces: DB unreachable: %s", exc)
        return

    enc_tmp: list[np.ndarray] = []
    uid_tmp: list[int]        = []
    for row in (rows or []):
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape != (128,):
                raise ValueError(f"bad shape {enc.shape}")
            enc_tmp.append(enc)
            uid_tmp.append(int(row["user_id"]))
        except Exception as exc:
            logger.warning("load_known_faces: skipping row user_id=%s: %s", row.get("user_id"), exc)

    with _cache_lock:
        known_encodings[:] = enc_tmp
        known_user_ids[:]  = uid_tmp
    logger.info("load_known_faces: loaded %d encoding(s).", len(known_encodings))


def reload_known_faces() -> None:
    global known_encodings, known_user_ids
    try:
        from models.db import execute_query
        rows = execute_query(
            "SELECT user_id, encoding FROM face_encodings WHERE encoding IS NOT NULL",
            fetchall=True
        )
    except Exception as exc:
        logger.error("reload_known_faces: DB error: %s", exc)
        return

    enc_tmp: list[np.ndarray] = []
    uid_tmp: list[int]        = []
    for row in (rows or []):
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape != (128,):
                raise ValueError(f"bad shape {enc.shape}")
            enc_tmp.append(enc)
            uid_tmp.append(int(row["user_id"]))
        except Exception as exc:
            logger.warning("reload_known_faces: skipping row user_id=%s: %s", row.get("user_id"), exc)

    with _cache_lock:
        known_encodings[:] = enc_tmp
        known_user_ids[:]  = uid_tmp
    logger.info("reload_known_faces: %d encoding(s) loaded.", len(known_encodings))


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

def encode_samples(image_list: list[bytes]) -> list[np.ndarray]:
    if not FACE_RECOGNITION_AVAILABLE:
        raise RuntimeError("face_recognition is not installed")

    results: list[np.ndarray] = []
    for idx, img_bytes in enumerate(image_list, start=1):
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Sample {idx}: could not decode image")

        rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        encs = face_recognition.face_encodings(rgb)
        if len(encs) == 0:
            raise ValueError(f"Sample {idx}: no face detected in image")

        results.append(encs[0])  # np.ndarray shape (128,) float64
    return results


# ---------------------------------------------------------------------------
# Property test helpers
# ---------------------------------------------------------------------------

def compute_confidence(distance: float) -> float:
    return round((1 - distance) * 100, 2)


def classify_face_match(distance: float, user_id: Optional[int] = None,
                        full_name: Optional[str] = None) -> dict:
    if known_encodings and distance <= config.TOLERANCE:
        return {"user_id": user_id, "full_name": full_name or "Unknown",
                "confidence": compute_confidence(distance)}
    return {"user_id": None, "full_name": "Unknown", "confidence": None}


# ---------------------------------------------------------------------------
# Recognition pipeline
# ---------------------------------------------------------------------------

def _get_user_name(user_id: int) -> str:
    try:
        from models.db import execute_query
        row = execute_query("SELECT full_name FROM users WHERE id = %s",
                            params=(user_id,), fetchone=True)
        return row["full_name"] if row else f"User#{user_id}"
    except Exception as exc:
        logger.warning("_get_user_name: %s", exc)
        return f"User#{user_id}"


def recognize_frame(image_b64: str) -> list[dict]:
    if not FACE_RECOGNITION_AVAILABLE:
        logger.error("recognize_frame: face_recognition not available")
        return []

    # Step 1: Decode base64 JPEG to numpy array
    try:
        img_data = base64.b64decode(image_b64)
    except Exception as exc:
        raise ValueError(f"Invalid base64 payload: {exc}") from exc

    np_arr = np.frombuffer(img_data, np.uint8)
    frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Could not decode image")

    # Step 2: Downscale 0.25x -- ~4x speedup, non-negotiable for usable framerate
    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)

    # Step 3: BGR (OpenCV default) -> RGB (face_recognition expects RGB input)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

    # Step 4: Detect face bounding boxes in the downscaled frame
    locs = face_recognition.face_locations(rgb)

    # Step 5: Compute 128-dim facial encodings for each detected face
    encs = face_recognition.face_encodings(rgb, locs)

    if not locs:
        return []

    with _cache_lock:
        enc_snapshot = list(known_encodings)
        uid_snapshot = list(known_user_ids)

    results = []
    for enc, loc in zip(encs, locs):
        if enc_snapshot:
            # Step 6: Euclidean distances against every known encoding in cache
            distances  = face_recognition.face_distance(enc_snapshot, enc)
            best_index = int(np.argmin(distances))
            best_dist  = float(distances[best_index])
        else:
            best_dist = 1.0

        # Step 7: Match if within TOLERANCE (0.45 is stricter than the 0.6 default)
        # LIVENESS HOOK: a liveness check (blink / head-movement) would be inserted here
        #   before accepting the match -- currently deferred as a future enhancement.
        if enc_snapshot and best_dist <= config.TOLERANCE:
            uid        = uid_snapshot[best_index]
            name       = _get_user_name(uid)
            confidence = compute_confidence(best_dist)
        else:
            uid, name, confidence = None, "Unknown", None

        # Step 8: Scale bounding box back to original frame dimensions (multiply by 4)
        top, right, bottom, left = [v * 4 for v in loc]

        results.append({
            "user_id":    uid,
            "full_name":  name,
            "confidence": confidence,
            "bounding_box": {"top": top, "right": right, "bottom": bottom, "left": left},
        })

    return results
