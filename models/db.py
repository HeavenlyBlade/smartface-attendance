"""
models/db.py — MySQL connection pool and query helpers for SmartFace

The pool is lazy-initialized: it is created on the first call to
get_connection(), not at import time.  This means importing this module
while MySQL is offline will not raise an error; the error surfaces only
when a query is actually attempted.

All public helpers enforce parameterized queries (%s placeholders).
Never pass raw SQL built with f-strings or string concatenation.

Usage:
    from models.db import get_connection, execute_query, execute_many

    # Simple SELECT (returns list of dicts)
    rows = execute_query("SELECT * FROM users WHERE email = %s",
                         params=(email,), fetchall=True)

    # INSERT / UPDATE / DELETE (returns lastrowid on INSERT, else None)
    new_id = execute_query(
        "INSERT INTO users (full_name, email) VALUES (%s, %s)",
        params=(name, email), commit=True
    )

    # Bulk INSERT
    execute_many(
        "INSERT INTO face_encodings (user_id, encoding, sample_no) VALUES (%s, %s, %s)",
        params_list=[(uid, blob, idx) for idx, blob in enumerate(blobs)]
    )
"""

import logging
import threading
from contextlib import contextmanager

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool

import config

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy pool initialisation
# ---------------------------------------------------------------------------

_pool: MySQLConnectionPool | None = None
_pool_lock = threading.Lock()

# Connection pool configuration
_POOL_NAME = "smartface_pool"
_POOL_SIZE = 5  # matches documented max of 5 concurrent connections


def _get_pool() -> MySQLConnectionPool:
    """
    Return the module-level connection pool, creating it on first call.

    Thread-safe: uses a lock so that two threads racing on startup both
    wait for the single pool to be created rather than creating two.

    Raises:
        mysql.connector.Error — if the pool cannot connect to the database.
    """
    global _pool

    # Fast path: pool already exists (avoids acquiring the lock on every call)
    if _pool is not None:
        return _pool

    with _pool_lock:
        # Double-checked locking: another thread may have initialised the
        # pool while we were waiting for the lock.
        if _pool is not None:
            return _pool

        logger.info(
            "Initialising MySQL connection pool '%s' (size=%d) → %s:%d/%s",
            _POOL_NAME,
            _POOL_SIZE,
            config.DB_HOST,
            config.DB_PORT,
            config.DB_NAME,
        )

        try:
            _pool = MySQLConnectionPool(
                pool_name=_POOL_NAME,
                pool_size=_POOL_SIZE,
                pool_reset_session=True,  # clean state between checkouts
                host=config.DB_HOST,
                port=config.DB_PORT,
                user=config.DB_USER,
                password=config.DB_PASS,
                database=config.DB_NAME,
                charset="utf8mb4",
                use_unicode=True,
                autocommit=False,  # explicit commit required for writes
                connection_timeout=10,
            )
        except MySQLError as exc:
            logger.error("Failed to create connection pool: %s", exc)
            raise

    return _pool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_connection():
    """
    Obtain a pooled connection from the pool.

    The caller is responsible for calling .close() to return it to the pool.
    Prefer the context-manager form via _managed_connection() for automatic
    cleanup, but this function is exposed for callers that need manual control
    (e.g., multi-statement transactions).

    Returns:
        mysql.connector.pooling.PooledMySQLConnection

    Raises:
        mysql.connector.Error — on pool exhaustion or DB unreachability.
    """
    try:
        return _get_pool().get_connection()
    except MySQLError as exc:
        logger.error("get_connection() failed: %s", exc)
        raise


@contextmanager
def _managed_connection():
    """
    Internal context manager that checks out a connection and guarantees
    it is returned to the pool (via .close()) even if an exception occurs.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def execute_query(
    sql: str,
    params: tuple = (),
    fetchone: bool = False,
    fetchall: bool = False,
    commit: bool = False,
):
    """
    Execute a single parameterized SQL statement.

    Parameters
    ----------
    sql : str
        SQL statement using %s placeholders — NEVER build SQL with
        f-strings or string concatenation.
    params : tuple
        Values substituted into the %s placeholders.
    fetchone : bool
        If True, return the first row as a dict (or None if no rows).
    fetchall : bool
        If True, return all rows as a list of dicts.
    commit : bool
        If True, call connection.commit() after executing.  Required for
        INSERT / UPDATE / DELETE statements.

    Returns
    -------
    list[dict] | dict | int | None
        - fetchall=True  → list of row dicts
        - fetchone=True  → single row dict or None
        - commit=True (INSERT) → lastrowid (int)
        - otherwise      → None

    Raises
    ------
    mysql.connector.Error
        Logged then re-raised so callers can decide how to handle failures.
    """
    with _managed_connection() as conn:
        # dictionary=True makes every row a plain dict keyed by column name
        cursor = conn.cursor(dictionary=True)
        try:
            logger.debug("execute_query: %s | params=%s", sql, params)
            cursor.execute(sql, params)

            if fetchall:
                return cursor.fetchall()

            if fetchone:
                return cursor.fetchone()

            if commit:
                conn.commit()
                # For INSERT statements return the auto-generated primary key
                return cursor.lastrowid

            return None

        except MySQLError as exc:
            logger.error("execute_query error — SQL: %s | params: %s | err: %s",
                         sql, params, exc)
            if commit:
                conn.rollback()
            raise
        finally:
            cursor.close()


def execute_many(sql: str, params_list: list[tuple]) -> None:
    """
    Execute a parameterized statement once per tuple in params_list using
    cursor.executemany().  Designed for bulk INSERTs (e.g., storing multiple
    facial encoding BLOBs in a single round-trip).

    Parameters
    ----------
    sql : str
        SQL statement using %s placeholders.
    params_list : list[tuple]
        Each tuple is one set of values.  An empty list is a no-op.

    Raises
    ------
    mysql.connector.Error
        Logged then re-raised; the transaction is rolled back on error.
    """
    if not params_list:
        logger.debug("execute_many called with empty params_list — skipping")
        return

    with _managed_connection() as conn:
        cursor = conn.cursor()
        try:
            logger.debug("execute_many: %s | %d rows", sql, len(params_list))
            cursor.executemany(sql, params_list)
            conn.commit()
        except MySQLError as exc:
            logger.error("execute_many error — SQL: %s | err: %s", sql, exc)
            conn.rollback()
            raise
        finally:
            cursor.close()
