import sqlite3

from corpus.store import (
    bump_corpus_version,
    create_source,
    current_corpus_version,
    get_source,
    list_chunks,
    list_sources,
    replace_chunks,
    update_source,
)


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
    return conn


def test_crud_and_version_change_only_with_active_content() -> None:
    conn = _db()
    create_source(
        conn,
        {
            "doc_id": "DOC-1",
            "title": "Quy định 1",
            "status": "PENDING_REVIEW",
            "content_hash": "hash-a",
        },
    )
    assert get_source(conn, "DOC-1")["title"] == "Quy định 1"  # type: ignore[index]
    assert len(list_sources(conn, "PENDING_REVIEW")) == 1

    replace_chunks(
        conn,
        "DOC-1",
        [
            {
                "chunk_id": "c1",
                "breadcrumb": "Điều 1",
                "text": "Nội dung",
                "domain": "conduct_score",
                "ord": 1,
            }
        ],
    )
    assert list_chunks(conn, doc_id="DOC-1")[0]["label"] == "human_only"

    initial = bump_corpus_version(conn, "ADMIN:test", "Khởi tạo")
    assert initial == current_corpus_version(conn)
    update_source(conn, "DOC-1", status="ACTIVE")
    active = bump_corpus_version(conn, "ADMIN:test", "Kích hoạt")
    assert active != initial
    assert list_chunks(conn, active_only=True)[0]["chunk_id"] == "c1"

    update_source(conn, "DOC-1", status="SUPERSEDED")
    inactive = bump_corpus_version(conn, "ADMIN:test", "Hạ cấp")
    assert inactive != active
    assert list_chunks(conn, active_only=True) == []
