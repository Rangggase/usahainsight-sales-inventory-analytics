"""SQLite access: each request/service uses a separate connection and explicit transactions."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "instance" / "usahainsight.db"


def database_path() -> Path:
    return Path(os.getenv("USAHAINSIGHT_DB", str(DEFAULT_DB))).resolve()


@contextmanager
def connection():
    db_file = database_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with connection() as db:
        schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        db.executescript(schema)
        # Safe, idempotent migration for existing v1.0 SQLite databases.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(products)")}
        if "is_active" not in columns:
            db.execute("ALTER TABLE products ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))")
        db.commit()
