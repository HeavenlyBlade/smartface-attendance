"""
database/seed.py SmartFace development seed data
====================================================
Populates the SQLite database with:
  - 1 admin + 1 test_faculty + 11 BSIT students  (13 users total)
  - All passwords hashed; default password: Admin123
  - consent_given = 1  (RA 10173 compliance)
  - 3 weeks (21 calendar days) of attendance data for students, skipping
    weekends.  Per student per weekday:
      70% present  (time_in 07:007:59, status='present')
      15% late     (time_in 08:019:30, status='late')
      15% absent   (no row inserted)

Run from the SmartFace project root:
    python database/seed.py

Idempotent: if admin@sacli.edu.ph already exists the script exits early.
"""

import os
import random
import sys
from datetime import date, timedelta, time

# ---------------------------------------------------------------------------
# Path fix: allow imports when run from any working directory
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from werkzeug.security import generate_password_hash
from models.db import get_connection, execute_query, execute_many

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PASSWORD = "Admin123"
ADMIN_EMAIL = "admin@sacli.edu.ph"
SEED_RANDOM = 42
CONFIDENCE_MIN = 75.0
CONFIDENCE_MAX = 98.0

# ---------------------------------------------------------------------------
# User roster: 1 admin + 1 test_faculty + 11 students = 13 total
# ---------------------------------------------------------------------------

# fmt: off
ADMIN_USER = {
    "full_name":  "Carl",
    "email":      ADMIN_EMAIL,
    "role":       "admin",
    "id_number":  "SACLI-2024-0001",
    "department": "College of Computer Studies",
}

FACULTY_USERS = [
    {"full_name": "Test Faculty", "email": "test.faculty@sacli.edu.ph",
     "role": "faculty", "id_number": "SACLI-2024-0002", "department": "BSIT"},
]

STUDENT_USERS = [
    {"full_name": "Mon Gabriel Eta",       "email": "mongabriel.eta@sacli.edu.ph",       "id_number": "SACLI-2024-0007",  "department": "BSIT"},
    {"full_name": "Dave Marione Ortega",   "email": "davemarione.ortega@sacli.edu.ph",   "id_number": "SACLI-2024-0008",  "department": "BSIT"},
    {"full_name": "Benjamine Panganiban",  "email": "benjamine.panganiban@sacli.edu.ph", "id_number": "SACLI-2024-0009",  "department": "BSIT"},
    {"full_name": "Carl Vincent Remolin",  "email": "carlvincent.remolin@sacli.edu.ph",  "id_number": "SACLI-2024-0010",  "department": "BSIT"},
    {"full_name": "Justin Ritardo",        "email": "justin.ritardo@sacli.edu.ph",       "id_number": "SACLI-2024-0011",  "department": "BSIT"},
    {"full_name": "Dan Cedreck Monsalve",  "email": "dancedreck.monsalve@sacli.edu.ph",  "id_number": "SACLI-2024-0012",  "department": "BSIT"},
    {"full_name": "Keybe Duro",            "email": "keybe.duro@sacli.edu.ph",           "id_number": "SACLI-2024-0013",  "department": "BSIT"},
    {"full_name": "Warien Atienza",        "email": "warien.atienza@sacli.edu.ph",       "id_number": "SACLI-2024-0014",  "department": "BSIT"},
    {"full_name": "James Deligente",       "email": "james.deligente@sacli.edu.ph",      "id_number": "SACLI-2024-0015",  "department": "BSIT"},
    {"full_name": "Nico De Mesa",          "email": "nico.demesa@sacli.edu.ph",          "id_number": "SACLI-2024-0016",  "department": "BSIT"},
    {"full_name": "Kory Chester Atendido", "email": "korychestser.atendido@sacli.edu.ph","id_number": "SACLI-2024-0017",  "department": "BSIT"},
]
# fmt: on


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_time_in_range(start_h: int, start_m: int, end_h: int, end_m: int) -> time:
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    minutes = random.randint(start_total, end_total)
    seconds = random.randint(0, 59)
    return time(minutes // 60, minutes % 60, seconds)


def _weekdays_for_last_3_weeks() -> list:
    today = date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=20)
    weekdays = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            weekdays.append(current)
        current += timedelta(days=1)
    return weekdays


def _insert_user(conn, user_data: dict, role: str = "student") -> int:
    """Insert a single user row and return the new user id."""
    hashed = generate_password_hash(DEFAULT_PASSWORD)
    sql = """
        INSERT INTO users
            (full_name, email, password_hash, role, id_number, department,
             consent_given, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1, 1)
    """
    params = (
        user_data["full_name"],
        user_data["email"],
        hashed,
        role,
        user_data["id_number"],
        user_data["department"],
    )
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Main seed routine
# ---------------------------------------------------------------------------

def seed() -> None:
    random.seed(SEED_RANDOM)

    print("=" * 60)
    print("SmartFace Database Seed Script")
    print("=" * 60)

    # Idempotency check
    existing = execute_query(
        "SELECT id FROM users WHERE email = ?",
        params=(ADMIN_EMAIL,),
        fetchone=True,
    )
    if existing:
        print(f"[SKIP] Admin '{ADMIN_EMAIL}' already exists seed already run.")
        print("       Delete all rows from `users` and `attendance` to re-seed.")
        return

    conn = get_connection()

    try:
        # 1. Insert admin
        print("\n[1/4] Inserting admin user ...")
        admin_id = _insert_user(conn, ADMIN_USER, role="admin")
        print(f"      admin: {ADMIN_USER['full_name']} (id={admin_id})")

        # 2. Insert faculty
        print("\n[2/4] Inserting 1 test faculty user ...")
        for u in FACULTY_USERS:
            uid = _insert_user(conn, u, role="faculty")
            print(f"      Faculty: {u['full_name']} (id={uid})")


        # Steps 3+4: no seeded students or attendance data.
        # Enroll students via the web UI after first login.

        conn.commit()
        print('')
        print('=' * 60)
        print('Seed complete -- 2 users inserted (admin + test faculty).')
        print(f'  Admin login:  {ADMIN_EMAIL}')
        print(f'  Password:     {DEFAULT_PASSWORD}')
        print('=' * 60)
    except Exception as exc:
        conn.rollback()
        print(f"\n[ERROR] Seed failed transaction rolled back.\n  {exc}")
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
