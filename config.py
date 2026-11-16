"""
config.py — SmartFace configuration

All settings are read from environment variables (loaded from .env via
python-dotenv).  Hard-coded defaults are provided so the app starts in
development without a .env file.

SQLite DB is stored in %APPDATA%\SmartFace\smartface.db (managed by models/db.py).
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (silent no-op if the file is absent)
load_dotenv()

# ---------------------------------------------------------------------------
# Face-matching
# ---------------------------------------------------------------------------

TOLERANCE: float = float(os.getenv("TOLERANCE", 0.45))

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
