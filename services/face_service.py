"""
services/face_service.py -- SmartFace facial encoding cache and recognition pipeline

Module-level State
------------------
known_encodings : list[np.ndarray]
    Flat list of all enrolled facial encodings (128-dim float64 each).
    Multiple entries per user (one per enrollment sample) for higher accuracy.
known_user_ids : list[int]
    Parallel list mapping each encoding index to its owner's user_id.
_cache_lock : threading.Lock
    Guards atomic replacement of both lists during reload_known_faces().

Startup
-------
Call load_known_faces() once during app initialisation (app.py startup hook).
After any enrollment, call reload_known_faces() to refresh the cache.
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
    FACE_RECOGNITION_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "face_recognition not available -- recognition will return all faces as Unknown"
    )

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level in-memory encoding cache
# ---------------------------------------------------------------------------

known_encodings: list[np.ndarray] = []   # 128-dim float64 per sample
known_user_ids:  list[int]        = []   # parallel index: same length as known_encodings
_cache_lock = threading.Lock()           # guards atomic replacement during reload


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def serialize_encoding(enc: np.ndarray) -> bytes:
    """
    Serialize a 128-dim float64 numpy array to raw bytes for BLOB storage.

    enc.tobytes() produces 128 * 8 = 1024 bytes (little-endian float64).
    This is the inverse of deserialize_encoding().

    Args:
        enc: np.ndarray of shape (128,) and dtype float64

    Returns:
        bytes of length 1024
    """
    return enc.tobytes()


def deserialize_encoding(blob: bytes) -> np.ndarray:
    """
    Deserialize a 1024-byte BLOB from the database back to a numpy array.

    np.frombuffer(blob, dtype=np.float64) yields shape (128,) -- the same
    array that was originally serialized with enc.tobytes().

    Args:
        blob: bytes of length 1024 from the face_encodings.encoding column

    Returns:
        np.ndarray of shape (128,), dtype float64
    """
    return np.frombuffer(blob, dtype=np.float64)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def load_known_faces() -> None:
    """
    Load all non-null facial encodings from the database into the in-memory cache.

    Called once at application startup (app.py startup hook).
    If the database is unreachable, logs an error and leaves the cache empty
    so that the application can still start and retry later.

    Requirements: 4.1, 4.6
    """
    global known_encodings, known_user_ids

    try:
        from models.db import execute_query
        rows = execute_query(
            "SELECT user_id, encoding FROM face_encodings WHERE encoding IS NOT NULL",
            fetchall=True
        )
    except Exception as exc:
        logger.error(
            "load_known_faces: DB unreachable at startup -- starting with empty cache. Error: %s", exc
        )
        return  # stay operational with empty cache

    encodings_tmp: list[np.ndarray] = []
    user_ids_tmp:  list[int]        = []

    for row in rows:
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape != (128,):
                raise ValueError(f"Unexpected shape {enc.shape}")
            encodings_tmp.append(enc)
            user_ids_tmp.append(int(row["user_id"]))
        except Exception as exc:
            logger.warning(
                "load_known_faces: skipping undeserializable row for user_id=%s: %s",
                row.get("user_id"), exc
            )

    with _cache_lock:
        known_encodings[:] = encodings_tmp
        known_user_ids[:]  = user_ids_tmp

    logger.info("load_known_faces: loaded %d encoding(s) for the recognition cache.", len(known_encodings))


def reload_known_faces() -> None:
    """
    Atomically rebuild both known_encodings and known_user_ids from the database.

    Called after every successful enrollment so that the new face is immediately
    available for recognition without restarting the server.

    The replacement is atomic: any concurrent recognize_frame() call observes
    either the fully previous or the fully updated cache -- never a partial state.

    Requirements: 4.2, 4.5
    """
    global known_encodings, known_user_ids

    try:
        from models.db import execute_query
        rows = execute_query(
            "SELECT user_id, encoding FROM face_encodings WHERE encoding IS NOT NULL",
            fetchall=True
        )
    except Exception as exc:
        logger.error("reload_known_faces: DB error -- cache not updated. Error: %s", exc)
        return

    encodings_tmp: list[np.ndarray] = []
    user_ids_tmp:  list[int]        = []

    for row in rows:
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape != (128,):
                raise ValueError(f"Unexpected shape {enc.shape}")
            encodings_tmp.append(enc)
            user_ids_tmp.append(int(row["user_id"]))
        except Exception as exc:
            logger.warning(
                "reload_known_faces: skipping bad row for user_id=%s: %s",
                row.get("user_id"), exc
            )

    # Atomic replacement -- swap both lists inside the lock
    with _cache_lock:
        known_encodings[:] = encodings_tmp
        known_user_ids[:]  = user_ids_tmp

    logger.info("reload_known_faces: cache refreshed -- %d encoding(s) loaded.", len(known_encodings))


# ---------------------------------------------------------------------------
# Enrollment helper
# ---------------------------------------------------------------------------

def encode_samples(image_list: list[bytes]) -> list[np.ndarray]:
    """
    Compute a 128-dim facial encoding for each raw JPEG in image_list.

    Accepts raw JPEG bytes (from file reads or multipart upload).
    Returns one encoding per image.  Raises ValueError if an image contains
    no detectable face (caller decides how to handle the error).

    Args:
        image_list: list of raw JPEG bytes, one per enrollment sample

    Returns:
        list of np.ndarray, each of shape (128,), dtype float64

    Raises:
        ValueError: if no face is detected in one of the samples (index given)
        RuntimeError: if face_recognition library is not available
    """
    if not FACE_RECOGNITION_AVAILABLE:
        raise RuntimeError("face_recognition library is not installed")

    results: list[np.ndarray] = []
    for idx, img_bytes in enumerate(image_list, start=1):
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Sample {idx}: could not decode image")

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        encs = face_recognition.face_encodings(rgb)
        if len(encs) == 0:
            raise ValueError(f"Sample {idx}: no face detected in image")

        results.append(encs[0])  # take the first (and expected only) face

    return results


# ---------------------------------------------------------------------------
# Property test helpers
# ---------------------------------------------------------------------------

def compute_confidence(distance: float) -> float:
    """
    Convert a face Euclidean distance to a confidence percentage.

    Formula: round((1 - distance) * 100, 2)
    Valid range for matched faces: distance in [0.0, TOLERANCE] -> confidence in [55.0, 100.0]

    Used directly by Property 6 tests in test_face_service.py.

    Args:
        distance: Euclidean face distance (0.0 = identical, higher = less similar)

    Returns:
        confidence as float, e.g. 72.50
    """
    return round((1 - distance) * 100, 2)


def classify_face_match(distance: float, user_id: Optional[int] = None,
                         full_name: Optional[str] = None) -> dict:
    """
    Classify a face match result based on TOLERANCE.

    Returns a dict with user_id, full_name, and confidence.
    If distance > TOLERANCE, returns Unknown result (user_id=None).
    Used directly by Property 7 tests in test_face_service.py.

    Args:
        distance: Euclidean face distance
        user_id: known user_id to return if within tolerance (None for unknown)
        full_name: known name to return if within tolerance

    Returns:
        dict with keys: user_id, full_name, confidence
    """
    if known_encodings and distance <= config.TOLERANCE:
        return {
            "user_id":    user_id,
            "full_name":  full_name or "Unknown",
            "confidence": compute_confidence(distance),
        }
    # Above tolerance OR empty cache -> Unknown
    return {
        "user_id":    None,
        "full_name":  "Unknown",
        "confidence": None,
    }


# ---------------------------------------------------------------------------
# Recognition pipeline
# ---------------------------------------------------------------------------

def _get_user_name(user_id: int) -> str:
    """Fetch full_name for a user_id from the DB (with fallback)."""
    try:
        from models.db import execute_query
        row = execute_query(
            "SELECT full_name FROM users WHERE id = %s",
            params=(user_id,), fetchone=True
        )
        return row["full_name"] if row else f"User#{user_id}"
    except Exception as exc:
        logger.warning("_get_user_name: DB error for user_id=%s: %s", user_id, exc)
        return f"User#{user_id}"


def recognize_frame(image_b64: str) -> list[dict]:
    """
    Full recognition pipeline: base64 JPEG -> list of face match dicts.

    Processes a single webcam frame and returns one dict per detected face.
    Returns an empty list when no faces are found (never raises on no-face).
    If known_encodings is empty, all faces are returned as Unknown.

    Args:
        image_b64: base64-encoded JPEG string (no data URI prefix)

    Returns:
        list of dicts, each containing:
            user_id      (int or None)
            full_name    (str -- "Unknown" if no match)
            confidence   (float or None)
            bounding_box (dict: top, right, bottom, left in original pixels)

    Raises:
        ValueError: if base64 decode fails or cv2.imdecode returns None
    """
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
    # Reducing dimensions by 75% means face_recognition processes 1/16th the pixels,
    # cutting detection time from ~2s to ~0.3s on typical hardware.
    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)

    # Step 3: BGR (OpenCV default) -> RGB (face_recognition expects RGB input)
    # face_recognition uses dlib under the hood which requires RGB channel order.
    # Passing BGR produces corrupted color information and degrades accuracy.
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

    # Step 4: Detect face bounding boxes in the downscaled frame
    locs = face_recognition.face_locations(rgb)

    # Step 5: Compute 128-dim facial encodings for each detected face
    encs = face_recognition.face_encodings(rgb, locs)

    # Early exit: no faces detected
    if not locs:
        return []

    # Snapshot the cache for thread safety (avoids holding the lock during comparison)
    with _cache_lock:
        enc_snapshot    = list(known_encodings)
        uid_snapshot    = list(known_user_ids)

    results = []
    for enc, loc in zip(encs, locs):
        if enc_snapshot:
            # Step 6: Euclidean distances against every known encoding in cache
            distances  = face_recognition.face_distance(enc_snapshot, enc)
            best_index = int(np.argmin(distances))
            best_dist  = float(distances[best_index])
        else:
            best_dist = 1.0   # empty cache -> treat as Unknown

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
        # The downscale was 0.25x, so all coordinates must be multiplied by 4
        # to match positions in the original full-resolution frame.
        top, right, bottom, left = [v * 4 for v in loc]

        results.append({
            "user_id":    uid,
            "full_name":  name,
            "confidence": confidence,
            "bounding_box": {
                "top":    top,
                "right":  right,
                "bottom": bottom,
                "left":   left,
            },
        })

    return results
