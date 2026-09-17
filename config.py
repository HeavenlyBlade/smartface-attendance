"""
config.py — SmartFace configuration

All settings are read from environment variables (loaded from .env via
python-dotenv).  Hard-coded defaults are provided so the app starts in
development without a .env file, but every production deployment MUST
override SECRET_KEY, DB_PASS, and DB_NAME at minimum.

Usage in other modules:
    from config import TOLERANCE, LATE_TIME, DB_HOST, ...
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (silent no-op if the file is absent)
load_dotenv()

# ---------------------------------------------------------------------------
# Face-matching
# ---------------------------------------------------------------------------

# Distance threshold for accepting a face match.
# Lower = stricter (fewer false positives, more false negatives).
# 0.40 (cosine) -- tighter than the old 0.45 (Euclidean) because Facenet
# cosine distances occupy a narrower scale than dlib Euclidean distances.
# Adjust via the TOLERANCE env var if recognition is too strict/lenient.
TOLERANCE: float = float(os.getenv("TOLERANCE", 0.40))

# ---------------------------------------------------------------------------
# Attendance rules
# ---------------------------------------------------------------------------

# Time-in after this threshold is recorded as 'late' instead of 'present'.
# Format: HH:MM:SS (24-hour).
LATE_TIME: str = os.getenv("LATE_TIME", "08:00:00")

# ---------------------------------------------------------------------------
# Flask / session
# ---------------------------------------------------------------------------

# MUST be overridden with a long random string in production.
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")

# ---------------------------------------------------------------------------
# Database (MySQL via mysql-connector-python)
# ---------------------------------------------------------------------------

DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", 3306))
DB_USER: str = os.getenv("DB_USER", "root")
DB_PASS: str = os.getenv("DB_PASS", "")
DB_NAME: str = os.getenv("DB_NAME", "smartface_db")

# ---------------------------------------------------------------------------
# File storage
# ---------------------------------------------------------------------------

# Directory for raw enrollment JPEG samples (relative to project root).
# Created automatically by the enrollment route if it does not exist.
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads/face_samples")

# ---------------------------------------------------------------------------
# Camera / image quality
# ---------------------------------------------------------------------------

# Mean pixel brightness (0–255) below which the kiosk shows a lighting warning.
# Computed client-side in camera.js before each frame is sent to the server.
BRIGHTNESS_THRESHOLD: int = int(os.getenv("BRIGHTNESS_THRESHOLD", 50))
