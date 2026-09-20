import sqlite3

from corpus.conflict import detect_conflicts, scheduled_supersedes
from corpus.seed import seed_if_empty


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE sources (
          doc_id TEXT PRIMARY KEY, title TEXT, issuer TEXT, source_url TEXT,
          source_kind TEXT, sha256 TEXT UNIQUE, fetched_at TEXT,
          is_synthetic INTEGER DEFAULT 0, published_at TEXT, effective_from TEXT,
          effective_to TEXT, applies_to_json TEXT, cohorts_json TEXT,
          domains_json TEXT, supersedes_json TEXT, superseded_by TEXT,
          superseded_at TEXT, transitional_clause INTEGER DEFAULT 0,
          status TEXT NOT NULL, content_hash TEXT, created_at TEXT,
          activated_at TEXT, activated_by TEXT
        );
        CREATE TABLE chunks (
          chunk_id TEXT PRIMARY KEY, doc_id TEXT REFERENCES sources,
          article_no TEXT, clause_no TEXT, breadcrumb TEXT NOT NULL,
          text TEXT NOT NULL, domain TEXT NOT NULL,
          label TEXT NOT NULL DEFAULT 'human_only', conflict_flag INTEGER DEFAULT 0,
          conflict_with TEXT, ord INTEGER, token_count INTEGER
        );
        CREATE TABLE corpus_versions (
          corpus_version TEXT PRIMARY KEY, created_at TEXT, actor TEXT,
          note TEXT, active_doc_ids_json TEXT
        );
        CREATE TABLE settings (
          key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, actor TEXT
        );
        """)
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
