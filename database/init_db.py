import logging
import importlib.util
import os
import pathlib

logger = logging.getLogger(__name__)


def init_db() -> None:
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
            logger.info("init_db: tables already exist, skipping.")
            return
        logger.info("init_db: first boot detected, running schema + seed...")
        _run_schema()
        logger.info("init_db: schema applied, seeding...")
        _run_seed()
        logger.info("init_db: database ready.")
    except Exception as exc:
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