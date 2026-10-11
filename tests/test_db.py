"""
tests/test_db.py — Unit tests for models/db.py connection pool helpers.

Tests cover:
  - When TESTING=true, _get_pool() uses TEST_DATABASE_URL path
  - Without TESTING env var, DATABASE_URL path is used
  - Both paths call ThreadedConnectionPool with the expected DSN

All tests mock psycopg2.pool.ThreadedConnectionPool so no real DB is needed.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _reset_pool():
    """Helper: force models.db to forget the cached pool between tests."""
    import models.db as db_module
    db_module._pool = None


# ---------------------------------------------------------------------------
# TESTING=true + TEST_DATABASE_URL → uses TEST_DATABASE_URL
# ---------------------------------------------------------------------------

def test_get_pool_uses_test_database_url_when_testing():
    """
    When TESTING=true and TEST_DATABASE_URL is set, _get_pool() must pass
    TEST_DATABASE_URL directly to ThreadedConnectionPool (not DATABASE_URL).
    """
    _reset_pool()

    test_dsn = "postgresql://test-user:test-pass@localhost:5432/test_db"
    env_overrides = {
        "TESTING": "true",
        "TEST_DATABASE_URL": test_dsn,
        "DATABASE_URL": "postgresql://prod-user:prod-pass@prod-host/prod_db",
    }

    mock_pool = MagicMock()

    with patch.dict(os.environ, env_overrides, clear=False), \
         patch("psycopg2.pool.ThreadedConnectionPool", return_value=mock_pool) as mock_tcp:
        from models.db import _get_pool
        result = _get_pool()

    # ThreadedConnectionPool must have been called with the test DSN
    mock_tcp.assert_called_once_with(1, 5, test_dsn)
    assert result is mock_pool

    _reset_pool()


# ---------------------------------------------------------------------------
# No TESTING env var → uses DATABASE_URL
# ---------------------------------------------------------------------------

def test_get_pool_uses_database_url_when_not_testing():
    """
    When TESTING is not set (or falsy), _get_pool() must pass DATABASE_URL
    to ThreadedConnectionPool, not TEST_DATABASE_URL.
    """
    _reset_pool()

    prod_dsn = "postgresql://prod-user:prod-pass@prod-host:5432/prod_db"
    # Remove TESTING / TEST_DATABASE_URL from the environment for this test
    env_overrides = {
        "DATABASE_URL": prod_dsn,
    }
    env_removes = ["TESTING", "TEST_DATABASE_URL"]

    mock_pool = MagicMock()

    # Build a clean env: set DATABASE_URL, unset TESTING + TEST_DATABASE_URL
    clean_env = {k: v for k, v in os.environ.items() if k not in env_removes}
    clean_env.update(env_overrides)

    with patch.dict(os.environ, clean_env, clear=True), \
         patch("psycopg2.pool.ThreadedConnectionPool", return_value=mock_pool) as mock_tcp:
        from models.db import _get_pool
        result = _get_pool()

    # ThreadedConnectionPool must have been called with the production DSN
    mock_tcp.assert_called_once_with(1, 5, prod_dsn)
    assert result is mock_pool

    _reset_pool()


# ---------------------------------------------------------------------------
# TESTING=true but no TEST_DATABASE_URL → falls back to DB_* config vars
# ---------------------------------------------------------------------------

def test_get_pool_falls_back_to_config_vars_when_no_test_url():
    """
    When TESTING=true but TEST_DATABASE_URL is absent, _get_pool() builds
    the DSN from individual DB_* config variables (the legacy path).
    ThreadedConnectionPool must be called with a DSN string (not None).
    """
    _reset_pool()

    # Remove DATABASE_URL and TEST_DATABASE_URL; provide DB_* vars
    env_removes = ["DATABASE_URL", "TEST_DATABASE_URL"]
    clean_env = {k: v for k, v in os.environ.items() if k not in env_removes}
    clean_env["TESTING"] = "true"
    clean_env["DB_HOST"] = "localhost"
    clean_env["DB_PORT"] = "5432"
    clean_env["DB_NAME"] = "smartface_test_db"
    clean_env["DB_USER"] = "postgres"
    clean_env["DB_PASS"] = "testpass"

    mock_pool = MagicMock()

    with patch.dict(os.environ, clean_env, clear=True), \
         patch("psycopg2.pool.ThreadedConnectionPool", return_value=mock_pool) as mock_tcp:
        from models.db import _get_pool
        result = _get_pool()

    # Pool must have been created with some DSN string
    mock_tcp.assert_called_once()
    dsn_arg = mock_tcp.call_args[0][2]  # positional arg #3 = dsn
    assert isinstance(dsn_arg, str)
    assert len(dsn_arg) > 0
    # DSN should not be empty and should be a valid PostgreSQL connection string
    # (when TEST_DATABASE_URL is not set, falls back to config.DB_* vars which
    # use the default DB_NAME from .env — we just verify a DSN was constructed)
    assert "host=" in dsn_arg or "postgresql" in dsn_arg

    _reset_pool()
