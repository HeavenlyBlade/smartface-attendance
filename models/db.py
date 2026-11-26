"""
models/db.py — SQLite connection helpers for SmartFace

Each thread gets its own connection via threading.local().
Rows are returned as plain dicts (sqlite3.Row row_factory).
"""
import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB path: %APPDATA%\SmartFace\smartface.db  (or ~/SmartFace/ on non-Windows)
# Fallback to project database directory if APPDATA is not writable.
# ---------------------------------------------------------------------------
def _resolve_db_path() -> str:
    custom = os.environ.get("DATABASE_PATH") or os.environ.get("SMARTFACE_DB_PATH")
    if custom:
        os.makedirs(os.path.dirname(os.path.abspath(custom)), exist_ok=True)
        return os.path.abspath(custom)

    appdata_dir = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "SmartFace",
    )
    try:
        os.makedirs(appdata_dir, exist_ok=True)
        test_file = os.path.join(appdata_dir, ".test_write")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return os.path.join(appdata_dir, "smartface.db")
    except Exception:
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        fallback_dir = os.path.join(base_dir, "database")
        os.makedirs(fallback_dir, exist_ok=True)
        return os.path.join(fallback_dir, "smartface.db")

_DB_PATH = _resolve_db_path()

# Thread-local storage for per-thread connections
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Return (or create) the sqlite3 connection for the current thread."""
    if not getattr(_local, "conn", None):
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
    return _local.conn


def execute_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """
    Execute a single SQL statement.

    Parameters
    ----------
    sql        : str   — SQL statement with ? placeholders
    params     : tuple — bind parameters
    fetchone   : bool  — return one dict or None
    fetchall   : bool  — return list of dicts
    commit     : bool  — commit after execute; on INSERT returns lastrowid
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        is_insert = sql.strip().upper().startswith("INSERT")
        cur.execute(sql, () if params is None else params)

        if fetchall:
            rows = cur.fetchall()
            return [dict(r) for r in rows]

        if fetchone:
            row = cur.fetchone()
            return dict(row) if row else None

        if commit:
            conn.commit()
            if is_insert and not fetchone and not fetchall:
                return cur.lastrowid
            return None

        return None

    except Exception as exc:
        logger.error("execute_query error: %s | sql: %.120s", exc, sql)
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        cur.close()


def execute_many(sql, params_list):
    """Execute a parameterized statement for each row in params_list, then commit."""
    if not params_list:
        return
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.executemany(sql, params_list)
        conn.commit()
    except Exception as exc:
        logger.error("execute_many error: %s", exc)
        conn.rollback()
        raise
    finally:
        cur.close()
