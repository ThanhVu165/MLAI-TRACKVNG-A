import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
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
    return conn


def test_admin_page_has_required_four_tabs_and_vietnamese_actions() -> None:
    page = Path("pages/3_Quan_tri_quy_dinh.py").read_text(encoding="utf-8")

    for label in ["Nạp tài liệu", "Chờ duyệt", "Đang hiệu lực", "Lịch sử"]:
        assert label in page
    for action in ["Nạp tệp", "Lưu nhãn", "Duyệt", "Kích hoạt tài liệu", "Rollback tài liệu"]:
        assert action in page


def test_admin_page_renders_seeded_corpus_without_loading_embedding_model() -> None:
    app = AppTest.from_file(Path.cwd() / "pages" / "3_Quan_tri_quy_dinh.py")
    app.session_state["db_connection"] = _db()

    app.run(timeout=10)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Nạp tài liệu",
        "Chờ duyệt",
        "Đang hiệu lực",
        "Lịch sử",
    ]
    assert app.metric[0].label == "Corpus version"
    assert any(
        info.value == "Chưa có tài liệu chờ duyệt. Hãy nạp tài liệu ở tab Nạp tài liệu."
        for info in app.info
    )
