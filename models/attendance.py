"""
models/attendance.py — Attendance data-access layer for SmartFace

Provides three public functions:

  get_today_records()
      SELECT attendance joined with users for the current calendar date.
      Returns a list of dicts keyed by: full_name, id_number, time_in,
      time_out, status, confidence.
      Used by GET /api/live-feed (Requirement 7.3, 7.4).

  get_records(filters: dict)
      Paginated, filtered query spanning any date range.  Accepts optional
      keys in filters: start_date, end_date, role, department, page,
      per_page.  Returns {"records": [...], "total": int, "pages": int}.
      Used by GET /reports (Requirement 8.1, 8.2).

  manual_override(user_id, date, admin_id, status='manual')
      INSERT attendance row or UPDATE existing row, forcing status='manual'
      and marked_by=admin_id.  Satisfies the ON DUPLICATE KEY pattern
      required by Requirement 9.1.

All queries use %s parameterized placeholders.  No f-string or string
concatenation is used to build SQL WHERE clauses — only the condition
strings themselves (plain SQL keywords) are assembled; all *values* are
bound via params tuples.
"""

import logging
import math
from datetime import date as date_type

from models.db import execute_query

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_today_records() -> list[dict]:
    """
    Return all attendance records for today joined with user details.

    Returns
    -------
    list[dict]
        Each dict contains:
          - full_name   (str)
          - id_number   (str)
          - time_in     (str | None)   — HH:MM:SS or None if absent
          - time_out    (str | None)   — HH:MM:SS or None
          - status      (str | None)   — 'present', 'late', 'manual', or None
          - confidence  (float | None) — 0.00–100.00 or None

    Raises
    ------
    mysql.connector.Error
        Propagated so the caller (live-feed route) can return 503.
    """
    today = date_type.today().isoformat()   # YYYY-MM-DD string

    sql = (
        "SELECT u.full_name, u.id_number, "
        "       a.time_in, a.time_out, a.status, a.confidence "
        "FROM attendance a "
        "JOIN users u ON a.user_id = u.id "
        "WHERE a.date = %s "
        "ORDER BY a.time_in ASC"
    )
    rows: list[dict] = execute_query(sql, params=(today,), fetchall=True) or []
    logger.debug("get_today_records: %d rows for date=%s", len(rows), today)
    return rows


def get_records(filters: dict) -> dict:
    """
    Return a paginated, filtered slice of the attendance log.

    Accepted filter keys (all optional):
      start_date  (str)  — YYYY-MM-DD inclusive lower bound on attendance.date
      end_date    (str)  — YYYY-MM-DD inclusive upper bound
      role        (str)  — exact match on users.role
      department  (str)  — exact match on users.department
      page        (int)  — 1-based page number (default: 1)
      per_page    (int)  — rows per page (default: 50, max enforced by caller)

    Returns
    -------
    dict
        {"records": list[dict], "total": int, "pages": int}

        Each record dict includes:
          full_name, id_number, department, role,
          date, time_in, time_out, status, confidence

    Raises
    ------
    mysql.connector.Error
        Propagated so the route layer can return 503.
    """
    # ------------------------------------------------------------------
    # Pagination defaults and bounds
    # ------------------------------------------------------------------
    page = max(1, int(filters.get("page", 1)))
    per_page = max(1, int(filters.get("per_page", 50)))
    offset = (page - 1) * per_page

    # ------------------------------------------------------------------
    # Dynamic WHERE clause — values always bound as params, never inlined
    # ------------------------------------------------------------------
    conditions: list[str] = []
    params: list = []

    start_date = filters.get("start_date")
    if start_date:
        conditions.append("a.date >= %s")
        params.append(start_date)

    end_date = filters.get("end_date")
    if end_date:
        conditions.append("a.date <= %s")
        params.append(end_date)

    role = filters.get("role")
    if role:
        conditions.append("u.role = %s")
        params.append(role)

    department = filters.get("department")
    if department:
        conditions.append("u.department = %s")
        params.append(department)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    join_clause = (
        "FROM attendance a "
        "JOIN users u ON a.user_id = u.id "
        + where_clause
    )

    # ------------------------------------------------------------------
    # COUNT — total matching rows for pagination metadata
    # ------------------------------------------------------------------
    count_sql = "SELECT COUNT(*) AS total " + join_clause
    count_row = execute_query(count_sql, params=tuple(params), fetchone=True)
    total: int = int(count_row["total"]) if count_row else 0
    pages: int = math.ceil(total / per_page) if total > 0 else 1

    # ------------------------------------------------------------------
    # Data query — paginated, ordered by date desc then time_in desc
    # ------------------------------------------------------------------
    data_sql = (
        "SELECT u.full_name, u.id_number, u.department, u.role, "
        "       a.date, a.time_in, a.time_out, a.status, a.confidence "
        + join_clause
        + " ORDER BY a.date DESC, a.time_in DESC "
        "LIMIT %s OFFSET %s"
    )
    data_params = tuple(params) + (per_page, offset)
    records: list[dict] = (
        execute_query(data_sql, params=data_params, fetchall=True) or []
    )

    logger.debug(
        "get_records: total=%d pages=%d page=%d per_page=%d",
        total, pages, page, per_page,
    )
    return {"records": records, "total": total, "pages": pages}


def manual_override(
    user_id: int,
    date: str,
    admin_id: int,
    status: str = "manual",
) -> None:
    """
    Insert or update an attendance row, forcing status to 'manual'.

    Uses INSERT … ON DUPLICATE KEY UPDATE to respect the unique constraint
    ``uniq_user_day (user_id, date)`` at the DB level (Requirement 9.1).

    On INSERT (no prior row):  creates a full row with status='manual',
      time_in=NULL (not a recognition event), marked_by=admin_id.
    On UPDATE (row already exists): overwrites status with 'manual' and
      sets marked_by to admin_id; time_in / time_out are preserved.

    Parameters
    ----------
    user_id  : int   — target student's users.id
    date     : str   — target date as YYYY-MM-DD string
    admin_id : int   — acting Administrator's users.id (marked_by field)
    status   : str   — defaults to 'manual'; callers may pass other values
                       if an extended status vocabulary is introduced later.

    Raises
    ------
    mysql.connector.Error
        Propagated so the override route can roll back and return an error.
    """
    sql = (
        "INSERT INTO attendance (user_id, date, status, marked_by) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_id, date) DO UPDATE SET "
        "status = EXCLUDED.status, "
        "marked_by = EXCLUDED.marked_by"
    )
    execute_query(sql, params=(user_id, date, status, admin_id), commit=True)
    logger.debug(
        "manual_override: user_id=%d date=%s status=%s admin_id=%d",
        user_id, date, status, admin_id,
    )
