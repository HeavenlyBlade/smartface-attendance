"""
services/face_service.py -- SmartFace facial encoding cache and recognition pipeline
Backend: face_recognition + dlib-bin. Liveness: EAR blink detection.
"""

import base64
import logging
import os
import threading
import time
from typing import Optional

import cv2
import numpy as np

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None
    FACE_RECOGNITION_AVAILABLE = False
    logging.getLogger(__name__).warning("face_recognition not available")

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory encoding cache
# ---------------------------------------------------------------------------
known_encodings: list = []
known_user_ids:  list = []
_cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Liveness detection — EAR (Eye Aspect Ratio) blink detection
# ---------------------------------------------------------------------------
def _resolve_predictor_path() -> str:
    import sys
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        p = os.path.join(base, "models", "shape_predictor_68_face_landmarks.dat")
        if os.path.exists(p):
            return os.path.abspath(p)
    p = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "shape_predictor_68_face_landmarks.dat"))
    if os.path.exists(p):
        return p
    cwd_p = os.path.abspath(os.path.join("models", "shape_predictor_68_face_landmarks.dat"))
    if os.path.exists(cwd_p):
        return cwd_p
    return p

_PREDICTOR_PATH = _resolve_predictor_path()
_predictor  = None
_dlib_hog   = None
_predictor_lock = threading.Lock()

def _load_predictor():
    global _predictor, _dlib_hog
    if _predictor is not None:
        return
    with _predictor_lock:
        if _predictor is not None:
            return
        if os.path.exists(_PREDICTOR_PATH):
            try:
                import dlib
                _predictor = dlib.shape_predictor(_PREDICTOR_PATH)
                _dlib_hog  = dlib.get_frontal_face_detector()
                logger.info("Shape predictor loaded — liveness detection active")
            except Exception as exc:
                logger.warning("Shape predictor load failed: %s", exc)
        else:
            logger.warning("shape_predictor_68 not found — liveness disabled")

def _ear(pts) -> float:
    """Eye Aspect Ratio from 6 (x,y) landmark points."""
    def d(a, b): return float(np.linalg.norm(np.array(a) - np.array(b)))
    A = d(pts[1], pts[5])
    B = d(pts[2], pts[4])
    C = d(pts[0], pts[3])
    return (A + B) / (2.0 * C + 1e-6)

def _face_ear(gray, loc=None) -> float:
    """Compute mean EAR for a face. If loc is provided, uses bounding box directly."""
    _load_predictor()
    if _predictor is None:
        return 0.35  # assume open if predictor unavailable
    try:
        import dlib
        if loc is not None:
            t, r, b, l = loc
            rect = dlib.rectangle(int(l), int(t), int(r), int(b))
        else:
            faces = _dlib_hog(gray, 0)
            if not faces:
                return 0.35
            rect = faces[0]
        shape = _predictor(gray, rect)
        L = [(shape.part(i).x, shape.part(i).y) for i in range(36, 42)]
        R = [(shape.part(i).x, shape.part(i).y) for i in range(42, 48)]
        return (_ear(L) + _ear(R)) / 2.0
    except Exception as exc:
        logger.debug("_face_ear error: %s", exc)
        return 0.35

_frame_ear = _face_ear

# Liveness state: uid -> {blinked, frames_closed}
_liveness: dict = {}
_EAR_THRESH = 0.22   # below this = eyes closed
_EAR_FRAMES = 1      # single closed frame = blink confirmed

def reset_liveness_state(uid=None):
    """Reset blink state. uid=None resets all users."""
    global _liveness
    if uid is None:
        _liveness.clear()
    elif uid in _liveness:
        del _liveness[uid]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_encoding(enc) -> bytes:
    return enc.tobytes()

def deserialize_encoding(blob: bytes):
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
    enc_tmp, uid_tmp = [], []
    for row in (rows or []):
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape != (128,): raise ValueError("bad shape")
            enc_tmp.append(enc)
            uid_tmp.append(int(row["user_id"]))
        except Exception as exc:
            logger.warning("load_known_faces: skipping uid=%s: %s", row.get("user_id"), exc)
    with _cache_lock:
        known_encodings[:] = enc_tmp
        known_user_ids[:]  = uid_tmp
    logger.info("load_known_faces: %d encoding(s) loaded.", len(known_encodings))


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
    enc_tmp, uid_tmp = [], []
    for row in (rows or []):
        try:
            enc = deserialize_encoding(bytes(row["encoding"]))
            if enc.shape != (128,): raise ValueError("bad shape")
            enc_tmp.append(enc)
            uid_tmp.append(int(row["user_id"]))
        except Exception as exc:
            logger.warning("reload_known_faces: skipping uid=%s: %s", row.get("user_id"), exc)
    with _cache_lock:
        known_encodings[:] = enc_tmp
        known_user_ids[:]  = uid_tmp
    logger.info("reload_known_faces: %d encoding(s) loaded.", len(known_encodings))


# ---------------------------------------------------------------------------
# Enrollment with quality checks
# ---------------------------------------------------------------------------

def encode_samples(image_list: list) -> list:
    if not FACE_RECOGNITION_AVAILABLE:
        raise RuntimeError("face_recognition is not installed")
    results = []
    for idx, img_bytes in enumerate(image_list, start=1):
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Sample {idx}: could not decode image")

        # -- Preprocessing: CLAHE to improve low-light / low-contrast frames --
        lab   = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l     = clahe.apply(l)
        frame = cv2.cvtColor(cv2.merge([l, a, b_ch]), cv2.COLOR_LAB2BGR)

        # -- Preprocessing: mild unsharp mask to recover soft/slightly blurry frames --
        blurred = cv2.GaussianBlur(frame, (0, 0), 3)
        frame   = cv2.addWeighted(frame, 1.5, blurred, -0.5, 0)

        # Quality check 1: blur score (lowered threshold — JPEG compression
        # and webcam noise already reduce Laplacian variance significantly)
        gray_q = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur   = cv2.Laplacian(gray_q, cv2.CV_64F).var()
        if blur < 30:
            raise ValueError(
                f"Sample {idx}: image too blurry (score={blur:.0f}) "
                f"-- hold still and ensure good lighting"
            )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Face detection: try HOG first (fast), fall back to CNN if no face found
        locs = face_recognition.face_locations(rgb, model="hog")
        if not locs:
            locs = face_recognition.face_locations(rgb, model="cnn")
        if not locs:
            raise ValueError(f"Sample {idx}: no face detected -- face the camera directly")

        # Quality check 2: face size >= 6% of frame (lowered from 8% to be less strict)
        t, r, b, l = locs[0]
        face_pct = ((b - t) * (r - l)) / (frame.shape[0] * frame.shape[1])
        if face_pct < 0.06:
            raise ValueError(
                f"Sample {idx}: face too small ({face_pct*100:.1f}%) "
                f"-- move closer to the camera"
            )

        encs = face_recognition.face_encodings(rgb, known_face_locations=locs, num_jitters=5)
        if not encs:
            raise ValueError(f"Sample {idx}: could not compute face encoding")
        results.append(encs[0])
    return results


# ---------------------------------------------------------------------------
# Property test helpers
# ---------------------------------------------------------------------------

def compute_confidence(distance: float) -> float:
    return round((1 - distance) * 100, 2)


def classify_face_match(distance: float, user_id=None, full_name=None) -> dict:
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
        row = execute_query("SELECT full_name FROM users WHERE id = ?",
                            params=(user_id,), fetchone=True)
        return row["full_name"] if row else f"User#{user_id}"
    except Exception as exc:
        logger.warning("_get_user_name: %s", exc)
        return f"User#{user_id}"


def recognize_frame(image_b64: str) -> list:
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

    # Step 2: Adaptive downscale for fast face detection (320px width)
    h, w = frame.shape[:2]
    if w > 320:
        fx = 320.0 / w
        small = cv2.resize(frame, (0, 0), fx=fx, fy=fx)
        inv_scale = 1.0 / fx
    else:
        small = frame
        inv_scale = 1.0

    # Step 3: BGR -> RGB (face_recognition expects RGB input)
    rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

    # Step 4: Detect face bounding boxes in the downscaled frame
    locs_raw = face_recognition.face_locations(rgb_small, model="hog")
    if not locs_raw:
        return []

    # Scale bounding boxes back to full-frame dimensions
    if inv_scale != 1.0:
        locs = [
            (
                int(round(t * inv_scale)),
                int(round(r * inv_scale)),
                int(round(b * inv_scale)),
                int(round(l * inv_scale)),
            )
            for t, r, b, l in locs_raw
        ]
    else:
        locs = list(locs_raw)

    # Step 5: Compute 128-dim facial encodings using crisp full-frame
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    encs = face_recognition.face_encodings(rgb_frame, locs, num_jitters=1, model="small")
    if not encs:
        return []

    with _cache_lock:
        enc_snapshot = list(known_encodings)
        uid_snapshot = list(known_user_ids)

    gray_frame = None
    results = []
    for enc, loc in zip(encs, locs):
        if enc_snapshot:
            # Step 6: Euclidean distances against every known encoding in cache
            distances  = face_recognition.face_distance(enc_snapshot, enc)
            best_index = int(np.argmin(distances))
            best_dist  = float(distances[best_index])
        else:
            best_dist = 1.0

        # Step 7: Match within TOLERANCE + LIVENESS check (EAR blink detection)
        # LIVENESS HOOK: Eye Aspect Ratio blink detection implemented here.
        # Requires one confirmed blink before each match acceptance when enabled.
        # Mitigates static photo spoofing; video replay can defeat blink detection.
        uid, name, confidence = None, "Unknown", None
        if enc_snapshot and best_dist <= config.TOLERANCE:
            cand_uid = uid_snapshot[best_index]
            if config.REQUIRE_LIVENESS:
                state = _liveness.setdefault(cand_uid, {"blinked": False, "frames_closed": 0})
                if not state["blinked"]:
                    if gray_frame is None:
                        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    ear = _face_ear(gray_frame, loc)
                    if ear < _EAR_THRESH:
                        state["frames_closed"] += 1
                        if state["frames_closed"] >= _EAR_FRAMES:
                            state["blinked"] = True
                            logger.info("Liveness confirmed uid=%s (EAR=%.3f)", cand_uid, ear)
                    else:
                        state["frames_closed"] = 0
                if state["blinked"]:
                    uid        = cand_uid
                    name       = _get_user_name(uid)
                    confidence = compute_confidence(best_dist)
                else:
                    uid        = None
                    name       = f"Verifying ({_get_user_name(cand_uid)})..."
                    confidence = compute_confidence(best_dist)
            else:
                uid        = cand_uid
                name       = _get_user_name(uid)
                confidence = compute_confidence(best_dist)

        # Bounding box in original frame dimensions
        top, right, bottom, left = loc

        face_dict = {
            "user_id":    uid,
            "full_name":  name,
            "confidence": confidence,
            "bounding_box": {"top": top, "right": right, "bottom": bottom, "left": left},
        }
        results.append(face_dict)

        # Reset liveness so the next recognition event requires a fresh blink
        if uid is not None and config.REQUIRE_LIVENESS:
            _liveness[uid] = {"blinked": False, "frames_closed": 0}

    return results
