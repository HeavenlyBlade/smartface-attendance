"""
tests/conftest.py — pytest configuration and shared fixtures for SmartFace.

Fixtures
--------
test_app    Flask test client (TESTING=True, real DB with smartface_test_db if
            available, otherwise falls back to the configured smartface_db).
auth_client Wraps test_app with a set_session() helper that injects session
            variables via client.session_transaction().

Hypothesis settings
-------------------
Profile "smartface" is registered and loaded globally:
    max_examples=100, deadline=5000 ms
"""

import sys
from pathlib import Path

import pytest
from hypothesis import settings

# ---------------------------------------------------------------------------
# sys.path — ensure the project root is importable from any working directory
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Hypothesis global profile
# ---------------------------------------------------------------------------

settings.register_profile("smartface", max_examples=100, deadline=5000)
settings.load_profile("smartface")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_app():
    """
    Flask test client with TESTING=True.

    Configuration overrides applied to every test run:
        TESTING         = True
        SECRET_KEY      = 'test-secret-key'
        DB_NAME         = 'smartface_test_db'  (falls back to real DB if needed)

    Yields the Flask test client (not the app) so callers can make requests
    directly:

        def test_something(test_app):
            response = test_app.get('/login')
            assert response.status_code == 200
    """
    import os
    # Tell config to use the test database.  This must happen before create_app
    # imports config, so we set the env var directly.
    os.environ.setdefault("DB_NAME", "smartface_test_db")

    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["DB_NAME"] = "smartface_test_db"

    with app.test_client() as client:
        with app.app_context():
            yield client


# ---------------------------------------------------------------------------
# AuthenticatedClient helper
# ---------------------------------------------------------------------------

class AuthenticatedClient:
    """
    Thin wrapper around a Flask test client that provides a convenience
    method for injecting session state without going through the login
    endpoint.

    Usage
    -----
        def test_admin_page(auth_client):
            auth_client.set_session(user_id=1, role='admin')
            response = auth_client.get('/dashboard')
            assert response.status_code == 200

        def test_student_blocked(auth_client):
            auth_client.set_session(user_id=5, role='student')
            response = auth_client.get('/dashboard')
            assert response.status_code == 403
    """

    def __init__(self, client):
        self._client = client

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def set_session(self, user_id: int = 1, role: str = "admin",
                    full_name: str = "Test User") -> None:
        """
        Inject authentication state into the current session.

        Parameters
        ----------
        user_id:    Numeric user ID stored in session['user_id']
        role:       Role string — 'admin', 'faculty', or 'student'
        full_name:  Display name stored in session['full_name']
        """
        with self._client.session_transaction() as sess:
            sess["user_id"]   = user_id
            sess["role"]      = role
            sess["full_name"] = full_name

    def clear_session(self) -> None:
        """Remove all session variables (simulates logout or session expiry)."""
        with self._client.session_transaction() as sess:
            sess.clear()

    # ------------------------------------------------------------------
    # HTTP method proxies
    # ------------------------------------------------------------------

    def get(self, *args, **kwargs):
        """Proxy GET to the underlying test client."""
        return self._client.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        """Proxy POST to the underlying test client."""
        return self._client.post(*args, **kwargs)

    def put(self, *args, **kwargs):
        """Proxy PUT to the underlying test client."""
        return self._client.put(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Proxy DELETE to the underlying test client."""
        return self._client.delete(*args, **kwargs)

    # ------------------------------------------------------------------
    # Expose the raw client when needed
    # ------------------------------------------------------------------

    @property
    def client(self):
        """Access the underlying Flask test client directly."""
        return self._client


@pytest.fixture
def auth_client(test_app):
    """
    Authenticated test client with a set_session() convenience method.

    Wraps the test_app fixture so callers get session-injection helpers
    without boilerplate ``session_transaction`` blocks in every test.

    Example
    -------
        def test_faculty_blocked_from_enroll(auth_client):
            auth_client.set_session(user_id=2, role='faculty')
            response = auth_client.get('/enroll')
            assert response.status_code == 403
    """
    return AuthenticatedClient(test_app)
