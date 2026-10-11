"""
tests/test_routes_api.py — Unit tests for /api/* route endpoints.

Tests cover:
  - POST /enroll returns 401 when not authenticated
  - POST /recognize returns 200 with {faces: []} when face_service returns empty list
  - GET /users returns 401 when not authenticated
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# POST /api/enroll — unauthenticated → 401
# ---------------------------------------------------------------------------

def test_enroll_returns_401_unauthenticated(test_app):
    """
    POST /api/enroll without a session returns 401.
    The @role_required('admin') decorator must fire before any business logic.
    """
    response = test_app.post(
        "/api/enroll",
        json={
            "full_name": "Test User",
            "email": "test@example.com",
            "id_number": "12345",
            "department": "IT",
            "role": "student",
            "consent_given": 1,
            "samples": [],
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/recognize — mocked face_service → 200 + empty faces list
# ---------------------------------------------------------------------------

def test_recognize_returns_200_with_empty_faces(auth_client):
    """
    POST /api/recognize with a valid (but blank) frame returns HTTP 200
    and {"faces": []} when face_service.recognize_frame returns an empty list.
    Mocks both face_service and the DB to keep this a pure unit test.
    """
    import base64
    import numpy as np
    import cv2

    # Build a minimal valid base64 JPEG so the payload passes validation
    blank = np.zeros((10, 10, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", blank)
    image_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    auth_client.set_session(user_id=1, role="admin")

    with patch("routes.api.face_service.recognize_frame", return_value=[]):
        response = auth_client.post(
            "/api/recognize",
            json={"image": image_b64},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "faces" in data
    assert data["faces"] == []


# ---------------------------------------------------------------------------
# GET /users — unauthenticated → 401 (redirect to login counts as non-200)
# ---------------------------------------------------------------------------

def test_users_returns_401_unauthenticated(test_app):
    """
    GET /users without a session redirects to /login (or returns 401).
    role_required aborts with 401 for unauthenticated requests on page routes,
    which Flask maps to a redirect to /login via the error handler.
    """
    response = test_app.get("/users", follow_redirects=False)
    # role_required calls abort(401) → our error handler redirects to /login
    # Accept either 401 or 302 (redirect to login)
    assert response.status_code in (401, 302)


# ---------------------------------------------------------------------------
# GET /users — authenticated as admin → should not return 401
# ---------------------------------------------------------------------------

def test_users_accessible_to_admin(auth_client):
    """
    GET /users with an admin session does NOT return 401.
    (May return 200, 302, or 503 depending on DB availability — all are
    acceptable since the auth gate was passed.)
    """
    auth_client.set_session(user_id=1, role="admin")

    with patch("routes.admin.list_users", return_value={"users": [], "total": 0, "pages": 1}):
        response = auth_client.get("/users", follow_redirects=False)

    assert response.status_code != 401
