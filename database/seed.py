"""
database/seed.py — SmartFace development seed data
====================================================
Populates smartface_db with:
  - 1 admin, 5 faculty, 24 students  (30 users total)
  - All passwords hashed; default password: SmartFace2024!
  - consent_given = 1  (RA 10173 compliance)
  - 3 weeks (21 calendar days) of attendance data for students, skipping
    weekends.  Per student per weekday:
      70 % → present  (time_in 07:00–07:59, status='present')
      15 % → late     (time_in 08:01–09:30, status='late')
      15 % → absent   (no row inserted)

Run from the SmartFace project root:
    python database/seed.py

Idempotent: if admin@sacli.edu.ph already exists the script exits early.
"""

import os
import random
import sys
from datetime import date, timedelta, time

# ---------------------------------------------------------------------------
# Path fix: allow `import config` and `from models.db import …` when the
# script is run from *any* working directory, not just the project root.
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from werkzeug.security import generate_password_hash
from models.db import get_connection, execute_query, execute_many
import config  # noqa: F401 — triggers .env load and sets DB_* constants

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PASSWORD = "SmartFace2024!"
ADMIN_EMAIL = "admin@sacli.edu.ph"
SEED_RANDOM = 42          # reproducible runs
CONFIDENCE_MIN = 75.0
CONFIDENCE_MAX = 98.0

DEPARTMENTS = [
    "College of Computer Studies",
    "College of Education",
    "College of Business",
    "College of Nursing",
    "College of Engineering",
]

# ---------------------------------------------------------------------------
# User roster
# 1 admin + 5 faculty + 24 students = 30 total
# All Filipino names; roles/depts spread realistically
# ---------------------------------------------------------------------------

# fmt: off
ADMIN_USER = {
    "full_name":  "Maria Santos",
    "email":      ADMIN_EMAIL,
    "role":       "admin",
    "id_number":  "SACLI-2024-0001",
    "department": "College of Computer Studies",
}

FACULTY_USERS = [
    {"full_name": "Jose Reyes",       "email": "jose.reyes@sacli.edu.ph",       "role": "faculty", "id_number": "SACLI-2024-0002", "department": "College of Computer Studies"},
    {"full_name": "Ana Dela Cruz",    "email": "ana.delacruz@sacli.edu.ph",     "role": "faculty", "id_number": "SACLI-2024-0003", "department": "College of Education"},
    {"full_name": "Roberto Villanueva","email": "roberto.villanueva@sacli.edu.ph","role":"faculty","id_number": "SACLI-2024-0004", "department": "College of Business"},
    {"full_name": "Lourdes Castillo", "email": "lourdes.castillo@sacli.edu.ph", "role": "faculty", "id_number": "SACLI-2024-0005", "department": "College of Nursing"},
    {"full_name": "Emmanuel Bautista","email": "emmanuel.bautista@sacli.edu.ph","role": "faculty", "id_number": "SACLI-2024-0006", "department": "College of Engineering"},
]

STUDENT_USERS = [
    {"full_name": "Angelica Torres",   "email": "angelica.torres@sacli.edu.ph",   "id_number": "SACLI-2024-0007",  "department": "College of Computer Studies"},
    {"full_name": "Miguel Ramos",      "email": "miguel.ramos@sacli.edu.ph",      "id_number": "SACLI-2024-0008",  "department": "College of Computer Studies"},
    {"full_name": "Kristine Aquino",   "email": "kristine.aquino@sacli.edu.ph",   "id_number": "SACLI-2024-0009",  "department": "College of Computer Studies"},
    {"full_name": "Daniel Fernandez",  "email": "daniel.fernandez@sacli.edu.ph",  "id_number": "SACLI-2024-0010",  "department": "College of Computer Studies"},
    {"full_name": "Joanna Mendoza",    "email": "joanna.mendoza@sacli.edu.ph",    "id_number": "SACLI-2024-0011",  "department": "College of Computer Studies"},
    {"full_name": "Paolo Garcia",      "email": "paolo.garcia@sacli.edu.ph",      "id_number": "SACLI-2024-0012",  "department": "College of Education"},
    {"full_name": "Carmela Navarro",   "email": "carmela.navarro@sacli.edu.ph",   "id_number": "SACLI-2024-0013",  "department": "College of Education"},
    {"full_name": "Ronaldo Cruz",      "email": "ronaldo.cruz@sacli.edu.ph",      "id_number": "SACLI-2024-0014",  "department": "College of Education"},
    {"full_name": "Patricia Lopez",    "email": "patricia.lopez@sacli.edu.ph",    "id_number": "SACLI-2024-0015",  "department": "College of Education"},
    {"full_name": "Francis Gomez",     "email": "francis.gomez@sacli.edu.ph",     "id_number": "SACLI-2024-0016",  "department": "College of Business"},
    {"full_name": "Marilou Rivera",    "email": "marilou.rivera@sacli.edu.ph",    "id_number": "SACLI-2024-0017",  "department": "College of Business"},
    {"full_name": "Anthony Pascual",   "email": "anthony.pascual@sacli.edu.ph",   "id_number": "SACLI-2024-0018",  "department": "College of Business"},
    {"full_name": "Shiela Morales",    "email": "shiela.morales@sacli.edu.ph",    "id_number": "SACLI-2024-0019",  "department": "College of Business"},
    {"full_name": "Jerome Santiago",   "email": "jerome.santiago@sacli.edu.ph",   "id_number": "SACLI-2024-0020",  "department": "College of Business"},
    {"full_name": "Rowena Flores",     "email": "rowena.flores@sacli.edu.ph",     "id_number": "SACLI-2024-0021",  "department": "College of Nursing"},
    {"full_name": "Eduardo Aguilar",   "email": "eduardo.aguilar@sacli.edu.ph",   "id_number": "SACLI-2024-0022",  "department": "College of Nursing"},
    {"full_name": "Liezl Santos",      "email": "liezl.santos@sacli.edu.ph",      "id_number": "SACLI-2024-0023",  "department": "College of Nursing"},
    {"full_name": "Christian Dela Pena","email":"christian.delapena@sacli.edu.ph","id_number": "SACLI-2024-0024",  "department": "College of Nursing"},
    {"full_name": "Mary Grace Reyes",  "email": "marygrace.reyes@sacli.edu.ph",   "id_number": "SACLI-2024-0025",  "department": "College of Nursing"},
    {"full_name": "Jomar Tan",         "email": "jomar.tan@sacli.edu.ph",         "id_number": "SACLI-2024-0026",  "department": "College of Engineering"},
    {"full_name": "Clarissa Villafuerte","email":"clarissa.villafuerte@sacli.edu.ph","id_number":"SACLI-2024-0027","department": "College of Engineering"},
    {"full_name": "Alvin Ocampo",      "email": "alvin.ocampo@sacli.edu.ph",      "id_number": "SACLI-2024-0028",  "department": "College of Engineering"},
    {"full_name": "Hazel Macaraeg",    "email": "hazel.macaraeg@sacli.edu.ph",    "id_number": "SACLI-2024-0029",  "department": "College of Engineering"},
    {"full_name": "Bryan Catalan",     "email": "bryan.catalan@sacli.edu.ph",     "id_number": "SACLI-2024-0030",  "department": "College of Engineering"},
]
# fmt: on


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_time_in_range(start_h: int, start_m: int, end_h: int, end_m: int) -> time:
    """Return a random time object between [start_h:start_m, end_h:end_m]."""
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    minutes = random.randint(start_total, end_total)
    seconds = random.randint(0, 59)
    return time(minutes // 60, minutes % 60, seconds)


def _weekdays_for_last_3_weeks() -> list[date]:
    """
    Return an ordered list of weekdays (Mon–Fri) covering exactly 21
    calendar days ending yesterday. Weekends are excluded, giving
    between 14 and 15 actual attendance days depending on the calendar.
    """
    today = date.today()
    end = today - timedelta(days=1)       # yesterday — so today is "live"
    start = end - timedelta(days=20)      # 21-day window (indices 0..20)
    weekdays = []
    current = start
    while current <= end:
        if current.weekday() < 5:         # 0=Mon … 4=Fri, 5=Sat, 6=Sun
            weekdays.append(current)
        current += timedelta(days=1)
    return weekdays


def _insert_user(conn, cursor, user_data: dict, role: str = "student") -> int:
    """Insert a single user row and return the new user id."""
    hashed = generate_password_hash(DEFAULT_PASSWORD)
    sql = """
        INSERT INTO users
            (full_name, email, password_hash, role, id_number, department,
             consent_given, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, 1, 1)
    """
    params = (
        user_data["full_name"],
        user_data["email"],
        hashed,
        role,
        user_data["id_number"],
        user_data["department"],
    )
    cursor.execute(sql, params)
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Main seed routine
# ---------------------------------------------------------------------------

def seed() -> None:
    random.seed(SEED_RANDOM)

    print("=" * 60)
    print("SmartFace — Database Seed Script")
    print("=" * 60)

    # ------------------------------------------------------------------ #
    # Idempotency check                                                     #
    # ------------------------------------------------------------------ #
    existing = execute_query(
        "SELECT id FROM users WHERE email = %s",
        params=(ADMIN_EMAIL,),
        fetchone=True,
    )
    if existing:
        print(f"[SKIP] Admin '{ADMIN_EMAIL}' already exists — seed already run.")
        print("       Delete all rows from `users` and `attendance` to re-seed.")
        return

    conn = get_connection()
    conn.autocommit = False
    cursor = conn.cursor(dictionary=True)

    try:
        # ---------------------------------------------------------------- #
        # 1. Insert admin                                                    #
        # ---------------------------------------------------------------- #
        print("\n[1/4] Inserting admin user …")
        admin_id = _insert_user(conn, cursor, ADMIN_USER, role="admin")
        print(f"      ✓ Admin: {ADMIN_USER['full_name']} (id={admin_id})")

        # ---------------------------------------------------------------- #
        # 2. Insert faculty                                                  #
        # ---------------------------------------------------------------- #
        print("\n[2/4] Inserting 5 faculty users …")
        for u in FACULTY_USERS:
            uid = _insert_user(conn, cursor, u, role="faculty")
            print(f"      ✓ Faculty: {u['full_name']} (id={uid})")

        # ---------------------------------------------------------------- #
        # 3. Insert students                                                 #
        # ---------------------------------------------------------------- #
        print("\n[3/4] Inserting 24 student users …")
        student_ids: list[int] = []
        for u in STUDENT_USERS:
            uid = _insert_user(conn, cursor, u, role="student")
            student_ids.append(uid)
            print(f"      ✓ Student: {u['full_name']} (id={uid})")

        # ---------------------------------------------------------------- #
        # 4. Generate attendance rows (students only)                        #
        # ---------------------------------------------------------------- #
        print("\n[4/4] Generating 3 weeks of attendance data …")
        weekdays = _weekdays_for_last_3_weeks()
        print(f"      Weekdays found: {len(weekdays)} days "
              f"({weekdays[0]} → {weekdays[-1]})")

        attendance_rows: list[tuple] = []
        present_count = late_count = absent_count = 0

        for student_id in student_ids:
            for day in weekdays:
                roll = random.random()   # uniform [0.0, 1.0)

                if roll < 0.70:
                    # Present: time_in between 07:00 and 07:59
                    t_in = _random_time_in_range(7, 0, 7, 59)
                    confidence = round(random.uniform(CONFIDENCE_MIN, CONFIDENCE_MAX), 2)
                    attendance_rows.append((
                        student_id,
                        day.isoformat(),
                        str(t_in),
                        None,          # time_out — NULL until recognized again
                        "present",
                        confidence,
                        None,          # marked_by — automatic
                    ))
                    present_count += 1

                elif roll < 0.85:
                    # Late: time_in between 08:01 and 09:30
                    t_in = _random_time_in_range(8, 1, 9, 30)
                    confidence = round(random.uniform(CONFIDENCE_MIN, CONFIDENCE_MAX), 2)
                    attendance_rows.append((
                        student_id,
                        day.isoformat(),
                        str(t_in),
                        None,
                        "late",
                        confidence,
                        None,
                    ))
                    late_count += 1

                else:
                    # Absent: no row inserted
                    absent_count += 1

        # Bulk-insert all attendance rows
        if attendance_rows:
            att_sql = """
                INSERT INTO attendance
                    (user_id, date, time_in, time_out, status, confidence, marked_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    time_in    = VALUES(time_in),
                    status     = VALUES(status),
                    confidence = VALUES(confidence)
            """
            cursor.executemany(att_sql, attendance_rows)
            print(f"      ✓ Inserted {len(attendance_rows)} attendance row(s):")
            print(f"        Present: {present_count}  |  Late: {late_count}  "
                  f"|  Absent (skipped): {absent_count}")
        else:
            print("      (no attendance rows generated — check weekday window)")

        conn.commit()
        print("\n" + "=" * 60)
        print("Seed complete — all 30 users and attendance data inserted.")
        print(f"\n  Admin login:  {ADMIN_EMAIL}")
        print(f"  Password:     {DEFAULT_PASSWORD}")
        print("=" * 60)

    except Exception as exc:
        conn.rollback()
        print(f"\n[ERROR] Seed failed — transaction rolled back.\n  {exc}")
        raise
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
