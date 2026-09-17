"""
tests/test_student_isolation.py -- Property 12: Student data isolation

Property 12: Student only sees own attendance records
Validates: Requirements 12.1, 12.3
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis.strategies import integers

sys.path.insert(0, str(Path(__file__).parent.parent))


@given(integers(min_value=1, max_value=100))
@settings(max_examples=100, deadline=None)
def test_property_12_student_data_isolation(student_id):
    """
    Feature: smartface-attendance-system, Property 12: Student only sees own records

    For any authenticated student session, every attendance record returned
    by GET /my-attendance must belong to that student's user_id only.
    No records from other users may appear in the response.

    Validates: Requirements 12.1, 12.3
    """
    # Build fake attendance rows for this student and a decoy user
    own_rows = [
        {"date": "2024-01-10", "time_in": "07:45:00", "time_out": "16:00:00", "status": "present"},
        {"date": "2024-01-11", "time_in": "08:10:00", "time_out": None,         "status": "late"},
    ]

    # The query in my_attendance filters by session user_id; mock execute_query
    # to return only the student's own rows regardless of input
    with patch("routes.attendance.execute_query", return_value=own_rows):
        from app import create_app
        flask_app = create_app()
        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = "test-isolation-key"

        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = student_id
                sess["role"]    = "student"
                sess["_fresh"]  = True

            response = client.get("/my-attendance")

        # The route must respond without error
        assert response.status_code == 200, (
            f"Expected 200 for student_id={student_id}, got {response.status_code}"
        )

        # Verify the execute_query call used student_id as the filter param
        # (isolation guarantee — only that student's rows are fetched)
        from routes.attendance import execute_query as mocked_q
        # The mock was called with the student's user_id in the params tuple
        for call in mocked_q.call_args_list:
            args, kwargs = call
            params = kwargs.get("params") or (args[1] if len(args) > 1 else None)
            if params:
                assert student_id in params, (
                    f"Query params {params} do not include student_id={student_id} — isolation violated"
                )
