import logging
import importlib.util
import os
import pathlib

logger = logging.getLogger(__name__)


def init_db() -> None:
    print("[init_db] Checking database tables...", flush=True)
    try:
        import psycopg2
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            import config
            dsn = (f"host={config.DB_HOST} port={config.DB_PORT} "
                   f"dbname={config.DB_NAME} user={config.DB_USER} "
                   f"password={config.DB_PASS} sslmode=require")

        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='users'")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        if count > 0:
            print("[init_db] Tables exist, skipping schema.", flush=True)
            _ensure_seeded(dsn)
            return

        print("[init_db] Creating tables...", flush=True)
        schema = pathlib.Path(__file__).parent.parent / "database" / "schema.sql"
        sql = schema.read_text(encoding="utf-8")

        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql)
        cur.close()
        conn.close()
        print("[init_db] Tables created.", flush=True)
        _ensure_seeded(dsn)
    except Exception as exc:
        print(f"[init_db] ERROR: {exc}", flush=True)
        logger.error("init_db failed: %s", exc)


def _ensure_seeded(dsn: str) -> None:
    try:
        import psycopg2
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
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
    seed_path = str(pathlib.Path(__file__).parent.parent / "database" / "seed.py")
    spec = importlib.util.spec_from_file_location("seed", seed_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.seed()