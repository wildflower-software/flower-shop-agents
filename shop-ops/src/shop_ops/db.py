"""SQLite connection and schema setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schema" / "schema.sql"
DEFAULT_DB = PROJECT_ROOT / "data" / "shop.db"
CONFIG_DIR = PROJECT_ROOT / "config"


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def id_map(conn: sqlite3.Connection, table: str, key: str = "code") -> dict[str, int]:
    return {k: i for i, k in conn.execute(f"SELECT id, {key} FROM {table}")}


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default
