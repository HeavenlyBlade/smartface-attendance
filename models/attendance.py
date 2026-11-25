"""
models/attendance.py — Attendance data-access layer for SmartFace
All SQL uses ? parameterized placeholders.
"""

import logging
import math
from datetime import date as date_type

from models.db import execute_query

logger = logging.getLogger(__name__)


def get_today_records() -> list:
    today = date_type.today().isoformat()

    sql = (
        "SELECT u.full_name, u.id_number, u.department, "
        "       a.id AS attendance_id, a.time_in, a.time_out, a.status, a.confidence, "
        "       a.late_minutes, a.late_reason, a.late_remarks, a.scanner_id, a.is_excused, "
        "       s.name AS schedule_name "
        "FROM attendance a "
        "JOIN users u ON a.user_id = u.id "
        "LEFT JOIN schedules s ON a.schedule_id = s.id "
        "WHERE a.date = ? "
        "ORDER BY a.time_in ASC"
    )
    rows = execute_query(sql, params=(today,), fetchall=True) or []
    logger.debug("get_today_records: %d rows for date=%s", len(rows), today)
    return rows


def get_records(filters: dict) -> dict:
    page = max(1, int(filters.get("page", 1)))
    per_page = max(1, int(filters.get("per_page", 50)))
    offset = (page - 1) * per_page

    conditions: list = []
    params: list = []

    start_date = filters.get("start_date")
    if start_date:
        conditions.append("a.date >= ?")
        params.append(start_date)

    end_date = filters.get("end_date")
    if end_date:
        conditions.append("a.date <= ?")
        params.append(end_date)

    role = filters.get("role")
    if role:
        conditions.append("u.role = ?")
        params.append(role)

    department = filters.get("department")
    if department:
        conditions.append("u.department = ?")
        params.append(department)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    join_clause = (
        "FROM attendance a "
        "JOIN users u ON a.user_id = u.id "
        "LEFT JOIN schedules s ON a.schedule_id = s.id "
        + where_clause
    )

    count_sql = "SELECT COUNT(*) AS total " + join_clause
    count_row = execute_query(count_sql, params=tuple(params), fetchone=True)
    total: int = int(count_row["total"]) if count_row else 0
    pages: int = math.ceil(total / per_page) if total > 0 else 1

    data_sql = (
        "SELECT u.full_name, u.id_number, u.department, u.role, "
        "       a.id AS attendance_id, a.date, a.time_in, a.time_out, a.status, a.confidence, "
        "       a.late_minutes, a.late_reason, a.late_remarks, a.scanner_id, a.is_excused, "
        "       s.name AS schedule_name "
        + join_clause
        + " ORDER BY a.date DESC, a.time_in DESC "
        "LIMIT ? OFFSET ?"
    )
    data_params = tuple(params) + (per_page, offset)
    records = execute_query(data_sql, params=data_params, fetchall=True) or []

    logger.debug(
        "get_records: total=%d pages=%d page=%d per_page=%d",
        total, pages, page, per_page,
    )
    return {"records": records, "total": total, "pages": pages}


def get_lateness_records(filters: dict) -> dict:
    """
    Fetch comprehensive lateness report data with metrics on why and how
    students arrived late.
    """
    page = max(1, int(filters.get("page", 1)))
    per_page = max(1, int(filters.get("per_page", 25)))
    offset = (page - 1) * per_page

    conditions: list = ["a.status = 'late'"]
    params: list = []

    start_date = filters.get("start_date")
    if start_date:
        conditions.append("a.date >= ?")
        params.append(start_date)

    end_date = filters.get("end_date")
    if end_date:
        conditions.append("a.date <= ?")
        params.append(end_date)

    department = filters.get("department")
    if department:
        conditions.append("u.department = ?")
        params.append(department)

    search = (filters.get("search") or "").strip()
    if search:
        conditions.append("(u.full_name LIKE ? OR u.id_number LIKE ?)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param])

    is_excused = filters.get("is_excused")
    if is_excused is not None and str(is_excused).strip() != "":
        conditions.append("a.is_excused = ?")
        params.append(int(is_excused))

    where_clause = "WHERE " + " AND ".join(conditions)
    base_join = (
        "FROM attendance a "
        "JOIN users u ON a.user_id = u.id "
        "LEFT JOIN schedules s ON a.schedule_id = s.id "
        + where_clause
    )

    # 1. Total count
    count_sql = "SELECT COUNT(*) AS total " + base_join
    count_row = execute_query(count_sql, params=tuple(params), fetchone=True)
    total: int = int(count_row["total"]) if count_row else 0
    pages: int = math.ceil(total / per_page) if total > 0 else 1

    # 2. Paginated data
    data_sql = (
        "SELECT a.id AS attendance_id, a.user_id, a.date, a.time_in, a.time_out, "
        "       a.late_minutes, a.late_reason, a.late_remarks, a.scanner_id, a.is_excused, "
        "       u.full_name, u.id_number, u.department, u.role, "
        "       s.name AS schedule_name, s.start_time AS scheduled_start, "
        "       s.grace_period_mins "
        + base_join
        + " ORDER BY a.date DESC, a.time_in DESC "
        "LIMIT ? OFFSET ?"
    )
    records = execute_query(data_sql, params=tuple(params) + (per_page, offset), fetchall=True) or []

    # 3. Aggregates and statistical insights
    stats_sql = (
        "SELECT COUNT(*) AS total_late, "
        "       SUM(CASE WHEN a.is_excused = 1 THEN 1 ELSE 0 END) AS excused_count, "
        "       SUM(CASE WHEN a.is_excused = 0 OR a.is_excused IS NULL THEN 1 ELSE 0 END) AS unexcused_count, "
        "       AVG(COALESCE(a.late_minutes, 0)) AS avg_late_mins "
        + base_join
    )
    stats_row = execute_query(stats_sql, params=tuple(params), fetchone=True) or {}

    total_late = stats_row.get("total_late") or 0
    excused_count = stats_row.get("excused_count") or 0
    unexcused_count = stats_row.get("unexcused_count") or 0
    avg_late_mins = round(float(stats_row.get("avg_late_mins") or 0), 1)

    # 4. Top frequent late students
    top_students_sql = (
        "SELECT u.full_name, u.id_number, u.department, "
        "       COUNT(*) AS late_count, SUM(COALESCE(a.late_minutes, 0)) AS total_late_mins "
        + base_join
        + " GROUP BY a.user_id, u.full_name, u.id_number, u.department "
        "ORDER BY late_count DESC, total_late_mins DESC "
        "LIMIT 5"
    )
    top_students = execute_query(top_students_sql, params=tuple(params), fetchall=True) or []

    return {
        "records": [dict(r) for r in records],
        "total": total,
        "pages": pages,
        "summary": {
            "total_late": total_late,
            "excused_count": excused_count,
            "unexcused_count": unexcused_count,
            "avg_late_mins": avg_late_mins,
            "top_students": [dict(ts) for ts in top_students],
        },
    }


def update_late_details(
    attendance_id: int,
    reason: str,
    remarks: str,
    is_excused: int,
    admin_id: int,
) -> bool:
    """Update lateness explanation and excuse status for an attendance record."""
    sql = (
        "UPDATE attendance "
        "SET late_reason = ?, late_remarks = ?, is_excused = ?, marked_by = ? "
        "WHERE id = ?"
    )
    execute_query(sql, params=(reason.strip(), remarks.strip(), int(is_excused), admin_id, attendance_id), commit=True)
    logger.info("update_late_details: attendance_id=%d updated by admin_id=%d", attendance_id, admin_id)
    return True


def manual_override(
    user_id: int,
    date: str,
    admin_id: int,
    status: str = "manual",
) -> None:
    sql = (
        "INSERT INTO attendance (user_id, date, status, marked_by) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id, date) DO UPDATE SET "
        "status = EXCLUDED.status, "
        "marked_by = EXCLUDED.marked_by"
    )
    execute_query(sql, params=(user_id, date, status, admin_id), commit=True)
    logger.debug(
        "manual_override: user_id=%d date=%s status=%s admin_id=%d",
        user_id, date, status, admin_id,
    )
