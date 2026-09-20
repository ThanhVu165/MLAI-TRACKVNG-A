import sqlite3
import time

from corpus.intake import ingest_rechecked, ingest_url, recheck_urls
from infra.db import MIGRATION_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
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
