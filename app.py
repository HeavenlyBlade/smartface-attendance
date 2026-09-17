"""
app.py — SmartFace Flask application entry point

Startup sequence
----------------
1. Load .env (python-dotenv).
2. Create the Flask app and apply session / secret-key settings.
3. Register all four blueprints.
4. Register error handlers (404, 403, 500).
5. Pre-load the in-memory face-encoding cache (non-fatal if DB is offline).
6. Run the dev server.

IMPORTANT — use_reloader=False
    Flask's auto-reloader spawns a child process.  That child process does NOT
    inherit the in-memory encoding cache loaded at startup, so every recognised
    face would silently fall back to "Unknown".  Always keep use_reloader=False.

LAN HTTPS note
    Uncomment the ssl_context='adhoc' line below to enable HTTPS over LAN
    (requires `pip install pyopenssl`).  getUserMedia requires localhost or
    HTTPS, so this is needed when accessing the kiosk from another device on
    the network.
"""

import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

# Load .env from the project root before importing config so that os.getenv
# calls inside config.py resolve to the correct values.
load_dotenv()

import config  # noqa: E402 — must come after load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional face_service import
# face_service is implemented in Day 2.  Guard the import so the app starts
# cleanly on Day 1 even though the module doesn't exist yet.
# ---------------------------------------------------------------------------

try:
    from services import face_service  # noqa: F401
    _face_service_available = True
except ImportError:
    _face_service_available = False
    logger.warning(
        "services.face_service not found — skipping startup cache load. "
        "This is expected before Day 2 tasks are implemented."
    )

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """
    Create and configure the Flask application.

    Returns a fully configured Flask instance with blueprints registered,
    error handlers attached, and the face-encoding cache pre-loaded.
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------ #
    # Core settings                                                        #
    # ------------------------------------------------------------------ #

    app.secret_key = config.SECRET_KEY

    # Sessions expire after 30 minutes of inactivity.
    # SESSION_PERMANENT=True makes Flask honour PERMANENT_SESSION_LIFETIME.
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)

    # ------------------------------------------------------------------ #
    # Blueprint registration                                               #
    # ------------------------------------------------------------------ #

    # auth blueprint — handles /login, /logout, role redirect at /
    from routes.auth import auth_bp          # noqa: PLC0415
    app.register_blueprint(auth_bp, url_prefix="")

    # admin blueprint — user management, enrollment UI, etc.
    from routes.admin import admin_bp        # noqa: PLC0415
    app.register_blueprint(admin_bp, url_prefix="")

    # attendance blueprint — /kiosk, /dashboard, /reports, /attendance/*
    from routes.attendance import attendance_bp  # noqa: PLC0415
    app.register_blueprint(attendance_bp, url_prefix="")

    # api blueprint — JSON endpoints under /api/*
    from routes.api import api_bp            # noqa: PLC0415
    app.register_blueprint(api_bp, url_prefix="/api")

    # ------------------------------------------------------------------ #
    # Error handlers                                                       #
    # ------------------------------------------------------------------ #

    @app.errorhandler(404)
    def not_found(exc):
        """Return a branded 404 page, or JSON if the template is missing."""
        try:
            return render_template("errors/404.html"), 404
        except Exception:
            return jsonify({"error": "Not found"}), 404

    @app.errorhandler(403)
    def forbidden(exc):
        """Return a branded 403 page, or JSON if the template is missing."""
        try:
            return render_template("errors/403.html"), 403
        except Exception:
            return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(500)
    def internal_error(exc):
        """Always return JSON for 500 — avoids template errors masking real ones."""
        logger.exception("Unhandled 500 error: %s", exc)
        return jsonify({"error": "Internal server error"}), 500

    # ------------------------------------------------------------------ #
    # Startup: pre-load face-encoding cache                               #
    # ------------------------------------------------------------------ #

    with app.app_context():
        if _face_service_available:
            try:
                face_service.load_known_faces()
                logger.info("Face-encoding cache loaded successfully at startup.")
            except Exception as exc:
                # Non-fatal: the kiosk will simply treat every face as Unknown
                # until the DB comes back online and the cache is reloaded.
                logger.error(
                    "Could not load face-encoding cache at startup (DB may be "
                    "offline): %s — continuing with empty cache.", exc
                )
        else:
            logger.info(
                "Face service unavailable — recognition will not work until "
                "services/face_service.py is implemented."
            )

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    # LAN HTTPS — uncomment when accessing the kiosk from another device on the
    # network (requires `pip install pyopenssl`).  getUserMedia requires either
    # localhost or HTTPS, so this is necessary for non-localhost access.
    # app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')  # LAN HTTPS

    # use_reloader=False is REQUIRED — see module docstring for the reason.
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
