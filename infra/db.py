from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path("data/app.db")
MIGRATION_PATH = Path(__file__).with_name("migrations") / "001_init.sql"
LOCAL_TIMEZONE = timezone(timedelta(hours=7))


def _path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return Path(os.getenv("APP_DB_PATH") or DEFAULT_DB_PATH)


def now_iso() -> str:
    """Trả thời gian UTC theo ISO-8601 với hậu tố Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_local(ts: str) -> str:
    """Đổi dấu thời gian ISO UTC sang múi giờ Việt Nam (+07:00)."""
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE).isoformat()


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Mở SQLite, bật WAL và tự chạy migration idempotent."""
    path = _path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return conn


def fetch_one(
    sql: str,
    params: Iterable[object] = (),
    *,
    db_path: str | Path | None = None,
) -> sqlite3.Row | None:
    with get_connection(db_path) as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def fetch_all(
    sql: str,
    params: Iterable[object] = (),
    *,
    db_path: str | Path | None = None,
) -> list[sqlite3.Row]:
    with get_connection(db_path) as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def execute(
    sql: str,
    params: Iterable[object] = (),
    *,
    db_path: str | Path | None = None,
) -> int:
    """Chạy một lệnh ghi và trả số dòng bị ảnh hưởng."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, tuple(params))
        conn.commit()
        return cursor.rowcount
