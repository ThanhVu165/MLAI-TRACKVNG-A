import sqlite3

import pytest

from corpus.lifecycle import document_diff, pending_reviews, submit_review
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


def test_review_queue_shows_diff_and_records_approval_reason() -> None:
    conn = _db()
    conn.execute("UPDATE sources SET status='PENDING_REVIEW' WHERE doc_id='RL-2026-3150'")
    conn.commit()
    events: list[dict[str, object]] = []

    queue = pending_reviews(conn)
    diff = document_diff(conn, "RL-2026-3150")
    submit_review(
        conn,
        "RL-2026-3150",
        "APPROVE",
        actor="ADMIN:vu",
        reason="Metadata và nhãn đã đúng",
        audit=lambda **event: events.append(event),
    )

    assert [document["doc_id"] for document in queue] == ["RL-2026-3150"]
    assert "RL-2025-2363" in diff and "RL-2026-3150" in diff
    assert "K49" in diff
    assert (
        conn.execute("SELECT value FROM settings WHERE key='review:RL-2026-3150'").fetchone()[0]
        == "APPROVE"
    )
    assert events[0]["action"] == "SOURCE_METADATA_EDITED"


def test_review_requires_reason_and_rejects_document() -> None:
    conn = _db()
    conn.execute("UPDATE sources SET status='PENDING_REVIEW' WHERE doc_id='GA-2026-08'")
    conn.commit()
    with pytest.raises(ValueError, match="Lý do"):
        submit_review(conn, "GA-2026-08", "REJECT", actor="ADMIN:vu", reason="")

    submit_review(conn, "GA-2026-08", "REJECT", actor="ADMIN:vu", reason="Sai ngày")
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id='GA-2026-08'").fetchone()[0]
        == "REJECTED"
    )
