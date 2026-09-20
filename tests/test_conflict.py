import sqlite3

from corpus.conflict import detect_conflicts, scheduled_supersedes
from corpus.seed import seed_if_empty
from infra.db import MIGRATION_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    seed_if_empty(conn)
    return conn


def test_detects_refund_conflict_but_not_matching_withdrawal_deadline() -> None:
    conn = _db()
    events: list[dict[str, object]] = []

    conflicts = detect_conflicts(conn, audit=lambda **event: events.append(event))

    refund_rows = conn.execute(
        "SELECT doc_id, conflict_flag FROM chunks WHERE text LIKE '%hoàn 7%' OR text LIKE '%hoàn 6%'"
    ).fetchall()
    deadline_rows = conn.execute(
        "SELECT conflict_flag FROM chunks WHERE text LIKE '%Hạn chót rút học phần%'"
    ).fetchall()
    assert conflicts
    assert {row[0] for row in refund_rows} == {"WD-2026-20", "TU-2026-01"}
    assert all(row[1] == 1 for row in refund_rows)
    assert deadline_rows and all(row[0] == 0 for row in deadline_rows)
    assert all(event["action"] == "SOURCE_METADATA_EDITED" for event in events)


def test_supersedes_is_only_scheduled_while_old_document_is_active() -> None:
    conn = _db()
    conn.execute("UPDATE sources SET status='ACTIVE' WHERE doc_id='RL-2025-2363'")
    conn.commit()

    assert scheduled_supersedes(conn, "RL-2026-3150") == ["RL-2025-2363"]
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id='RL-2025-2363'").fetchone()[0]
        == "ACTIVE"
    )
