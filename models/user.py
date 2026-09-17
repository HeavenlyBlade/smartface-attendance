"""
models/user.py — User data-access wrapper for SmartFace

All functions return plain dicts (no ORM).  Every SQL statement uses
parameterized %s placeholders — never f-strings or string concatenation.

Usage:
    from models.user import get_user_by_email, create_user, list_users, ...

Public API
----------
get_user_by_email(email)            → dict | None
get_user_by_id(user_id)             → dict | None
create_user(...)                    → int  (new user id)
update_user(user_id, fields)        → bool
deactivate_user(user_id)            → bool
activate_user(user_id)              → bool
list_users(page, per_page)          → {'users': [...], 'total': int, 'pages': int}
delete_user(user_id)                → bool
"""

import logging
import math

from mysql.connector import Error as MySQLError

from models.db import execute_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed field names for update_user() — prevents SQL injection via
# untrusted field names submitted from the front-end.
# ---------------------------------------------------------------------------
_UPDATABLE_FIELDS = {"full_name", "department", "role", "id_number", "email"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_user_by_email(email: str) -> dict | None:
    """
    Return the user row whose email matches *email*, or None if not found.

    Parameters
    ----------
    email : str
        The email address to look up (case-insensitive on most MySQL collations).

    Returns
    -------
    dict | None
        Row as a plain dict with all users columns, or None.
    """
    try:
        return execute_query(
            "SELECT * FROM users WHERE email = %s LIMIT 1",
            params=(email,),
            fetchone=True,
        )
    except MySQLError as exc:
        logger.error("get_user_by_email(%s) failed: %s", email, exc)
        raise


def get_user_by_id(user_id: int) -> dict | None:
    """
    Return the user row with the given primary key, or None if not found.

    Parameters
    ----------
    user_id : int
        Primary key of the users table.

    Returns
    -------
    dict | None
    """
    try:
        return execute_query(
            "SELECT * FROM users WHERE id = %s LIMIT 1",
            params=(user_id,),
            fetchone=True,
        )
    except MySQLError as exc:
        logger.error("get_user_by_id(%s) failed: %s", user_id, exc)
        raise


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_user(
    full_name: str,
    email: str,
    password_hash: str,
    role: str,
    id_number: str,
    department: str,
    consent_given: int = 0,
) -> int:
    """
    Insert a new user row and return the auto-generated primary key.

    Parameters
    ----------
    full_name : str
    email : str
    password_hash : str
        Pre-hashed password (use werkzeug.security.generate_password_hash).
    role : str
        One of 'admin', 'faculty', 'student'.
    id_number : str
        Institutional ID; must be unique in the users table.
    department : str
    consent_given : int
        0 (default) or 1.  Must be 1 before any face_encodings row is
        created (RA 10173 compliance — enforced by the enrollment route).

    Returns
    -------
    int
        The lastrowid of the new users row.

    Raises
    ------
    mysql.connector.Error
        On duplicate email / id_number or other DB error.
    """
    sql = (
        "INSERT INTO users "
        "(full_name, email, password_hash, role, id_number, department, consent_given) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    params = (full_name, email, password_hash, role, id_number, department, consent_given)
    try:
        new_id = execute_query(sql, params=params, commit=True)
        logger.info("create_user: inserted user id=%s email=%s", new_id, email)
        return new_id
    except MySQLError as exc:
        logger.error("create_user(%s) failed: %s", email, exc)
        raise


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def update_user(user_id: int, fields: dict) -> bool:
    """
    Update a subset of the user's profile fields.

    Only keys listed in _UPDATABLE_FIELDS are accepted.  Any other key is
    silently ignored, which prevents callers from overwriting password_hash,
    consent_given, or created_at via this helper.

    Parameters
    ----------
    user_id : int
    fields : dict
        Mapping of column name → new value.  Example:
        {'full_name': 'Jane Doe', 'department': 'CS'}

    Returns
    -------
    bool
        True if at least one row was affected, False if the user does not
        exist or no valid fields were provided.

    Raises
    ------
    mysql.connector.Error
    """
    # Filter to the safe whitelist
    safe = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}
    if not safe:
        logger.warning("update_user(%s): no valid fields provided — skipping", user_id)
        return False

    # Build SET clause dynamically from the safe subset
    # Column names come from the whitelist above, not from user input, so
    # they are safe to interpolate into the SQL string as identifiers.
    set_clause = ", ".join(f"{col} = %s" for col in safe)
    values = list(safe.values())
    values.append(user_id)

    sql = f"UPDATE users SET {set_clause} WHERE id = %s"
    try:
        execute_query(sql, params=tuple(values), commit=True)
        logger.info("update_user(%s): updated fields %s", user_id, list(safe))
        return True
    except MySQLError as exc:
        logger.error("update_user(%s) failed: %s", user_id, exc)
        raise


# ---------------------------------------------------------------------------
# Activation / deactivation
# ---------------------------------------------------------------------------


def deactivate_user(user_id: int) -> bool:
    """
    Set is_active = 0 for the given user.

    Note: the caller (route handler) is responsible for:
    - Rejecting self-deactivation (Requirement 10.5).
    - Writing an audit_logs entry (Requirement 10.3).
    - Invalidating any active session for this user.

    Parameters
    ----------
    user_id : int

    Returns
    -------
    bool
        True on success.

    Raises
    ------
    mysql.connector.Error
    """
    try:
        execute_query(
            "UPDATE users SET is_active = 0 WHERE id = %s",
            params=(user_id,),
            commit=True,
        )
        logger.info("deactivate_user(%s): is_active set to 0", user_id)
        return True
    except MySQLError as exc:
        logger.error("deactivate_user(%s) failed: %s", user_id, exc)
        raise


def activate_user(user_id: int) -> bool:
    """
    Set is_active = 1 for the given user (re-enable a deactivated account).

    Parameters
    ----------
    user_id : int

    Returns
    -------
    bool
        True on success.

    Raises
    ------
    mysql.connector.Error
    """
    try:
        execute_query(
            "UPDATE users SET is_active = 1 WHERE id = %s",
            params=(user_id,),
            commit=True,
        )
        logger.info("activate_user(%s): is_active set to 1", user_id)
        return True
    except MySQLError as exc:
        logger.error("activate_user(%s) failed: %s", user_id, exc)
        raise


# ---------------------------------------------------------------------------
# Paginated list
# ---------------------------------------------------------------------------


def list_users(page: int = 1, per_page: int = 25) -> dict:
    """
    Return a page of users together with pagination metadata.

    Parameters
    ----------
    page : int
        1-indexed page number.  Clamped to 1 if below 1.
    per_page : int
        Number of rows per page (default 25, max enforced by caller).

    Returns
    -------
    dict
        {
            'users'  : list[dict],  # rows for the requested page
            'total'  : int,         # total row count across all pages
            'pages'  : int,         # total number of pages
        }

    Raises
    ------
    mysql.connector.Error
    """
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 25

    offset = (page - 1) * per_page

    try:
        # Total count — needed to calculate page metadata
        count_row = execute_query(
            "SELECT COUNT(*) AS total FROM users",
            fetchone=True,
        )
        total: int = count_row["total"] if count_row else 0
        pages: int = max(1, math.ceil(total / per_page))

        # Retrieve columns needed by the user management UI (Requirement 10.1)
        users = execute_query(
            "SELECT id, full_name, id_number, role, department, is_active, email, created_at "
            "FROM users "
            "ORDER BY full_name ASC "
            "LIMIT %s OFFSET %s",
            params=(per_page, offset),
            fetchall=True,
        )

        return {
            "users": users or [],
            "total": total,
            "pages": pages,
        }
    except MySQLError as exc:
        logger.error("list_users(page=%s, per_page=%s) failed: %s", page, per_page, exc)
        raise


# ---------------------------------------------------------------------------
# Hard delete
# ---------------------------------------------------------------------------


def delete_user(user_id: int) -> bool:
    """
    Permanently delete a user row.

    Because the schema defines ON DELETE CASCADE on face_encodings and
    attendance foreign keys, deleting the users row automatically removes
    all related encoding BLOBs and attendance records at the DB level.

    The caller is responsible for:
    - Deleting raw JPEG files in uploads/face_samples/ for this user.
    - Calling reload_known_faces() to update the in-memory cache.
    - Writing an audit_logs entry.
    (Requirement 10.4)

    Parameters
    ----------
    user_id : int

    Returns
    -------
    bool
        True on success.

    Raises
    ------
    mysql.connector.Error
    """
    try:
        execute_query(
            "DELETE FROM users WHERE id = %s",
            params=(user_id,),
            commit=True,
        )
        logger.info("delete_user(%s): user and cascaded records removed", user_id)
        return True
    except MySQLError as exc:
        logger.error("delete_user(%s) failed: %s", user_id, exc)
        raise
