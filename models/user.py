"""
models/user.py — User data-access wrapper for SmartFace

All functions return plain dicts (no ORM).  Every SQL statement uses
parameterized ? placeholders — never f-strings or string concatenation.
"""

import logging
import math

from models.db import execute_query

logger = logging.getLogger(__name__)

_UPDATABLE_FIELDS = {"full_name", "department", "role", "id_number", "email"}


def get_user_by_email(email: str) -> dict | None:
    try:
        return execute_query(
            "SELECT * FROM users WHERE email = ? LIMIT 1",
            params=(email,),
            fetchone=True,
        )
    except Exception as exc:
        logger.error("get_user_by_email(%s) failed: %s", email, exc)
        raise


def get_user_by_id(user_id: int) -> dict | None:
    try:
        return execute_query(
            "SELECT * FROM users WHERE id = ? LIMIT 1",
            params=(user_id,),
            fetchone=True,
        )
    except Exception as exc:
        logger.error("get_user_by_id(%s) failed: %s", user_id, exc)
        raise


def create_user(
    full_name: str,
    email: str,
    password_hash: str,
    role: str,
    id_number: str,
    department: str,
    consent_given: int = 0,
) -> int:
    sql = (
        "INSERT INTO users "
        "(full_name, email, password_hash, role, id_number, department, consent_given) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    params = (full_name, email, password_hash, role, id_number, department, consent_given)
    try:
        new_id = execute_query(sql, params=params, commit=True)
        logger.info("create_user: inserted user id=%s email=%s", new_id, email)
        return new_id
    except Exception as exc:
        logger.error("create_user(%s) failed: %s", email, exc)
        raise


def update_user(user_id: int, fields: dict) -> bool:
    safe = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    if not safe:
        logger.warning("update_user(%s): no valid fields provided — skipping", user_id)
        return False

    set_clause = ", ".join(f"{col} = ?" for col in safe)
    values = list(safe.values())
    values.append(user_id)

    sql = f"UPDATE users SET {set_clause} WHERE id = ?"
    try:
        execute_query(sql, params=tuple(values), commit=True)
        logger.info("update_user(%s): updated fields %s", user_id, list(safe))
        return True
    except Exception as exc:
        logger.error("update_user(%s) failed: %s", user_id, exc)
        raise


def deactivate_user(user_id: int) -> bool:
    try:
        execute_query(
            "UPDATE users SET is_active = 0 WHERE id = ?",
            params=(user_id,),
            commit=True,
        )
        logger.info("deactivate_user(%s): is_active set to 0", user_id)
        return True
    except Exception as exc:
        logger.error("deactivate_user(%s) failed: %s", user_id, exc)
        raise


def activate_user(user_id: int) -> bool:
    try:
        execute_query(
            "UPDATE users SET is_active = 1 WHERE id = ?",
            params=(user_id,),
            commit=True,
        )
        logger.info("activate_user(%s): is_active set to 1", user_id)
        return True
    except Exception as exc:
        logger.error("activate_user(%s) failed: %s", user_id, exc)
        raise


def list_users(page: int = 1, per_page: int = 25, search: str = "") -> dict:
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 25

    offset = (page - 1) * per_page

    try:
        where = ""
        params_count: tuple = ()
        params_data: tuple = ()
        if search:
            where = (
                "WHERE LOWER(full_name) LIKE LOWER(?) OR LOWER(email) LIKE LOWER(?) "
                "OR LOWER(id_number) LIKE LOWER(?) OR LOWER(department) LIKE LOWER(?)"
            )
            like = f"%{search}%"
            params_count = (like, like, like, like)
            params_data = (like, like, like, like)

        count_sql = "SELECT COUNT(*) AS total FROM users " + where
        count_row = execute_query(count_sql, params=params_count, fetchone=True)
        total: int = count_row["total"] if count_row else 0
        pages: int = max(1, math.ceil(total / per_page))

        data_sql = (
            "SELECT id, full_name, id_number, role, department, is_active, email, created_at "
            "FROM users " + where +
            " ORDER BY full_name ASC LIMIT ? OFFSET ?"
        )
        users = execute_query(
            data_sql,
            params=params_data + (per_page, offset),
            fetchall=True,
        )

        return {
            "users": users or [],
            "total": total,
            "pages": pages,
        }
    except Exception as exc:
        logger.error("list_users(page=%s, per_page=%s) failed: %s", page, per_page, exc)
        raise


def delete_user(user_id: int) -> bool:
    try:
        execute_query(
            "DELETE FROM users WHERE id = ?",
            params=(user_id,),
            commit=True,
        )
        logger.info("delete_user(%s): user and cascaded records removed", user_id)
        return True
    except Exception as exc:
        logger.error("delete_user(%s) failed: %s", user_id, exc)
        raise
