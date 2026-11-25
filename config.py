r"""
config.py — SmartFace configuration

All settings are read from environment variables (loaded from .env via
python-dotenv).  Hard-coded defaults are provided so the app starts in
development without a .env file.

SQLite DB is stored in %APPDATA%\SmartFace\smartface.db (managed by models/db.py).
"""

import os
import sys
from dotenv import load_dotenv

# Load .env from the project root (or next to executable when frozen)
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    for _p in [os.path.join(_exe_dir, ".env"), os.path.join(getattr(sys, '_MEIPASS', _exe_dir), ".env")]:
        if os.path.exists(_p):
            load_dotenv(_p)
            break
load_dotenv()

# ---------------------------------------------------------------------------
# Face-matching & Liveness
# ---------------------------------------------------------------------------

TOLERANCE: float = float(os.getenv("TOLERANCE", 0.48))
REQUIRE_LIVENESS: bool = os.getenv("REQUIRE_LIVENESS", "0").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Attendance rules
# ---------------------------------------------------------------------------

LATE_TIME: str = os.getenv("LATE_TIME", "08:00:00")

# ---------------------------------------------------------------------------
# Flask / session
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")

_debug_mode = os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True")
_test_mode = os.getenv("TESTING", "0") in ("1", "true", "True")
DEBUG: bool = _debug_mode

if SECRET_KEY == "change-me-in-production" and not _debug_mode and not _test_mode:
    if getattr(sys, 'frozen', False):
        SECRET_KEY = "smartface-desktop-production-key-sacli-2026"
    else:
        raise RuntimeError(
            "SECRET_KEY is set to the insecure default 'change-me-in-production'. "
            "Set a strong SECRET_KEY environment variable before running in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

# ---------------------------------------------------------------------------
# File storage
# ---------------------------------------------------------------------------

UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads/face_samples")

# ---------------------------------------------------------------------------
# Camera / image quality
# ---------------------------------------------------------------------------

BRIGHTNESS_THRESHOLD: int = int(os.getenv("BRIGHTNESS_THRESHOLD", 50))
