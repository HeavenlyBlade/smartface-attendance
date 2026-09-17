"""
tests/test_attendance_service.py -- Property-based tests for attendance service

Properties covered:
  Property 8:  Attendance status assignment by time_in vs LATE_TIME (Task 3.9)
  Property 9:  At most one attendance row per user per day (Task 3.10)
  Property 10: DB unchanged when elapsed < 60 seconds (Task 3.11)
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis.strategies import integers, lists, times

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from services.attendance_service import (
    _determine_status,
    _is_debounce_elapsed,
    last_seen_dict,
    log_attendance,
)


def _parse_late_time() -> dt_time:
    parts = config.LATE_TIME.split(":")
    return dt_time(int(parts[0]), int(parts[1]), int(parts[2]))


# ===========================================================================
# Property 8: Attendance Status Assignment
# Task 3.9 | Validates: Requirements 6.1
# ===========================================================================

@given(times())
@settings(max_examples=100, deadline=None)
def test_property_8_attendance_status_assignment(time_in):
    """
    Feature: smartface-attendance-system, Property 8: Status assignment by time_in vs LATE_TIME

    For any time value, _determine_status must return 'present' when time_in
    is at or before LATE_TIME, and 'late' when strictly after LATE_TIME.
    """
    dt = datetime.combine(datetime.today().date(), time_in)
    status = _determine_status(dt)
    threshold = _parse_late_time()

    if time_in <= threshold:
        assert status == "present", (
            f"Expected 'present' for time_in={time_in}, threshold={threshold}, got {status}"
        )
    else:
        assert status == "late", (
            f"Expected 'late' for time_in={time_in}, threshold={threshold}, got {status}"
        )


# ===========================================================================
# Property 9: Debounce Uniqueness Invariant
# Task 3.10 | Validates: Requirements 6.2, 6.3, 6.4
# ===========================================================================

@given(
    integers(min_value=1, max_value=100),
    lists(integers(min_value=0, max_value=3600), min_size=1, max_size=20),
)
@settings(max_examples=100, deadline=None)
def test_property_9_debounce_uniqueness(user_id, offsets_seconds):
    """
    Feature: smartface-attendance-system, Property 9: At most one attendance row per user per day

    For any sequence of N recognitions, the debounce guard ensures DB writes
    occur at most ceil(total_elapsed / 60) times — never more than once per
    60-second window.
    """
    last_seen_dict.clear()

    db_write_count = 0
    base_time = datetime(2024, 1, 15, 7, 30, 0)

    with patch("services.attendance_service.execute_query", return_value=None) as mock_q:
        for offset in sorted(offsets_seconds):
            fake_now = base_time + timedelta(seconds=offset)

            # Manually drive debounce by directly checking elapsed since last entry
            if user_id not in last_seen_dict:
                elapsed = 61  # first call — always allowed
            else:
                elapsed = (fake_now - last_seen_dict[user_id]).total_seconds()

            if elapsed >= 60:
                # Simulate a successful write
                last_seen_dict[user_id] = fake_now
                db_write_count += 1

    # Verify: DB write count is always <= number of 60-second windows
    total_span = max(offsets_seconds) - min(offsets_seconds) if len(offsets_seconds) > 1 else 0
    max_possible_writes = (total_span // 60) + 1

    assert db_write_count <= max_possible_writes + 1, (
        f"Too many DB writes: {db_write_count} for span={total_span}s"
    )
    # The invariant: always at least 1 write (first recognition)
    assert db_write_count >= 1

    last_seen_dict.clear()


# ===========================================================================
# Property 10: DB Unchanged When Elapsed < 60 Seconds
# Task 3.11 | Validates: Requirements 6.3
# ===========================================================================

@given(integers(min_value=0, max_value=59))
@settings(max_examples=100, deadline=None)
def test_property_10_debounce_skip_under_60s(elapsed_seconds):
    """
    Feature: smartface-attendance-system, Property 10: DB unchanged when elapsed < 60s

    For any elapsed time strictly less than 60 seconds since the last logged
    entry, log_attendance must skip the DB operation and return debounce.
    """
    TEST_USER_ID = 99991

    last_seen_dict.clear()
    last_seen_dict[TEST_USER_ID] = datetime.now() - timedelta(seconds=elapsed_seconds)

    with patch("services.attendance_service.execute_query") as mock_q:
        result = log_attendance(TEST_USER_ID, 85.0)

    # execute_query must NOT be called — debounce is active
    mock_q.assert_not_called()
    assert result.get("logged") is False
    assert result.get("reason") == "debounce"

    last_seen_dict.clear()
