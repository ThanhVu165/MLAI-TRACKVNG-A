import sqlite3

from corpus.seed import seed_if_empty


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
        """
    )
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
