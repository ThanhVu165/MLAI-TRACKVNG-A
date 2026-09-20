import sqlite3
import time

from corpus.intake import ingest_rechecked, ingest_url, recheck_urls


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE sources (
        doc_id TEXT PRIMARY KEY, title TEXT, issuer TEXT, source_url TEXT,
        source_kind TEXT, sha256 TEXT UNIQUE, fetched_at TEXT,
        is_synthetic INTEGER DEFAULT 0, published_at TEXT, effective_from TEXT,
        effective_to TEXT, applies_to_json TEXT, cohorts_json TEXT,
        domains_json TEXT, supersedes_json TEXT, superseded_by TEXT,
        superseded_at TEXT, transitional_clause INTEGER DEFAULT 0,
        status TEXT NOT NULL, content_hash TEXT, created_at TEXT,
        activated_at TEXT, activated_by TEXT)""")
    ingest_url(
        conn,
        "https://example.edu/same.pdf",
        actor="ADMIN:vu",
        fetcher=lambda _: b"same",
    )
    ingest_url(
        conn,
        "https://example.edu/changed.pdf",
        actor="ADMIN:vu",
        fetcher=lambda _: b"old",
    )
    return conn


def test_manual_recheck_reports_changes_and_can_create_pending_version() -> None:
    conn = _db()
    events: list[dict[str, object]] = []
    payloads = {
        "https://example.edu/same.pdf": b"same",
        "https://example.edu/changed.pdf": b"new",
    }
    started = time.perf_counter()

    checks = recheck_urls(
        conn,
        actor="ADMIN:vu",
        fetcher=payloads.__getitem__,
        audit=lambda **event: events.append(event),
    )

    assert time.perf_counter() - started < 10
    assert {check.message for check in checks} == {"Không đổi", "Đã đổi"}
    assert [event["action"] for event in events] == ["SOURCE_RECHECKED"] * 2
    changed = next(check for check in checks if check.changed)
    result = ingest_rechecked(conn, changed, actor="ADMIN:vu")
    assert not result.duplicate
    assert (
        conn.execute("SELECT status FROM sources WHERE doc_id = ?", (result.doc_id,)).fetchone()[0]
        == "PENDING_REVIEW"
    )
