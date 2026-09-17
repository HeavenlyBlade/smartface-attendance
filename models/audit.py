"""
models/audit.py — Audit log data-access wrapper for SmartFace

Provides two public functions:
  - write_audit()  : INSERT a record into audit_logs; swallows all exceptions
                     so audit failures never crash the application.
  - list_audit()   : Paginated, reverse-chronological SELECT with optional
                     filters for action type and date range.

Action constants are defined at module level so callers import them by name
instead of using raw strings, reducing typo risk and making grep easy.

Usage:
    from models.audit import write_audit, list_audit, ACTION_LOGIN

    # Write an audit entry (fire-and-forget; never raises)
    write_audit(
        user_id=session['user_id'],
        action=ACTION_LOGIN,
        details="Successful login",
        ip_address=request.remote_addr,
    )

    # Paginated listing with optional filters
    result = list_audit(page=1, per_page=25, action_filter=ACTION_LOGIN,
                        start_date='2024-01-01', end_date='2024-12-31')
    entries = result['entries']   # list of dicts
    total   = result['total']     # int — total matching rows
    pages   = result['pages']     # int — total page count
"""

import logging
import math

from models.db import execute_query

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action constants
# Callers should import these rather than using raw string literals.
# ---------------------------------------------------------------------------

ACTION_LOGIN             = 'user_login'
ACTION_LOGOUT            = 'user_logout'
ACTION_ENROLL            = 'user_enrolled'
ACTION_MANUAL_OVERRIDE   = 'manual_attendance_override'
ACTION_DEACTIVATE        = 'user_deactivated'
ACTION_BIOMETRIC_DELETE  = 'biometric_data_deleted'

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_audit(
    user_id: int | None,
    action: str,
    details: str,
    ip_address: str,
) -> None:
    """
    Insert a single row into ``audit_logs``.

    This function is intentionally exception-safe: any database or
    serialization error is caught, logged at ERROR level, and then
    silently discarded.  Audit failures MUST NOT propagate to the caller
    or cause an HTTP 500 response — the main operation has already
    succeeded at the point ``write_audit`` is called.

    Parameters
    ----------
    user_id : int | None
        The ``users.id`` of the acting user.  Pass ``None`` for
        system-generated entries where no user is authenticated (e.g.,
        a failed login attempt before a session exists).
    action : str
        One of the ``ACTION_*`` constants defined in this module.
        Freeform strings are accepted but discouraged.
    details : str
        Human-readable description of what happened.  Keep concise —
        this is displayed verbatim in the audit log viewer.
    ip_address : str
        The ``request.remote_addr`` value from the Flask request context,
        or an empty string if not available.
    """
    sql = (
        "INSERT INTO audit_logs (user_id, action, details, ip_address) "
        "VALUES (%s, %s, %s, %s)"
    )
    try:
        execute_query(sql, params=(user_id, action, details, ip_address), commit=True)
        logger.debug(
            "audit written — user_id=%s action=%s ip=%s",
            user_id, action, ip_address,
        )
    except Exception as exc:  # pragma: no cover — intentionally broad catch
        # Log to the application error log; do NOT re-raise.
        # Requirement 11.3: audit write failures must never surface to the user.
        logger.error(
            "write_audit failed — user_id=%s action=%s details=%r ip=%s — %s",
            user_id, action, details, ip_address, exc,
        )


def list_audit(
    page: int = 1,
    per_page: int = 25,
    action_filter: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """
    Return a paginated, reverse-chronological slice of the audit log.

    Parameters
    ----------
    page : int
        1-based page number.  Values below 1 are clamped to 1.
    per_page : int
        Maximum rows per page.  Values below 1 are clamped to 1.
    action_filter : str | None
        If provided, only rows whose ``action`` column exactly matches
        this value are returned.  Use the ``ACTION_*`` constants.
    start_date : str | None
        Inclusive lower bound on ``timestamp``, in YYYY-MM-DD format.
        Rows with ``timestamp >= start_date 00:00:00`` are included.
    end_date : str | None
        Inclusive upper bound on ``timestamp``, in YYYY-MM-DD format.
        Rows with ``timestamp <= end_date 23:59:59`` are included.

    Returns
    -------
    dict
        ``{'entries': list[dict], 'total': int, 'pages': int}``

        Each entry dict has the keys returned by the ``audit_logs``
        table columns: ``id``, ``user_id``, ``action``, ``details``,
        ``ip_address``, ``timestamp``.

    Raises
    ------
    mysql.connector.Error
        Propagated from ``execute_query`` so the caller can handle DB
        unavailability (e.g., return 503).  Unlike ``write_audit``, this
        function does not swallow exceptions — the caller needs the data.
    """
    # ------------------------------------------------------------------
    # Sanitise pagination bounds
    # ------------------------------------------------------------------
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    offset = (page - 1) * per_page

    # ------------------------------------------------------------------
    # Build WHERE clause dynamically from optional filters.
    # All values go through %s parameters — no string interpolation.
    # ------------------------------------------------------------------
    conditions: list[str] = []
    params: list = []

    if action_filter is not None:
        conditions.append("action = %s")
        params.append(action_filter)

    if start_date is not None:
        # Include the full start day from midnight
        conditions.append("timestamp >= %s")
        params.append(f"{start_date} 00:00:00")

    if end_date is not None:
        # Include the full end day until the last second
        conditions.append("timestamp <= %s")
        params.append(f"{end_date} 23:59:59")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # ------------------------------------------------------------------
    # COUNT query — total matching rows for pagination metadata
    # ------------------------------------------------------------------
    count_sql = f"SELECT COUNT(*) AS total FROM audit_logs {where_clause}"
    count_row = execute_query(count_sql, params=tuple(params), fetchone=True)
    total: int = int(count_row["total"]) if count_row else 0
    pages: int = math.ceil(total / per_page) if total > 0 else 1

    # ------------------------------------------------------------------
    # Data query — paginated slice, newest first
    # ------------------------------------------------------------------
    data_sql = (
        f"SELECT id, user_id, action, details, ip_address, timestamp "
        f"FROM audit_logs "
        f"{where_clause} "
        f"ORDER BY timestamp DESC "
        f"LIMIT %s OFFSET %s"
    )
    data_params = tuple(params) + (per_page, offset)
    entries: list[dict] = execute_query(data_sql, params=data_params, fetchall=True) or []

    return {
        "entries": entries,
        "total": total,
        "pages": pages,
    }
