"""
models/audit.py — Audit log data-access wrapper for SmartFace
All SQL uses ? parameterized placeholders.
"""

import logging
import math

from models.db import execute_query

logger = logging.getLogger(__name__)

ACTION_LOGIN             = 'user_login'
ACTION_LOGOUT            = 'user_logout'
ACTION_ENROLL            = 'user_enrolled'
ACTION_MANUAL_OVERRIDE   = 'manual_attendance_override'
ACTION_DEACTIVATE        = 'user_deactivated'
ACTION_BIOMETRIC_DELETE  = 'biometric_data_deleted'
ACTION_USER_DELETED      = 'user_deleted'


def write_audit(
    user_id: int | None,
    action: str,
    details: str,
    ip_address: str,
) -> None:
    sql = (
        "INSERT INTO audit_logs (user_id, action, details, ip_address) "
        "VALUES (?, ?, ?, ?)"
    )
    try:
        execute_query(sql, params=(user_id, action, details, ip_address), commit=True)
        logger.debug(
            "audit written — user_id=%s action=%s ip=%s",
            user_id, action, ip_address,
        )
    except Exception as exc:
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
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    offset = (page - 1) * per_page

    conditions: list = []
    params: list = []

    if action_filter is not None:
        conditions.append("action = ?")
        params.append(action_filter)

    if start_date is not None:
        conditions.append("timestamp >= ?")
        params.append(f"{start_date} 00:00:00")

    if end_date is not None:
        conditions.append("timestamp <= ?")
        params.append(f"{end_date} 23:59:59")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = f"SELECT COUNT(*) AS total FROM audit_logs {where_clause}"
    count_row = execute_query(count_sql, params=tuple(params), fetchone=True)
    total: int = int(count_row["total"]) if count_row else 0
    pages: int = math.ceil(total / per_page) if total > 0 else 1

    data_sql = (
        f"SELECT id, user_id, action, details, ip_address, timestamp "
        f"FROM audit_logs "
        f"{where_clause} "
        f"ORDER BY timestamp DESC "
        f"LIMIT ? OFFSET ?"
    )
    data_params = tuple(params) + (per_page, offset)
    entries = execute_query(data_sql, params=data_params, fetchall=True) or []

    return {
        "entries": entries,
        "total": total,
        "pages": pages,
    }
