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
            print("[init_db] Tables exist, skipping schema.", flush=True)
            _ensure_seeded()
            return

        print("[init_db] Creating tables...", flush=True)
        schema = pathlib.Path(__file__).parent / "schema.sql"
        sql = schema.read_text(encoding="utf-8")
        conn.executescript(sql)
        print("[init_db] Tables created.", flush=True)
        _ensure_seeded()
    except Exception as exc:
        print(f"[init_db] ERROR: {exc}", flush=True)
        logger.error("init_db failed: %s", exc)


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
    seed_path = str(pathlib.Path(__file__).parent / "seed.py")
    spec = importlib.util.spec_from_file_location("seed", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()
