"""
tests/test_auth_lockout.py — Unit tests for server-side login lockout logic.

Tests cover:
  - Failed logins increment login_attempts in DB
  - Locked-out user is rejected before password check
  - Successful login resets login_attempts to 0
  - _lockout_seconds helper: correct progression at each attempt count
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# _lockout_seconds helper tests
# ---------------------------------------------------------------------------

def test_lockout_seconds_zero_attempts():
    """0 attempts → no lockout (0 seconds)."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(0) == 0


def test_lockout_seconds_one_attempt():
    """1 attempt → no lockout (0 seconds)."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(1) == 0


def test_lockout_seconds_two_attempts():
    """2 attempts → no lockout (0 seconds)."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(2) == 0


def test_lockout_seconds_three_attempts():
    """3 attempts → 30-second lockout."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(3) == 30


def test_lockout_seconds_four_attempts():
    """4 attempts → 40-second lockout (30 + 1×10)."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(4) == 40


def test_lockout_seconds_five_attempts():
    """5 attempts → 50-second lockout (30 + 2×10)."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(5) == 50


def test_lockout_seconds_ten_attempts():
    """10 attempts → 100-second lockout (30 + 7×10)."""
    from routes.auth import _lockout_seconds
    assert _lockout_seconds(10) == 100


# ---------------------------------------------------------------------------
# Failed login increments DB counter
# ---------------------------------------------------------------------------

def test_failed_login_increments_login_attempts(test_app):
    """
    A failed login for an existing user calls execute_query with an UPDATE
    that increments login_attempts. Verifies the DB write is triggered.
    """
    from werkzeug.security import generate_password_hash

    fake_user = {
        "id": 1,
        "email": "test@example.com",
        "password_hash": generate_password_hash("correct-password"),
        "is_active": True,
        "role": "admin",
        "full_name": "Test User",
        "login_attempts": 0,
        "lockout_until": None,
    }

    with patch("routes.auth.get_user_by_email", return_value=fake_user) as mock_get, \
         patch("routes.auth.execute_query") as mock_exec:

        response = test_app.post(
            "/login",
            data={"email": "test@example.com", "password": "wrong-password"},
            follow_redirects=False,
        )

    # Should be 401 (invalid credentials)
    assert response.status_code == 401

    # execute_query must have been called to increment login_attempts
    mock_exec.assert_called_once()
    call_args = mock_exec.call_args
    sql = call_args[0][0] if call_args[0] else call_args[1].get("sql", "")
    # The UPDATE must mention login_attempts
    assert "login_attempts" in sql.lower()
    assert call_args[1].get("commit") is True


# ---------------------------------------------------------------------------
# Locked-out user is rejected before password check
# ---------------------------------------------------------------------------

def test_locked_out_user_rejected_without_password_check(test_app):
    """
    When lockout_until is in the future, the login endpoint returns 429
    before ever calling check_password_hash.
    """
    future = datetime.now() + timedelta(seconds=60)

    fake_user = {
        "id": 2,
        "email": "locked@example.com",
        "password_hash": "irrelevant",
        "is_active": True,
        "role": "admin",
        "full_name": "Locked User",
        "login_attempts": 5,
        "lockout_until": future,
    }

    with patch("routes.auth.get_user_by_email", return_value=fake_user), \
         patch("routes.auth.execute_query") as mock_exec, \
         patch("routes.auth.check_password_hash") as mock_check:

        response = test_app.post(
            "/login",
            data={"email": "locked@example.com", "password": "any-password"},
            follow_redirects=False,
        )

    # 429 = Too Many Requests (lockout active)
    assert response.status_code == 429

    # Password must NOT have been checked — locked-out path short-circuits
    mock_check.assert_not_called()

    # execute_query must NOT be called (no increment during lockout)
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# Successful login resets login_attempts = 0
# ---------------------------------------------------------------------------

def test_successful_login_resets_login_attempts(test_app):
    """
    A successful login calls execute_query with an UPDATE that sets
    login_attempts = 0 and lockout_until = NULL.
    """
    from werkzeug.security import generate_password_hash

    fake_user = {
        "id": 3,
        "email": "good@example.com",
        "password_hash": generate_password_hash("correct-password"),
        "is_active": True,
        "role": "admin",
        "full_name": "Good User",
        "login_attempts": 2,
        "lockout_until": None,
    }

    with patch("routes.auth.get_user_by_email", return_value=fake_user), \
         patch("routes.auth.execute_query") as mock_exec, \
         patch("routes.auth.write_audit"):

        response = test_app.post(
            "/login",
            data={"email": "good@example.com", "password": "correct-password"},
            follow_redirects=False,
        )

    # Successful login redirects (302)
    assert response.status_code == 302

    # The reset UPDATE must have been called
    assert mock_exec.call_count >= 1
    # Find the reset call — it sets login_attempts = 0
    reset_calls = [
        c for c in mock_exec.call_args_list
        if "login_attempts = 0" in (c[0][0] if c[0] else "")
    ]
    assert len(reset_calls) == 1, (
        f"Expected exactly one reset-login_attempts call, got {len(reset_calls)}"
    )
    reset_call = reset_calls[0]
    assert reset_call[1].get("commit") is True
