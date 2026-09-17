"""tests/test_enrollment.py — Unit tests for POST /api/enroll"""
import sys, json, base64
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))

def make_client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-enroll"
    return app.test_client(), app

def admin_session(client):
    with client.session_transaction() as s:
        s["user_id"] = 1; s["role"] = "admin"

def dummy_b64():
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf.tobytes()).decode()

def test_enroll_missing_consent():
    client, app = make_client()
    admin_session(client)
    payload = {"full_name":"A","email":"a@a.com","id_number":"1","department":"D","role":"student","consent_given":0,"samples":[dummy_b64()]*3}
    with app.app_context():
        r = client.post("/api/enroll", json=payload)
    assert r.status_code == 400
    assert b"consent" in r.data.lower()

def test_enroll_too_few_samples():
    client, app = make_client()
    admin_session(client)
    payload = {"full_name":"A","email":"a@a.com","id_number":"1","department":"D","role":"student","consent_given":1,"samples":[dummy_b64()]}
    with app.app_context():
        r = client.post("/api/enroll", json=payload)
    assert r.status_code == 400

def test_enroll_duplicate_email():
    client, app = make_client()
    admin_session(client)
    payload = {"full_name":"A","email":"a@a.com","id_number":"1","department":"D","role":"student","consent_given":1,"samples":[dummy_b64()]*3}
    fake_enc = np.zeros(128)
    with patch("routes.api.encode_samples", return_value=[fake_enc]*3), \
         patch("routes.api.execute_query", side_effect=[{"id":99}, None]):
        with app.app_context():
            r = client.post("/api/enroll", json=payload)
    assert r.status_code == 400
    assert b"email" in r.data.lower()
