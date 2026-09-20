import sqlite3

import pytest

from corpus.metadata import SourceMetadata, save_metadata, validate_metadata
from corpus.store import create_source


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
    conn.execute(
        """CREATE TABLE settings (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, actor TEXT)"""
    )
    return conn


def _metadata(**changes: object) -> SourceMetadata:
    values: dict[str, object] = {
        "document_id": "RL-2026-3150",
        "title": "Quy định rèn luyện",
        "issuer": "Phòng CTSV",
        "published_at": "2026-07-07",
        "effective_from": "2026-07-07",
        "effective_to": None,
        "applies_to": ["undergraduate"],
        "cohorts": ["K48", "K49"],
        "supersedes": [],
        "transitional_clause": True,
        "domains": ["conduct_score"],
        "status": "PENDING_REVIEW",
        "content_hash": "hash-b",
    }
    values.update(changes)
    return SourceMetadata(**values)  # type: ignore[arg-type]


def test_validate_save_and_audit_metadata_diff() -> None:
    conn = _db()
    create_source(conn, {"doc_id": "DOC-TEMP", "status": "PENDING_REVIEW", "content_hash": "a"})
    conn.execute("INSERT INTO settings VALUES ('review:DOC-TEMP', 'APPROVE', NULL, 'ADMIN:vu')")
    conn.commit()
    events: list[dict[str, object]] = []

    changed = save_metadata(
        conn,
        "DOC-TEMP",
        _metadata(),
        actor="ADMIN:vu",
        audit=lambda **event: events.append(event),
    )

    row = conn.execute("SELECT doc_id, status, transitional_clause FROM sources").fetchone()
    assert tuple(row) == ("RL-2026-3150", "PENDING_REVIEW", 1)
    assert "doc_id" in changed and "domains_json" in changed
    assert events[0]["action"] == "SOURCE_METADATA_EDITED"
    assert conn.execute("SELECT 1 FROM settings WHERE key LIKE 'review:%'").fetchone() is None


def test_rejects_bad_dates_domains_duplicate_id_and_unconfirmed_transition() -> None:
    conn = _db()
    create_source(conn, {"doc_id": "DOC-TEMP", "status": "PENDING_REVIEW"})
    create_source(conn, {"doc_id": "DOC-TAKEN", "status": "PENDING_REVIEW"})

    with pytest.raises(ValueError, match="trước hoặc bằng"):
        validate_metadata(
            conn,
            _metadata(effective_from="2026-08-01", effective_to="2026-07-01"),
            existing_doc_id="DOC-TEMP",
        )
    with pytest.raises(ValueError, match="Domain"):
        validate_metadata(conn, _metadata(domains=["scholarship"]), existing_doc_id="DOC-TEMP")
    with pytest.raises(ValueError, match="đã tồn tại"):
        validate_metadata(conn, _metadata(document_id="DOC-TAKEN"), existing_doc_id="DOC-TEMP")
    with pytest.raises(ValueError, match="chuyển tiếp"):
        validate_metadata(conn, _metadata(transitional_clause=None), existing_doc_id="DOC-TEMP")
