import sqlite3

import pytest

from corpus.intake import ingest_text, ingest_upload, ingest_url


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE sources (
        doc_id TEXT PRIMARY KEY, title TEXT, issuer TEXT, source_url TEXT,
        source_kind TEXT, sha256 TEXT UNIQUE, fetched_at TEXT,
        is_synthetic INTEGER DEFAULT 0, published_at TEXT, effective_from TEXT,
        effective_to TEXT, applies_to_json TEXT, cohorts_json TEXT,
        domains_json TEXT, supersedes_json TEXT, superseded_by TEXT,
        superseded_at TEXT, transitional_clause INTEGER DEFAULT 0,
        status TEXT NOT NULL, content_hash TEXT, created_at TEXT,
        activated_at TEXT, activated_by TEXT)"""
    )
    return conn


def test_three_intake_paths_deduplicate_and_audit() -> None:
    conn = _db()
    events: list[dict[str, object]] = []

    def audit(**event: object) -> None:
        events.append(event)

    uploaded = ingest_upload(conn, "quy-dinh.pdf", b"%PDF sample", actor="ADMIN:vu", audit=audit)
    duplicate = ingest_upload(conn, "ban-sao.pdf", b"%PDF sample", actor="ADMIN:vu", audit=audit)
    pasted = ingest_text(conn, "Điều 1. Nội dung", title="Văn bản", actor="ADMIN:vu", audit=audit)
    fetched = ingest_url(
        conn,
        "https://example.edu/quy-dinh.docx",
        actor="ADMIN:vu",
        fetcher=lambda _: b"PK docx sample",
        audit=audit,
    )

    assert not uploaded.duplicate
    assert duplicate.duplicate and duplicate.doc_id == uploaded.doc_id
    assert duplicate.message == "Tài liệu không thay đổi"
    assert pasted.filename.endswith(".txt")
    assert fetched.filename == "quy-dinh.docx"
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 3
    assert [event["action"] for event in events] == ["SOURCE_UPLOADED"] * 3


def test_intake_rejects_invalid_inputs() -> None:
    conn = _db()
    with pytest.raises(ValueError, match="PDF hoặc DOCX"):
        ingest_upload(conn, "malware.exe", b"x", actor="ADMIN:vu")
    with pytest.raises(ValueError, match="http"):
        ingest_url(conn, "file:///secret.pdf", actor="ADMIN:vu")
    with pytest.raises(ValueError, match="để trống"):
        ingest_text(conn, "", title="Trống", actor="ADMIN:vu")
