"""
models/db.py - PostgreSQL connection helpers for SmartFace (psycopg2)
"""
import logging, os, threading
import psycopg2, psycopg2.extras, psycopg2.pool
from contextlib import contextmanager

logger = logging.getLogger(__name__)
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            import config
            dsn = (f"host={config.DB_HOST} port={config.DB_PORT} "
                   f"dbname={config.DB_NAME} user={config.DB_USER} "
                   f"password={config.DB_PASS} sslmode=require")
        logger.info("Initialising PostgreSQL connection pool")
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, dsn)
    return _pool


def get_connection():
    return _get_pool().getconn()


def release_connection(conn):
    # Always rollback before returning to pool to clear any open transaction
    try:
        conn.rollback()
    except Exception:
        pass
    _get_pool().putconn(conn)


@contextmanager
def _managed_connection():
    conn = get_connection()
    try:
        yield conn
    finally:
        release_connection(conn)


def execute_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    with _managed_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            is_insert = sql.strip().upper().startswith("INSERT")

            # For INSERT with commit, append RETURNING id to get the new PK
            exec_sql = sql
            if commit and is_insert and "RETURNING" not in sql.upper():
                exec_sql = sql.rstrip().rstrip(";") + " RETURNING id"

            cur.execute(exec_sql, params)

            if fetchall:
                rows = cur.fetchall()
                conn.rollback()  # end transaction cleanly
                return [dict(r) for r in rows]

            if fetchone:
                row = cur.fetchone()
                conn.rollback()  # end transaction cleanly
                return dict(row) if row else None

            if commit:
                if is_insert and "RETURNING" in exec_sql.upper():
                    row = cur.fetchone()  # fetch BEFORE commit
                    conn.commit()
                    return row["id"] if row else None
                conn.commit()
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
    if not params_list:
        return
    with _managed_connection() as conn:
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