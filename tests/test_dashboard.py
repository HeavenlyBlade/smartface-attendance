"""tests/test_dashboard.py — Unit tests for GET /dashboard and live-feed"""
import sys, json
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))

def make_client():
    from app import create_app
    app = create_app(); app.config["TESTING"] = True; app.config["SECRET_KEY"] = "test-dash"
    return app.test_client(), app

def auth(client):
    with client.session_transaction() as s:
        s["user_id"] = 1; s["role"] = "admin"

FAKE_RECORDS = [{"full_name":"Alice","id_number":"001","time_in":"07:45:00","time_out":None,"status":"present","confidence":92.5}]

def test_dashboard_loads():
    client, app = make_client()
    auth(client)
    with patch("routes.attendance.execute_query", side_effect=[{"c":3}, {"c":1}, {"c":30}]), \
         patch("routes.attendance.get_today_records", return_value=FAKE_RECORDS):
        with app.app_context():
            r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"Dashboard" in r.data

def test_live_feed_returns_records():
    client, app = make_client()
    auth(client)
    with patch("models.attendance.get_today_records", return_value=FAKE_RECORDS):
        with app.app_context():
            r = client.get("/api/live-feed")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "faces" in data

def test_live_feed_db_error():
    client, app = make_client()
    auth(client)
    from mysql.connector import Error as MySQLError
    with patch("models.attendance.get_today_records", side_effect=MySQLError("down")):
        with app.app_context():
            r = client.get("/api/live-feed")
    assert r.status_code == 503

