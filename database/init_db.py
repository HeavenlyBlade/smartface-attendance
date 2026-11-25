import importlib.util
import logging
import pathlib

from models.db import get_connection

logger = logging.getLogger(__name__)


def init_db() -> None:
    print("[init_db] Checking database tables...", flush=True)
    try:
        conn = get_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()[0]

        if count > 0:
            print("[init_db] Tables exist, ensuring migrations...", flush=True)
            _ensure_migrations(conn)
            _ensure_seeded()
            return

        print("[init_db] Creating tables...", flush=True)
        # Resolve schema.sql relative to this file, with PyInstaller bundle support
        import sys as _sys
        if getattr(_sys, 'frozen', False):
            _base = pathlib.Path(_sys._MEIPASS)
        else:
            _base = pathlib.Path(__file__).parent
        schema = _base / "database" / "schema.sql"
        if not schema.exists():
            schema = pathlib.Path(__file__).parent / "schema.sql"
        sql = schema.read_text(encoding="utf-8")
        conn.executescript(sql)
        print("[init_db] Tables created.", flush=True)
        _ensure_migrations(conn)
        _ensure_seeded()
    except Exception as exc:
        print(f"[init_db] ERROR: {exc}", flush=True)
        logger.error("init_db failed: %s", exc)


def _ensure_migrations(conn) -> None:
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'student',
                department    TEXT,
                days_of_week  TEXT NOT NULL DEFAULT 'Monday,Tuesday,Wednesday,Thursday,Friday',
                start_time    TIME NOT NULL DEFAULT '08:00:00',
                end_time      TIME NOT NULL DEFAULT '17:00:00',
                grace_period_mins INTEGER NOT NULL DEFAULT 15,
                is_default    INTEGER NOT NULL DEFAULT 0,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        sched_cols = [r[1] for r in conn.execute("PRAGMA table_info(schedules)").fetchall()]
        if "role" not in sched_cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")

        cols = [r[1] for r in conn.execute("PRAGMA table_info(attendance)").fetchall()]
        if "schedule_id" not in cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN schedule_id INTEGER REFERENCES schedules(id)")
        if "late_minutes" not in cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN late_minutes INTEGER DEFAULT 0")
        if "late_reason" not in cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN late_reason TEXT DEFAULT ''")
        if "late_remarks" not in cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN late_remarks TEXT DEFAULT ''")
        if "scanner_id" not in cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN scanner_id TEXT DEFAULT 'Main Kiosk'")
        if "is_excused" not in cols:
            conn.execute("ALTER TABLE attendance ADD COLUMN is_excused INTEGER DEFAULT 0")

        sched_cnt = conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        if sched_cnt == 0:
            conn.execute("""
                INSERT INTO schedules (name, role, department, days_of_week, start_time, end_time, grace_period_mins, is_default, is_active)
                VALUES ('Default Student Schedule', 'student', '', 'Monday,Tuesday,Wednesday,Thursday,Friday', '08:00:00', '17:00:00', 15, 1, 1)
            """)
        fac_cnt = conn.execute("SELECT COUNT(*) FROM schedules WHERE role = 'faculty'").fetchone()[0]
        if fac_cnt == 0:
            conn.execute("""
                INSERT INTO schedules (name, role, department, days_of_week, start_time, end_time, grace_period_mins, is_default, is_active)
                VALUES ('Default Faculty Schedule', 'faculty', '', 'Monday,Tuesday,Wednesday,Thursday,Friday', '07:30:00', '17:30:00', 15, 1, 1)
            """)
        conn.commit()
    except Exception as e:
        logger.warning("_ensure_migrations encountered warning: %s", e)


def _ensure_seeded() -> None:
    try:
        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            print(f"[init_db] {count} users already seeded.", flush=True)
            return
        print("[init_db] Seeding data...", flush=True)
        _run_seed()
        print("[init_db] Done - database ready.", flush=True)
    except Exception as exc:
        print(f"[init_db] Seed error: {exc}", flush=True)
        logger.error("init_db seed failed: %s", exc)


def _run_seed() -> None:
    try:
        from database import seed
        seed.seed()
        return
    except Exception as e:
        logger.debug("direct import of database.seed failed: %s, falling back to file loader", e)

    seed_path = pathlib.Path(__file__).parent / "seed.py"
    if not seed_path.exists():
        import sys as _sys
        if getattr(_sys, 'frozen', False):
            seed_path = pathlib.Path(_sys._MEIPASS) / "database" / "seed.py"

    if seed_path.exists():
        spec = importlib.util.spec_from_file_location("seed", str(seed_path))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.seed()
