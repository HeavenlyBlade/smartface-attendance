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
        "SELECT u.full_name, u.id_number, "
        "       a.time_in, a.time_out, a.status, a.confidence "
        "FROM attendance a "
        "JOIN users u ON a.user_id = u.id "
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
        + where_clause
    )

    count_sql = "SELECT COUNT(*) AS total " + join_clause
    count_row = execute_query(count_sql, params=tuple(params), fetchone=True)
    total: int = int(count_row["total"]) if count_row else 0
    pages: int = math.ceil(total / per_page) if total > 0 else 1

    data_sql = (
        "SELECT u.full_name, u.id_number, u.department, u.role, "
        "       a.date, a.time_in, a.time_out, a.status, a.confidence "
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
