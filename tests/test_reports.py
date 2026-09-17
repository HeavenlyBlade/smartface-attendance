"""tests/test_reports.py — Unit tests for GET /reports and CSV export"""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))

def make_client():
    from app import create_app
    app = create_app(); app.config["TESTING"] = True; app.config["SECRET_KEY"] = "test-reports"
    return app.test_client(), app

def auth(client, role="admin"):
    with client.session_transaction() as s:
        s["user_id"] = 1; s["role"] = role

FAKE_RESULT = {"records": [{"full_name":"A","id_number":"001","department":"CS","role":"student","date":"2024-01-10","time_in":"07:50:00","time_out":"16:00:00","status":"present","confidence":88.5}], "total": 1, "pages": 1}

def test_reports_valid_filter():
    client, app = make_client()
    auth(client)
    with patch("routes.attendance.get_records", return_value=FAKE_RESULT):
        with app.app_context():
            r = client.get("/reports?start_date=2024-01-01&end_date=2024-01-31")
    assert r.status_code == 200
    assert b"A" in r.data

def test_reports_start_after_end():
    client, app = make_client()
    auth(client)
    with app.app_context():
        r = client.get("/reports?start_date=2024-02-01&end_date=2024-01-01")
    assert r.status_code == 200
    assert b"cannot be after" in r.data.lower()

def test_reports_no_results():
    client, app = make_client()
    auth(client)
    empty = {"records": [], "total": 0, "pages": 1}
    with patch("routes.attendance.get_records", return_value=empty):
        with app.app_context():
            r = client.get("/reports")
    assert r.status_code == 200
    assert b"No records" in r.data

def test_csv_export_valid():
    client, app = make_client()
    auth(client)
    with patch("routes.attendance.get_records", return_value=FAKE_RESULT):
        with app.app_context():
            r = client.get("/reports/export")
    assert r.status_code == 200
    assert b"full_name" in r.data   # header row
    assert b"A" in r.data

def test_csv_export_start_after_end():
    client, app = make_client()
    auth(client)
    with app.app_context():
        r = client.get("/reports/export?start_date=2024-02-01&end_date=2024-01-01")
    assert r.status_code == 400
