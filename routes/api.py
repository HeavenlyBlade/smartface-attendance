"""
routes/api.py — JSON API Blueprint for SmartFace

Endpoints
---------
POST /api/enroll        — Enroll a new user with face samples (admin only)
GET  /api/live-feed     — Today's attendance records for dashboard polling
POST /api/recognize     — Frame recognition pipeline (filled in Task 3.7)

All endpoints return JSON.  Error responses always include an "error" key.
Success responses always include a "success": true key.

Notes
-----
- POST /api/enroll uses get_connection() directly (not execute_query) so the
  entire insert can be wrapped in a single manual transaction with explicit
  commit / rollback.
- RA 10173 compliance: consent_given must equal 1 before any face_encodings
  row is created.  This is validated server-side regardless of front-end state.
- Duplicate detection queries run BEFORE the transaction is opened so that no
  partial state is written on a conflict.
"""

import base64
import logging
import os
import secrets

from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash

import time

import config
from models.audit import ACTION_ENROLL, write_audit
from models.db import execute_query, get_connection
from routes.auth import role_required
from services import attendance_service, face_service
from services.face_service import (
    encode_samples,
    reload_known_faces,
    serialize_encoding,
)

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# POST /api/enroll
# ---------------------------------------------------------------------------

@api_bp.route("/enroll", methods=["POST"])
@role_required("admin")
def enroll():
    """
    Enroll a new user with 3–5 face samples.

    Request JSON body
    -----------------
    {
        "full_name":     str,         # 1–100 chars
        "email":         str,         # valid email, max 254 chars
        "id_number":     str,         # 1–50 chars; must be unique
        "department":    str,         # 1–100 chars
        "role":          str,         # admin | faculty | student
        "consent_given": int,         # MUST be 1 (RA 10173)
        "samples":       list[str],   # 3–5 base64-encoded JPEG strings
    }

    Response (success)
    ------------------
    HTTP 200  {"success": true, "user_id": <int>, "message": "User enrolled successfully"}

    Response (failure)
    ------------------
    HTTP 400  {"error": "<descriptive message>"}
    HTTP 500  {"error": "<descriptive message>"}

    Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
    """
    data = request.get_json(silent=True) or {}

    # ------------------------------------------------------------------
    # 1. Validate consent (RA 10173) — Requirement 3.3
    # ------------------------------------------------------------------
    if int(data.get("consent_given", 0)) != 1:
        return jsonify({"error": "Consent under RA 10173 is required before enrollment."}), 400

    # ------------------------------------------------------------------
    # 2. Extract and basic-validate required fields
    # ------------------------------------------------------------------
    full_name  = str(data.get("full_name",  "")).strip()
    email      = str(data.get("email",      "")).strip()
    id_number  = str(data.get("id_number",  "")).strip()
    department = str(data.get("department", "")).strip()
    role       = str(data.get("role",       "")).strip().lower()
    samples_b64: list = data.get("samples", [])

    missing = [f for f, v in [
        ("full_name", full_name), ("email", email), ("id_number", id_number),
        ("department", department), ("role", role),
    ] if not v]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    if role not in {"admin", "faculty", "student"}:
        return jsonify({"error": f"Invalid role '{role}'. Must be admin, faculty, or student."}), 400

    if not isinstance(samples_b64, list) or not (3 <= len(samples_b64) <= 5):
        return jsonify({"error": "Between 3 and 5 face samples are required."}), 400

    # ------------------------------------------------------------------
    # 3. Decode base64 samples → raw JPEG bytes
    # ------------------------------------------------------------------
    raw_samples: list[bytes] = []
    for idx, b64_str in enumerate(samples_b64, start=1):
        try:
            # Strip data-URI prefix if the browser included it
            if isinstance(b64_str, str) and b64_str.startswith("data:"):
                b64_str = b64_str.split(",", 1)[1]
            raw = base64.b64decode(b64_str)
        except Exception:
            return jsonify({"error": f"Sample {idx}: invalid base64 encoding."}), 400
        if len(raw) > 5 * 1024 * 1024:  # 5 MB cap (Requirement 3.2)
            return jsonify({"error": f"Sample {idx}: image exceeds the 5 MB size limit."}), 400
        raw_samples.append(raw)

    # ------------------------------------------------------------------
    # 4. Detect faces in every sample — Requirement 3.5
    #    No DB writes if any sample has no detectable face.
    # ------------------------------------------------------------------
    try:
        encodings = encode_samples(raw_samples)
    except ValueError as exc:
        # encode_samples raises ValueError("Sample N: no face detected in image")
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        # face_recognition library missing
        logger.error("enroll: face_recognition unavailable: %s", exc)
        return jsonify({"error": "Face recognition library is unavailable on this server."}), 500

    # ------------------------------------------------------------------
    # 5. Duplicate email / ID number check — Requirement 3.6
    # ------------------------------------------------------------------
    try:
        existing_email = execute_query(
            "SELECT id FROM users WHERE email = %s LIMIT 1",
            params=(email,),
            fetchone=True,
        )
        if existing_email:
            return jsonify({"error": "A user with that email already exists."}), 400

        existing_id = execute_query(
            "SELECT id FROM users WHERE id_number = %s LIMIT 1",
            params=(id_number,),
            fetchone=True,
        )
        if existing_id:
            return jsonify({"error": "A user with that ID number already exists."}), 400
    except Exception as exc:
        logger.error("enroll: duplicate check failed: %s", exc)
        return jsonify({"error": "Database error during duplicate check."}), 500

    # ------------------------------------------------------------------
    # 6. Transaction: INSERT users, face_encodings, save JPEGs, audit log
    #    Requirement 3.4, 3.7, 3.8
    # ------------------------------------------------------------------
    # Generate a random initial password — admin will reset later.
    initial_password = secrets.token_urlsafe(16)
    password_hash = generate_password_hash(initial_password)

    conn = None
    new_user_id: int | None = None

    try:
        conn = get_connection()
        conn.autocommit = False
        import psycopg2.extras as _pgx
        cursor = conn.cursor(cursor_factory=_pgx.RealDictCursor)

        # ---- Step A: INSERT users row --------------------------------
        try:
            cursor.execute(
                "INSERT INTO users "
                "(full_name, email, password_hash, role, id_number, department, consent_given) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (full_name, email, password_hash, role, id_number, department, 1),
            )
            new_user_id = cursor.lastrowid
            logger.info("enroll: inserted users row id=%s", new_user_id)
        except Exception as exc:
            logger.error("enroll: failed to insert users row: %s", exc)
            conn.rollback()
            return jsonify({"error": "Failed at step: creating user record."}), 500

        # ---- Step B: INSERT face_encodings BLOBs --------------------
        # Requirement 3.7 — serialize with enc.tobytes()
        try:
            encoding_rows = [
                (new_user_id, serialize_encoding(enc), idx + 1)
                for idx, enc in enumerate(encodings)
            ]
            cursor.executemany(
                "INSERT INTO face_encodings (user_id, encoding, sample_no) VALUES (%s, %s, %s)",
                encoding_rows,
            )
            logger.info("enroll: inserted %d face_encodings for user_id=%s", len(encodings), new_user_id)
        except Exception as exc:
            logger.error("enroll: failed to insert face_encodings: %s", exc)
            conn.rollback()
            return jsonify({"error": "Failed at step: saving facial encodings."}), 500

        # ---- Step C: Save raw JPEGs to disk -------------------------
        # Requirement 3.4 — uploads/face_samples/{user_id}/sample_{n}.jpg
        user_sample_dir = os.path.join(config.UPLOAD_DIR, str(new_user_id))
        try:
            os.makedirs(user_sample_dir, exist_ok=True)
            for n, raw_jpeg in enumerate(raw_samples, start=1):
                sample_path = os.path.join(user_sample_dir, f"sample_{n}.jpg")
                with open(sample_path, "wb") as fh:
                    fh.write(raw_jpeg)
            logger.info("enroll: saved %d JPEG samples to %s", len(raw_samples), user_sample_dir)
        except Exception as exc:
            logger.error("enroll: failed to save JPEG samples: %s", exc)
            conn.rollback()
            # Best-effort: clean up any partially written files
            try:
                import shutil
                shutil.rmtree(user_sample_dir, ignore_errors=True)
            except Exception:
                pass
            return jsonify({"error": "Failed at step: saving sample images to disk."}), 500

        # ---- Step D: Commit transaction ----------------------------
        try:
            conn.commit()
            logger.info("enroll: transaction committed for user_id=%s", new_user_id)
        except Exception as exc:
            logger.error("enroll: commit failed: %s", exc)
            conn.rollback()
            return jsonify({"error": "Failed at step: committing database transaction."}), 500

    except Exception as exc:
        # Catch-all for unexpected errors (e.g. connection failure)
        logger.error("enroll: unexpected error: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"error": "Unexpected server error during enrollment."}), 500
    finally:
        if conn is not None:
            try:
                cursor.close()
            except Exception:
                pass
            conn.close()

    # ------------------------------------------------------------------
    # 7. Post-commit: write audit log, reload encoding cache
    #    These happen outside the transaction — Requirement 3.4, 4.5
    # ------------------------------------------------------------------

    # Audit log (fire-and-forget; write_audit swallows its own exceptions)
    admin_id = session.get("user_id")
    write_audit(
        user_id=admin_id,
        action=ACTION_ENROLL,
        details=f"Admin user_id={admin_id} enrolled user_id={new_user_id} ({full_name}, {email})",
        ip_address=request.remote_addr or "",
    )

    # Reload in-memory encoding cache so the new face is immediately
    # available for recognition without restarting the server.
    try:
        reload_known_faces()
    except Exception as exc:
        # Non-fatal: enrollment succeeded; cache will catch up on next reload.
        logger.error("enroll: reload_known_faces() failed after enrollment: %s", exc)

    return jsonify({
        "success": True,
        "user_id": new_user_id,
        "message": "User enrolled successfully",
    }), 200


# ---------------------------------------------------------------------------
# GET /api/live-feed  (stub — full implementation in Task 4.2)
# ---------------------------------------------------------------------------

@api_bp.route("/live-feed", methods=["GET"])
@role_required("admin", "faculty")
def live_feed():
    """
    Return today's attendance records as JSON for the dashboard poller.

    Response: {"faces": [...records...]}

    Requirements: 7.3, 7.4
    """
    try:
        from models.attendance import get_today_records
        records = get_today_records()
        # Serialise timedelta / time objects to strings
        safe = []
        for r in records:
            safe.append({
                "full_name":  r.get("full_name", ""),
                "id_number":  r.get("id_number", ""),
                "time_in":    str(r["time_in"])  if r.get("time_in")  else None,
                "time_out":   str(r["time_out"]) if r.get("time_out") else None,
                "status":     r.get("status"),
                "confidence": r.get("confidence"),
            })
        return jsonify({"faces": safe}), 200
    except Exception as exc:
        logger.error("live_feed: DB error — %s", exc)
        return jsonify({"error": "Database unavailable"}), 503


# ---------------------------------------------------------------------------
# POST /api/recognize
# ---------------------------------------------------------------------------

@api_bp.route("/recognize", methods=["POST"])
@role_required("admin", "faculty")
def recognize():
    """
    Real-time face recognition pipeline endpoint.

    Accepts a single base64-encoded JPEG frame from the kiosk, runs the full
    face recognition pipeline, logs attendance for every matched face, and
    returns the result list to the caller.

    Request JSON body
    -----------------
    {
        "image": str   # base64-encoded JPEG (with or without data-URI prefix)
    }

    Response (success — always 200 even when no faces are detected)
    ---------------------------------------------------------------
    HTTP 200  {"faces": [ {user_id, full_name, confidence, bounding_box}, ... ]}
              {"faces": []}  when no faces are detected in the frame

    Response (failure)
    ------------------
    HTTP 400  {"error": "Invalid image payload"}   — bad base64 or missing field
    HTTP 400  {"error": "Could not decode image"}  — valid base64 but unreadable image
    HTTP 503  {"error": "Database unavailable"}    — DB error during attendance log

    Requirements: 5.4, 5.5, 5.6, 5.7, 5.8, 5.10
    """
    data = request.get_json(silent=True) or {}

    # ------------------------------------------------------------------
    # 1. Extract and validate image payload
    #    Requirement 5.5 — return 400 on bad base64
    # ------------------------------------------------------------------
    image_b64 = data.get("image")
    if not image_b64 or not isinstance(image_b64, str):
        return jsonify({"error": "Invalid image payload"}), 400

    # Strip data-URI prefix if the browser included it (e.g. "data:image/jpeg;base64,...")
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[-1]

    # ------------------------------------------------------------------
    # 2. Run recognition pipeline
    #    Requirement 5.4 — decode, downscale, detect, compare
    # ------------------------------------------------------------------
    t_start = time.monotonic()
    try:
        faces = face_service.recognize_frame(image_b64)
    except ValueError as exc:
        # recognize_frame raises ValueError for:
        #   - "Invalid base64 payload: ..."  →  400 Invalid image payload
        #   - "Could not decode image"       →  400 Could not decode image
        err_msg = str(exc)
        logger.warning("recognize: ValueError from recognize_frame: %s", err_msg)
        if "Could not decode image" in err_msg:
            return jsonify({"error": "Could not decode image"}), 400
        # Any other ValueError (bad base64, etc.) → generic payload error
        return jsonify({"error": "Invalid image payload"}), 400
    except Exception as exc:
        # Any unexpected error in the recognition pipeline — the frame is
        # the user's input, so we return 400, not 500.
        logger.error("recognize: unexpected error in recognition pipeline: %s", exc)
        return jsonify({"error": "Invalid image payload"}), 400

    elapsed = time.monotonic() - t_start
    if elapsed > 2.0:
        # Requirement 15.2 — recognition should complete within 2 s.
        # Log a warning but still return the result; never drop the response.
        logger.warning(
            "recognize: pipeline took %.3f s (> 2 s threshold)", elapsed
        )

    # ------------------------------------------------------------------
    # 3. Log attendance for every matched (known) face
    #    Requirements 5.6, 5.10 — matched faces trigger attendance logging;
    #    Unknown faces (user_id is None) are skipped (Requirement 5.7).
    # ------------------------------------------------------------------
    for face in faces:
        uid = face.get("user_id")
        if uid is None:
            # Unknown face — do not log attendance (Requirement 5.7)
            continue

        confidence = face.get("confidence")
        result = attendance_service.log_attendance(uid, confidence)

        if result.get("reason") == "db_error":
            # Requirement 5.8 / 6.7 — DB failure → 503
            logger.error(
                "recognize: DB error while logging attendance for user_id=%d: %s",
                uid, result.get("error"),
            )
            return jsonify({"error": "Database unavailable"}), 503

    # ------------------------------------------------------------------
    # 4. Return the faces array
    #    Requirement 5.8 — always 200; {"faces": []} when no faces detected
    # ------------------------------------------------------------------
    return jsonify({"faces": faces}), 200

