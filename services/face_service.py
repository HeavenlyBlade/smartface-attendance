"""
services/face_service.py -- SmartFace facial encoding cache and recognition pipeline

Backend: DeepFace + Facenet (128-dim embeddings).
Replaced face_recognition/dlib because dlib cannot be compiled on Render's
free tier (512 MB RAM).  The public interface -- module-level state, all
function signatures, DB schema, and recognize_frame() return shape -- is
identical to the previous implementation so the rest of the codebase is
unaffected.

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
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except ImportError:
    DeepFace = None  # type: ignore
    DEEPFACE_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "deepface not available -- recognition will return all faces as Unknown"
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
# Internal distance helper
# ---------------------------------------------------------------------------

def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine distance between two 128-dim Facenet embeddings.

    Formula: 1 - cos_similarity = 1 - (a·b) / (‖a‖ · ‖b‖)
    Range: [0.0, 2.0] -- 0.0 is identical, 2.0 is perfectly opposite.

    Cosine distance is preferred over Euclidean for Facenet embeddings because
    Facenet is trained with a triplet loss that optimises angular separation
    rather than absolute magnitude, making cosine a better geometric match.

    Args:
        a, b: np.ndarray of shape (128,), dtype float64

    Returns:
        float cosine distance
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0  # treat zero-vector as maximally dissimilar
    return float(1.0 - np.dot(a, b) / (norm_a * norm_b))


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
    Compute a 128-dim Facenet embedding for each raw JPEG in image_list.

    Accepts raw JPEG bytes (from file reads or multipart upload).
    Returns one embedding per image.  Raises ValueError if an image contains
    no detectable face (caller decides how to handle the error).

    Uses DeepFace.represent() with model_name="Facenet" which produces
    128-dimensional embeddings -- same dimensionality as the old dlib
    pipeline, so the DB schema (1024-byte BLOBs) is unchanged.

    Args:
        image_list: list of raw JPEG bytes, one per enrollment sample

    Returns:
        list of np.ndarray, each of shape (128,), dtype float64

    Raises:
        ValueError: if no face is detected in one of the samples (index given)
        RuntimeError: if deepface library is not available
    """
    if not DEEPFACE_AVAILABLE:
        raise RuntimeError("deepface library is not installed")

    results: list[np.ndarray] = []
    for idx, img_bytes in enumerate(image_list, start=1):
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Sample {idx}: could not decode image")

        # DeepFace expects RGB input; OpenCV decodes as BGR
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        try:
            result = DeepFace.represent(
                img_path=rgb,
                model_name="Facenet",
                enforce_detection=True,
            )
        except ValueError:
            raise ValueError(f"Sample {idx}: no face detected in image")

        embedding = np.array(result[0]["embedding"], dtype=np.float64)  # shape (128,)
        results.append(embedding)

    return results


# ---------------------------------------------------------------------------
# Property test helpers
# ---------------------------------------------------------------------------

def compute_confidence(distance: float) -> float:
    """
    Convert a face cosine distance to a confidence percentage.

    Formula: round((1 - distance) * 100, 2)
    Valid range for matched faces: distance in [0.0, TOLERANCE] -> confidence in [60.0, 100.0]

    Used directly by Property 6 tests in test_face_service.py.

    Note on TOLERANCE change: the threshold is 0.40 (cosine) vs the old 0.45
    (Euclidean) because Facenet cosine distances are on a tighter scale than
    dlib Euclidean distances.  The confidence formula is unchanged.

    Args:
        distance: cosine face distance (0.0 = identical, higher = less similar)

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
        distance: cosine face distance
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
    if not DEEPFACE_AVAILABLE:
        logger.error("recognize_frame: deepface not available")
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
    # Reducing dimensions by 75% means DeepFace processes 1/16th the pixels,
    # cutting detection time from ~2s to ~0.3s on typical hardware.
    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)

    # Step 3: BGR (OpenCV default) -> RGB (DeepFace/Facenet expects RGB input)
    # Passing BGR produces corrupted color information and degrades accuracy.
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

    # Step 4: DeepFace.represent() -- detect all faces and compute Facenet embeddings.
    # enforce_detection=False so that a frameless call returns [] instead of raising.
    try:
        face_results = DeepFace.represent(
            img_path=rgb,
            model_name="Facenet",
            enforce_detection=False,
        )
    except Exception as exc:
        logger.warning("recognize_frame: DeepFace.represent failed: %s", exc)
        return []

    # DeepFace returns an empty list when no faces are found
    if not face_results:
        return []

    # Snapshot the cache for thread safety (avoids holding the lock during comparison)
    with _cache_lock:
        enc_snapshot = list(known_encodings)
        uid_snapshot = list(known_user_ids)

    results = []
    for face in face_results:
        # Step 5: Extract the 128-dim Facenet embedding for this face
        embedding = np.array(face["embedding"], dtype=np.float64)

        if enc_snapshot:
            # Step 6: Cosine distances against every known encoding in cache.
            # Cosine distance is preferred for Facenet (trained with angular triplet loss).
            distances  = np.array([_cosine_distance(embedding, known) for known in enc_snapshot])
            best_index = int(np.argmin(distances))
            best_dist  = float(distances[best_index])
        else:
            best_dist = 1.0   # empty cache -> treat as Unknown

        # Step 7: Match if within TOLERANCE (0.40 cosine is stricter than the 0.6 Euclidean default)
        # LIVENESS HOOK: a liveness check (blink / head-movement) would be inserted here
        #   before accepting the match -- currently deferred as a future enhancement.
        if enc_snapshot and best_dist <= config.TOLERANCE:
            uid        = uid_snapshot[best_index]
            name       = _get_user_name(uid)
            confidence = compute_confidence(best_dist)
        else:
            uid, name, confidence = None, "Unknown", None

        # Step 8: Extract bounding box from DeepFace facial_area and scale back to
        # original frame dimensions (multiply by 4 since we downscaled to 0.25x).
        # DeepFace facial_area format: {x, y, w, h} (top-left origin, width, height)
        # -> convert to {top, right, bottom, left} to match the previous interface.
        facial_area = face.get("facial_area", {})
        x = facial_area.get("x", 0)
        y = facial_area.get("y", 0)
        w = facial_area.get("w", 0)
        h = facial_area.get("h", 0)

        top    = y * 4
        left   = x * 4
        bottom = (y + h) * 4
        right  = (x + w) * 4

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
