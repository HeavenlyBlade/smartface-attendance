"""
services/attendance_service.py — Attendance logging with debounce for SmartFace

Implements the attendance logging pipeline as specified in Requirements 6.1–6.8:

  - last_seen_dict  : module-level dict[int, datetime] that tracks the most
                      recent server timestamp at which each user_id was logged.
                      Used as the primary debounce guard (Requirement 6.3 / 6.8).

  - _is_debounce_elapsed(user_id) → bool
        Return True when no entry exists for user_id (first recognition today)
        OR elapsed time since the last logged entry is ≥ 30 seconds.
        Return False when elapsed < 30 seconds → caller must skip the DB write.

  - _determine_status(time_in: datetime) → str
        Compare the wall-clock time portion of time_in against config.LATE_TIME
        (HH:MM:SS string).  Returns 'present' if time_in ≤ LATE_TIME,
        'late' otherwise.  Satisfies Requirement 6.1.

  - log_attendance(user_id, confidence) → dict
        Two-guard pattern:
          Guard 1 — debounce: skip if elapsed < 30 s.
          Guard 2 — DB write: INSERT … ON CONFLICT (user_id, date) DO UPDATE (Req 6.4).
        On success: update last_seen_dict.
        On DB failure: leave last_seen_dict unchanged (Req 6.7).

All SQL uses %s parameterized placeholders — never f-string or concatenation.
"""

import logging
from datetime import datetime, time as dt_time

import config
from models.db import execute_query

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level debounce state
# Keys:   user_id  (int)
# Values: datetime of last successful DB write for that user_id
# ---------------------------------------------------------------------------

last_seen_dict: dict[int, datetime] = {}

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_DEBOUNCE_SECONDS = 30


def _is_debounce_elapsed(user_id: int) -> bool:
    """
    Return True if the debounce window has elapsed for user_id.

    Two cases qualify as "elapsed":
      1. user_id has no entry in last_seen_dict  — this is the first
         recognition ever (or first recognition today), so we allow it.
         (Requirement 6.8)
      2. elapsed time since last_seen_dict[user_id] is ≥ 30 seconds.
         (Requirement 6.2)

    Return False when elapsed < 30 seconds (Requirement 6.3).
    """
    if user_id not in last_seen_dict:
        return True  # No prior entry → treat as elapsed (Req 6.8)

    elapsed = (datetime.now() - last_seen_dict[user_id]).total_seconds()
    return elapsed >= _DEBOUNCE_SECONDS


def _determine_status(time_in: datetime, user_id: int = None) -> str:
    """
    Return 'present' if time_in is at or before the allowed arrival cutoff,
    'late' if strictly after.
    If user_id is provided, evaluates against user's schedule with grace period.
    Otherwise compares against config.LATE_TIME (Requirement 6.1).
    """
    if user_id is not None:
        try:
            from models.schedule import get_schedule_for_user, evaluate_attendance_time
            sched = get_schedule_for_user(user_id, time_in)
            eval_res = evaluate_attendance_time(sched, time_in)
            return eval_res["status"]
        except Exception as exc:
            logger.debug("_determine_status fallback to LATE_TIME: %s", exc)

    # Parse LATE_TIME from config (e.g. '08:00:00')
    parts = config.LATE_TIME.split(":")
    late_threshold: dt_time = dt_time(
        hour=int(parts[0]),
        minute=int(parts[1]),
        second=int(parts[2]),
    )

    if time_in.time() <= late_threshold:
        return "present"
    return "late"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_attendance(user_id: int, confidence: float, scanner_id: str = "Main Kiosk") -> dict:
    """
    Attempt to log (or update) an attendance record for user_id.
    """
    # ------------------------------------------------------------------
    # Guard 1: Debounce
    # ------------------------------------------------------------------
    if not _is_debounce_elapsed(user_id):
        logger.debug(
            "log_attendance: debounce active for user_id=%d — skipping", user_id
        )
        return {"logged": False, "reason": "debounce"}

    # ------------------------------------------------------------------
    # Capture wall-clock now once; use consistently throughout this call
    # ------------------------------------------------------------------
    now = datetime.now()
    today = now.date()
    time_in_str = now.strftime("%H:%M:%S")

    # Evaluate schedule
    sched_info = None
    try:
        from models.schedule import get_schedule_for_user, evaluate_attendance_time
        sched = get_schedule_for_user(user_id, now)
        sched_info = evaluate_attendance_time(sched, now)
    except Exception as exc:
        logger.debug("Schedule evaluation exception in log_attendance: %s", exc)

    if sched_info:
        status = sched_info["status"]
        late_minutes = sched_info["late_minutes"]
        schedule_id = sched_info["schedule_id"]
        late_reason = sched_info["explanation"] if status == "late" else ""
    else:
        status = _determine_status(now)
        late_minutes = 0
        schedule_id = None
        late_reason = ""

    # ------------------------------------------------------------------
    # Guard 2: DB write — INSERT … ON CONFLICT (user_id, date) DO UPDATE
    # ------------------------------------------------------------------
    sql = (
        "INSERT INTO attendance (user_id, date, time_in, status, confidence, "
        "                        schedule_id, late_minutes, late_reason, scanner_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, date) DO UPDATE SET "
        "time_out = EXCLUDED.time_in, "
        "confidence = EXCLUDED.confidence, "
        "scanner_id = EXCLUDED.scanner_id"
    )
    params = (
        user_id,
        today,
        time_in_str,
        status,
        confidence,
        schedule_id,
        late_minutes,
        late_reason,
        scanner_id or "Main Kiosk",
    )

    try:
        execute_query(sql, params=params, commit=True)
        logger.debug(
            "log_attendance: recorded user_id=%d date=%s time_in=%s status=%s conf=%.2f",
            user_id, today, time_in_str, status, confidence,
        )
    except Exception as exc:
        # Requirement 6.7: leave last_seen_dict unchanged on failure
        logger.error(
            "log_attendance: DB error for user_id=%d — %s", user_id, exc
        )
        return {"logged": False, "reason": "db_error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Requirement 6.5: update last_seen_dict only on success
    # ------------------------------------------------------------------
    last_seen_dict[user_id] = now
    # Reset liveness state so next recognition requires a fresh blink
    try:
        from services.face_service import reset_liveness_state
        reset_liveness_state(user_id)
    except Exception:
        pass

    return {"logged": True, "user_id": user_id, "status": status}
