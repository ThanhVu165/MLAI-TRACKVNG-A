import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from corpus.coverage import label_chunk
from corpus.lifecycle import (
    activate_source,
    affected_cases,
    document_diff,
    flag_cases_for_recheck,
    pending_reviews,
    rollback_source,
    submit_review,
    supersede_source,
)
from corpus.seed import seed_if_empty
from corpus.store import bump_corpus_version, current_corpus_version


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
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
        CREATE TABLE cases (
          case_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE decisions (
          decision_id TEXT PRIMARY KEY, case_id TEXT, evidence_ids_json TEXT
        );
        """
    )
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


def test_activate_uses_real_admin_supersedes_old_source_and_reindexes() -> None:
    conn = _db()
    conn.execute("UPDATE sources SET status='PENDING_REVIEW' WHERE doc_id='RL-2026-3150'")
    conn.execute(
        "UPDATE sources SET status='ACTIVE', superseded_by=NULL, superseded_at=NULL "
        "WHERE doc_id='RL-2025-2363'"
    )
    conn.commit()
    before = bump_corpus_version(conn, "ADMIN:test", "Chuẩn bị bản cũ")
    events: list[dict[str, object]] = []
    reindexed: list[bool] = []
    submit_review(
        conn,
        "RL-2026-3150",
        "APPROVE",
        actor="ADMIN:vu",
        reason="Đã kiểm tra",
        audit=lambda **event: events.append(event),
    )

    after = activate_source(
        conn,
        "RL-2026-3150",
        actor="ADMIN:vu",
        reason="Ban hành bản 2026",
        audit=lambda **event: events.append(event),
        reindex=lambda: reindexed.append(True),
    )

    states = dict(conn.execute("SELECT doc_id, status FROM sources").fetchall())
    assert states["RL-2026-3150"] == "ACTIVE"
    assert states["RL-2025-2363"] == "SUPERSEDED"
    assert after != before and after == current_corpus_version(conn)
    assert reindexed == [True]
    activated = next(event for event in events if event["action"] == "ACTIVATE_SOURCE")
    assert activated["actor"] == "ADMIN:vu"


def test_activate_rejects_system_actor() -> None:
    conn = _db()
    with pytest.raises(ValueError, match="quản trị viên"):
        activate_source(conn, "RL-2026-3150", actor="SYSTEM", reason="Không hợp lệ")


def test_edit_after_approval_requires_review_again() -> None:
    conn = _db()
    conn.execute("UPDATE sources SET status='PENDING_REVIEW' WHERE doc_id='RL-2026-3150'")
    conn.commit()
    submit_review(
        conn,
        "RL-2026-3150",
        "APPROVE",
        actor="ADMIN:vu",
        reason="Đã kiểm tra",
        audit=lambda **_: None,
    )
    chunk_id, label = conn.execute(
        "SELECT chunk_id, label FROM chunks WHERE doc_id='RL-2026-3150' LIMIT 1"
    ).fetchone()

    label_chunk(
        conn,
        chunk_id,
        "human_only" if label == "auto_answerable" else "auto_answerable",
        actor="ADMIN:vu",
        audit=lambda **_: None,
    )

    with pytest.raises(ValueError, match="duyệt trước"):
        activate_source(conn, "RL-2026-3150", actor="ADMIN:vu", reason="Kích hoạt")


def test_supersede_removes_chunks_from_active_set_but_keeps_history() -> None:
    conn = _db()
    conn.execute("UPDATE sources SET status='ACTIVE' WHERE doc_id='RL-2025-2363'")
    conn.commit()
    events: list[dict[str, object]] = []

    version = supersede_source(
        conn,
        "RL-2025-2363",
        "RL-2026-3150",
        actor="ADMIN:vu",
        reason="Áp dụng bản mới",
        audit=lambda **event: events.append(event),
    )

    assert version == current_corpus_version(conn)
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id='RL-2025-2363'").fetchone()[0]
        == "SUPERSEDED"
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id='RL-2025-2363'").fetchone()[0] == 9
    )
    assert (
        conn.execute(
            """SELECT COUNT(*) FROM chunks JOIN sources USING(doc_id)
           WHERE chunks.doc_id='RL-2025-2363' AND sources.status='ACTIVE'"""
        ).fetchone()[0]
        == 0
    )
    assert events[0]["action"] == "SUPERSEDE_SOURCE"


def test_flags_only_cases_using_source_within_30_days_and_rolls_back() -> None:
    conn = _db()
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    chunk_id = conn.execute(
        "SELECT chunk_id FROM chunks WHERE doc_id='RL-2025-2363' LIMIT 1"
    ).fetchone()[0]
    replacement_chunk_id = conn.execute(
        "SELECT chunk_id FROM chunks WHERE doc_id='RL-2026-3150' LIMIT 1"
    ).fetchone()[0]
    conn.executemany(
        "INSERT INTO cases(case_id, status, created_at) VALUES (?, 'RESOLVED', ?)",
        [
            ("recent", (now - timedelta(days=10)).isoformat()),
            ("recent-new", (now - timedelta(days=5)).isoformat()),
            ("old", (now - timedelta(days=40)).isoformat()),
        ],
    )
    conn.executemany(
        "INSERT INTO decisions VALUES (?, ?, ?)",
        [
            ("d1", "recent", f'["{chunk_id}"]'),
            ("d2", "old", f'["{chunk_id}"]'),
            ("d3", "recent-new", f'["{replacement_chunk_id}"]'),
        ],
    )
    conn.commit()
    events: list[dict[str, object]] = []

    assert affected_cases(conn, "RL-2025-2363", now=now) == ["recent"]
    flagged = flag_cases_for_recheck(
        conn,
        "RL-2025-2363",
        actor="SYSTEM",
        audit=lambda **event: events.append(event),
        now=now,
    )
    assert flagged == ["recent"]
    assert dict(conn.execute("SELECT case_id, status FROM cases").fetchall()) == {
        "recent": "NEEDS_RECHECK",
        "recent-new": "RESOLVED",
        "old": "RESOLVED",
    }
    assert events[0]["action"] == "FLAG_NEEDS_RECHECK"

    version = rollback_source(
        conn,
        "RL-2025-2363",
        actor="ADMIN:vu",
        reason="Phát hiện bản mới sai",
        audit=lambda **event: events.append(event),
    )
    assert version == current_corpus_version(conn)
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id='RL-2025-2363'").fetchone()[0]
        == "ACTIVE"
    )
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id='RL-2026-3150'").fetchone()[0]
        == "SUPERSEDED"
    )
    assert (
        conn.execute("SELECT status FROM cases WHERE case_id='recent-new'").fetchone()[0]
        == "NEEDS_RECHECK"
    )
    assert any(event["action"] == "ROLLBACK_SOURCE" for event in events)
