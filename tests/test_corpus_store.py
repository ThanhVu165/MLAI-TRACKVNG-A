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
from infra.db import MIGRATION_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
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
    conn.execute("INSERT INTO settings VALUES ('review:DOC-1', 'APPROVE', NULL, 'ADMIN:test')")
    conn.commit()

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
    assert conn.execute("SELECT 1 FROM settings WHERE key='review:DOC-1'").fetchone() is None

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
