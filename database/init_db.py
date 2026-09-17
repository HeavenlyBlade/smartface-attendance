import logging
import importlib.util
import os
import pathlib

logger = logging.getLogger(__name__)


def init_db() -> None:
    print("[init_db] Starting database initialisation check...", flush=True)
    try:
        from models.db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'users'"
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] > 0:
            print("[init_db] Tables already exist, skipping.", flush=True)
            return
        print("[init_db] First boot - creating tables...", flush=True)
        _run_schema()
        print("[init_db] Tables created - seeding data...", flush=True)
        _run_seed()
        print("[init_db] Done - database ready.", flush=True)
    except Exception as exc:
        print(f"[init_db] ERROR: {exc}", flush=True)
        logger.error("init_db failed: %s", exc)


def _run_schema() -> None:
    schema = pathlib.Path(__file__).parent.parent / "database" / "schema.sql"
    sql = schema.read_text(encoding="utf-8")
    from models.db import get_connection
    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()
    for stmt in sql.split(";"):
        s = stmt.strip()
        if s and not s.startswith("--"):
            cur.execute(s)
    cur.close()
    conn.close()


def _run_seed() -> None:
    seed_path = str(pathlib.Path(__file__).parent.parent / "database" / "seed.py")
    spec = importlib.util.spec_from_file_location("seed", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()