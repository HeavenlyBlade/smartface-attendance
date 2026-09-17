"""
services/attendance_service.py — Attendance logging with debounce for SmartFace

Implements the attendance logging pipeline as specified in Requirements 6.1–6.8:

  - last_seen_dict  : module-level dict[int, datetime] that tracks the most
                      recent server timestamp at which each user_id was logged.
                      Used as the primary debounce guard (Requirement 6.3 / 6.8).

  - _is_debounce_elapsed(user_id) → bool
        Return True when no entry exists for user_id (first recognition today)
        OR elapsed time since the last logged entry is ≥ 60 seconds.
        Return False when elapsed < 60 seconds → caller must skip the DB write.

  - _determine_status(time_in: datetime) → str
        Compare the wall-clock time portion of time_in against config.LATE_TIME
        (HH:MM:SS string).  Returns 'present' if time_in ≤ LATE_TIME,
        'late' otherwise.  Satisfies Requirement 6.1.

  - log_attendance(user_id, confidence) → dict
        Two-guard pattern:
          Guard 1 — debounce: skip if elapsed < 60 s.
          Guard 2 — DB write: INSERT … ON DUPLICATE KEY UPDATE (Req 6.4).
        On success: update last_seen_dict.
        On DB failure: leave last_seen_dict unchanged (Req 6.7).

All SQL uses %s parameterized placeholders — never f-string or concatenation.
"""

import logging
from datetime import datetime, time as dt_time

import config
from models.db import execute_query
MySQLError = Exception  # psycopg2 migration

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

_DEBOUNCE_SECONDS = 60


def _is_debounce_elapsed(user_id: int) -> bool:
    """
    Return True if the debounce window has elapsed for user_id.

    Two cases qualify as "elapsed":
      1. user_id has no entry in last_seen_dict  — this is the first
         recognition ever (or first recognition today), so we allow it.
         (Requirement 6.8)
      2. elapsed time since last_seen_dict[user_id] is ≥ 60 seconds.
         (Requirement 6.2)

    Return False when elapsed < 60 seconds (Requirement 6.3).
    """
    if user_id not in last_seen_dict:
        return True  # No prior entry → treat as elapsed (Req 6.8)

    elapsed = (datetime.now() - last_seen_dict[user_id]).total_seconds()
    return elapsed >= _DEBOUNCE_SECONDS


def _determine_status(time_in: datetime) -> str:
    """
    Return 'present' if time_in is at or before config.LATE_TIME,
    'late' if time_in is strictly after config.LATE_TIME.

    config.LATE_TIME is a string in HH:MM:SS format (e.g. '08:00:00').
    (Requirement 6.1)
    """
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


def log_attendance(user_id: int, confidence: float) -> dict:
    """
    Attempt to log (or update) an attendance record for user_id.

    Guard 1 — Debounce check (Requirement 6.3, 6.8):
        If elapsed time since last_seen_dict[user_id] is < 60 seconds,
        skip the DB operation and return::

            {"logged": False, "reason": "debounce"}

    Guard 2 — DB write (Requirements 6.1, 6.2, 6.4):
        Execute a single ``INSERT … ON DUPLICATE KEY UPDATE`` statement.
        This enforces the ``UNIQUE KEY uniq_user_day (user_id, date)``
        constraint at the DB level so no duplicate daily rows can ever exist,
        even under concurrent requests.

        First recognition (INSERT path):
            - Sets time_in to now, status determined by _determine_status(),
              confidence to the supplied value.
        Subsequent recognitions on the same date (UPDATE path):
            - Updates time_out to now, refreshes confidence.

    On DB success (Requirements 6.5):
        Update last_seen_dict[user_id] = now.

    On DB failure (Requirement 6.7):
        Leave last_seen_dict unchanged.  Return error dict so the caller
        (POST /api/recognize) can respond 503.

    Parameters
    ----------
    user_id : int
        The users.id of the recognized user.
    confidence : float
        Recognition confidence value (0.00–100.00) as returned by the
        face recognition pipeline.

    Returns
    -------
    dict
        Success: ``{"logged": True, "user_id": user_id, "status": status}``
        Debounce skip: ``{"logged": False, "reason": "debounce"}``
        DB error: ``{"logged": False, "reason": "db_error", "error": str}``
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
    status = _determine_status(now)

    # ------------------------------------------------------------------
    # Guard 2: DB write — INSERT … ON DUPLICATE KEY UPDATE
    #
    # On first recognition of the day (INSERT path):
    #   Sets time_in, status, confidence.
    #   time_out is left NULL (default from schema).
    #
    # On subsequent recognitions same day (DUPLICATE KEY → UPDATE path):
    #   Updates time_out to now and refreshes confidence.
    #   time_in and status are intentionally preserved from the first
    #   insert so status is always derived from actual arrival time.
    #
    # The VALUES(col) reference in the UPDATE clause uses the value that
    # was attempted for the INSERT — i.e. the current time / confidence.
    # ------------------------------------------------------------------
    sql = (
        "INSERT INTO attendance (user_id, date, time_in, status, confidence) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE "
        "time_out = VALUES(time_in), "
        "confidence = VALUES(confidence)"
    )
    params = (user_id, today, time_in_str, status, confidence)

    try:
        execute_query(sql, params=params, commit=True)
        logger.debug(
            "log_attendance: recorded user_id=%d date=%s time_in=%s status=%s conf=%.2f",
            user_id, today, time_in_str, status, confidence,
        )
    except MySQLError as exc:
        # Requirement 6.7: leave last_seen_dict unchanged on failure
        logger.error(
            "log_attendance: DB error for user_id=%d — %s", user_id, exc
        )
        return {"logged": False, "reason": "db_error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Requirement 6.5: update last_seen_dict only on success
    # ------------------------------------------------------------------
    last_seen_dict[user_id] = now

    return {"logged": True, "user_id": user_id, "status": status}
