import logging
import importlib.util
import pathlib
import time

logger = logging.getLogger(__name__)


def init_db() -> None:
    print("[init_db] Starting database initialisation check...", flush=True)
    try:
        import models.db as db_module

        # Check if tables exist using a fresh direct connection (bypasses pool)
        conn = db_module.get_connection()
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
        print("[init_db] Schema committed.", flush=True)

        # Reset the connection pool so seed.py gets fresh connections
        # that can see the newly created tables
        print("[init_db] Resetting connection pool...", flush=True)
        db_module._pool = None
        time.sleep(1)

        print("[init_db] Seeding data...", flush=True)
        _run_seed()
        print("[init_db] Done - database ready.", flush=True)

    except Exception as exc:
        print(f"[init_db] ERROR: {exc}", flush=True)
        logger.error("init_db failed: %s", exc)


def _run_schema() -> None:
    schema = pathlib.Path(__file__).parent.parent / "database" / "schema.sql"
    sql = schema.read_text(encoding="utf-8")

    import mysql.connector
    import config
    conn = mysql.connector.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASS,
        database=config.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    cur = conn.cursor()
    for stmt in sql.split(";"):
        s = stmt.strip()
        if s and not s.startswith("--"):
            cur.execute(s)
    conn.commit()
    cur.close()
    conn.close()


def _run_seed() -> None:
    seed_path = str(pathlib.Path(__file__).parent.parent / "database" / "seed.py")
    spec = importlib.util.spec_from_file_location("seed", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()