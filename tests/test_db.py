from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from infra.db import execute, fetch_all, get_connection, now_iso, to_local


def test_migration_and_time_helpers(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    with get_connection(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert {"cases", "audit_events", "sources", "settings"} <= tables
    assert now_iso().endswith("Z")
    assert to_local("2026-09-20T00:00:00Z").endswith("+07:00")


def test_concurrent_writes_use_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    get_connection(db_path).close()

    def write(index: int) -> None:
        execute(
            "INSERT INTO settings(key, value) VALUES (?, ?)",
            (f"key-{index}", str(index)),
            db_path=db_path,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, range(20)))
    assert len(fetch_all("SELECT key FROM settings", db_path=db_path)) == 20
