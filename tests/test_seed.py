import sqlite3

from corpus.seed import seed_if_empty
from infra.db import MIGRATION_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return conn


def test_seed_loads_six_synthetic_documents_and_at_least_45_chunks() -> None:
    conn = _db()

    assert seed_if_empty(conn) == 6
    assert seed_if_empty(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 6
    assert conn.execute("SELECT SUM(is_synthetic) FROM sources").fetchone()[0] == 6
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id='RL-2025-2363'").fetchone()[0]
        == "SUPERSEDED"
    )
    assert (
        conn.execute(
            "SELECT transitional_clause FROM sources WHERE doc_id='RL-2026-3150'"
        ).fetchone()[0]
        == 1
    )

    total, automatic = conn.execute(
        "SELECT COUNT(*), SUM(label='auto_answerable') FROM chunks"
    ).fetchone()
    assert total >= 45
    assert 0.55 <= automatic / total <= 0.65
    assert (
        conn.execute(
            "SELECT COUNT(DISTINCT domain) FROM chunks WHERE doc_id='AUTH-2026-01'"
        ).fetchone()[0]
        == 3
    )
