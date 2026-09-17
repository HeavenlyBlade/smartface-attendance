"""tests/test_override.py — Unit tests for POST /attendance/manual"""
import sys, json
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))

def make_client():
    from app import create_app
    app = create_app(); app.config["TESTING"] = True; app.config["SECRET_KEY"] = "test-override"
    return app.test_client(), app

def admin_session(client):
    with client.session_transaction() as s:
        s["user_id"] = 1; s["role"] = "admin"
        s["_last_active"] = datetime.now().isoformat()

FAKE_USER = {"id": 5, "full_name": "Student A", "email": "s@s.com", "is_active": 1}
TODAY = date.today().isoformat()
OLD_DATE = (date.today() - timedelta(days=400)).isoformat()

def test_override_valid():
    client, app = make_client()
    admin_session(client)
    with patch("routes.attendance.get_user_by_id", return_value=FAKE_USER), \
         patch("routes.attendance.db_manual_override"), \
         patch("routes.attendance.write_audit"):
        with app.app_context():
            r = client.post("/attendance/manual", json={"user_id": 5, "date": TODAY})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["success"] is True

def test_override_user_not_found():
    client, app = make_client()
    admin_session(client)
    with patch("routes.attendance.get_user_by_id", return_value=None):
        with app.app_context():
            r = client.post("/attendance/manual", json={"user_id": 999, "date": TODAY})
    assert r.status_code == 404

def test_override_date_too_old():
    client, app = make_client()
    admin_session(client)
    with patch("routes.attendance.get_user_by_id", return_value=FAKE_USER):
        with app.app_context():
            r = client.post("/attendance/manual", json={"user_id": 5, "date": OLD_DATE})
    assert r.status_code == 400

def test_override_invalid_date():
    client, app = make_client()
    admin_session(client)
    with patch("routes.attendance.get_user_by_id", return_value=FAKE_USER):
        with app.app_context():
            r = client.post("/attendance/manual", json={"user_id": 5, "date": "not-a-date"})
    assert r.status_code == 400
