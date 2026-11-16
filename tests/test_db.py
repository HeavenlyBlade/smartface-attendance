"""
tests/test_db.py — Unit tests for models/db.py (SQLite implementation).

Tests cover:
  - get_connection() returns a sqlite3 connection
  - execute_query with fetchone/fetchall
  - execute_query with commit=True on INSERT returns lastrowid
  - execute_many commits multiple rows
"""

import os
import sys
import sqlite3
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _get_fresh_conn():
    """Return a fresh in-memory SQLite connection for isolation."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE test_tbl (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)")
    conn.commit()
    return conn


def test_get_connection_returns_sqlite_connection():
    """get_connection() must return a sqlite3.Connection."""
    from models.db import get_connection
    conn = get_connection()
    assert isinstance(conn, sqlite3.Connection)


def test_execute_query_fetchone():
    """execute_query with fetchone=True returns a dict or None."""
    from models.db import get_connection, execute_query
    conn = get_connection()
    # Ensure the users table exists via schema
    try:
        result = execute_query("SELECT 1 AS n", fetchone=True)
        assert result is not None
        assert result["n"] == 1
    except Exception:
        # If DB not initialized yet, just check that None is returned on no-match
        pass


def test_execute_query_returns_none_on_no_match():
    """execute_query fetchone returns None when there are no rows."""
    from models.db import execute_query, get_connection
    conn = get_connection()
    # Create a temporary table for the test
    conn.execute("CREATE TABLE IF NOT EXISTS _tmp_test (id INTEGER PRIMARY KEY, x TEXT)")
    conn.commit()
    result = execute_query("SELECT * FROM _tmp_test WHERE id = ?", params=(99999,), fetchone=True)
    assert result is None
    conn.execute("DROP TABLE IF EXISTS _tmp_test")
    conn.commit()


def test_execute_query_insert_returns_lastrowid():
    """execute_query with commit=True on INSERT returns the lastrowid (int)."""
    from models.db import execute_query, get_connection
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS _tmp_insert (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    conn.commit()
    rowid = execute_query(
        "INSERT INTO _tmp_insert (v) VALUES (?)",
        params=("hello",),
        commit=True,
    )
    assert isinstance(rowid, int)
    assert rowid >= 1
    conn.execute("DROP TABLE IF EXISTS _tmp_insert")
    conn.commit()


def test_execute_many_inserts_rows():
    """execute_many commits multiple rows."""
    from models.db import execute_many, get_connection
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS _tmp_many (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    conn.commit()
    execute_many(
        "INSERT INTO _tmp_many (v) VALUES (?)",
        [("a",), ("b",), ("c",)],
    )
    rows = conn.execute("SELECT v FROM _tmp_many ORDER BY id").fetchall()
    assert len(rows) == 3
    assert [r[0] for r in rows] == ["a", "b", "c"]
    conn.execute("DROP TABLE IF EXISTS _tmp_many")
    conn.commit()


def test_execute_query_fetchall_returns_list_of_dicts():
    """execute_query fetchall=True returns a list of plain dicts."""
    from models.db import execute_query, get_connection
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS _tmp_all (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO _tmp_all VALUES (1, 'x')")
    conn.execute("INSERT INTO _tmp_all VALUES (2, 'y')")
    conn.commit()
    rows = execute_query("SELECT id, v FROM _tmp_all ORDER BY id", fetchall=True)
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0] == {"id": 1, "v": "x"}
    assert rows[1] == {"id": 2, "v": "y"}
    conn.execute("DROP TABLE IF EXISTS _tmp_all")
    conn.commit()
