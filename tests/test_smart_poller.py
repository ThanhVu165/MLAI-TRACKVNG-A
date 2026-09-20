from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Self

from core.pipeline import process_case
from core.poller import (
    HeadInfo,
    check_and_rerun_affected_case,
    check_source_update,
    check_url_head,
    poll_sources_from_db,
    stage_updated_source,
)
from core.types import CaseInput


def _create_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE sources (
            doc_id TEXT PRIMARY KEY,
            title TEXT,
            source_url TEXT,
            source_kind TEXT,
            sha256 TEXT UNIQUE,
            fetched_at TEXT,
            status TEXT NOT NULL,
            content_hash TEXT,
            created_at TEXT
        )"""
    )
    return conn


def test_check_url_head_extracts_headers() -> None:
    class DummyHeaders:
        def get(self, key: str, default: str | None = None) -> str | None:
            mapping = {
                "ETag": '"abc123etag"',
                "Last-Modified": "Sun, 20 Sep 2026 08:00:00 GMT",
                "Content-Length": "1048576",
            }
            return mapping.get(key, default)

    class DummyResponse:
        headers = DummyHeaders()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def dummy_opener(req: object, timeout: int = 10) -> DummyResponse:
        return DummyResponse()

    head = check_url_head("https://school.edu.vn/qd.pdf", opener=dummy_opener)
    assert head.accessible is True
    assert head.etag == "abc123etag"
    assert head.last_modified == "Sun, 20 Sep 2026 08:00:00 GMT"
    assert head.content_length == 1048576


def test_check_url_head_handles_network_failure() -> None:
    def fail_opener(req: object, timeout: int = 10) -> None:
        raise TimeoutError("Connection timed out")

    head = check_url_head("https://unreachable.edu.vn/qd.pdf", opener=fail_opener)
    assert head.accessible is False
    assert "timed out" in (head.error or "")


def test_check_source_update_fast_path_etag() -> None:
    download_called = False

    def dummy_fetcher(url: str) -> bytes:
        nonlocal download_called
        download_called = True
        return b"heavy pdf content"

    def head_checker(url: str) -> HeadInfo:
        return HeadInfo(
            url=url,
            etag="etag-stable-v1",
            last_modified=None,
            content_length=5000,
            accessible=True,
        )

    res = check_source_update(
        doc_id="DOC-01",
        url="https://school.edu.vn/quy-che.pdf",
        title="Quy chế đào tạo",
        stored_sha256="hash123",
        stored_etag="etag-stable-v1",
        head_checker=head_checker,
        body_fetcher=dummy_fetcher,
    )

    assert res.changed is False
    assert res.skipped_download is True
    assert res.status_message == "Không đổi"
    assert download_called is False  # Saved 100% download bandwidth!


def test_check_source_update_detects_changed_content() -> None:
    def head_checker(url: str) -> HeadInfo:
        return HeadInfo(
            url=url,
            etag="etag-new-v2",
            last_modified="Sun, 20 Sep 2026 09:00:00 GMT",
            content_length=8000,
            accessible=True,
        )

    new_content = b"new regulation text 2026 updated"

    res = check_source_update(
        doc_id="DOC-01",
        url="https://school.edu.vn/quy-che.pdf",
        title="Quy chế đào tạo",
        stored_sha256="old_sha_mismatch",
        stored_etag="etag-old-v1",
        head_checker=head_checker,
        body_fetcher=lambda _: new_content,
    )

    assert res.changed is True
    assert res.skipped_download is False
    assert res.status_message == "Đã đổi"
    assert res.payload == new_content
    assert res.new_sha256 is not None


def test_poll_sources_from_db_and_audit() -> None:
    conn = _create_test_db()
    conn.execute(
        """INSERT INTO sources (doc_id, title, source_url, source_kind, sha256, status)
        VALUES ('DOC-01', 'Quy chế 1', 'https://school.edu.vn/qc1.pdf', 'url', 'sha_same', 'ACTIVE'),
               ('DOC-02', 'Quy chế 2', 'https://school.edu.vn/qc2.pdf', 'url', 'sha_old', 'ACTIVE')"""
    )
    conn.commit()

    payloads = {
        "https://school.edu.vn/qc1.pdf": b"same content",
        "https://school.edu.vn/qc2.pdf": b"updated content 2026",
    }

    import hashlib

    # ensure doc1 sha matches
    doc1_sha = hashlib.sha256(b"same content").hexdigest()
    conn.execute("UPDATE sources SET sha256 = ? WHERE doc_id = 'DOC-01'", (doc1_sha,))
    conn.commit()

    events: list[dict[str, object]] = []

    def fake_audit(**kwargs: object) -> None:
        events.append(kwargs)

    def dummy_head(url: str) -> HeadInfo:
        return HeadInfo(
            url=url, etag=None, last_modified=None, content_length=None, accessible=True
        )

    results = poll_sources_from_db(
        conn,
        actor="ADMIN:lead",
        head_checker=dummy_head,
        body_fetcher=payloads.__getitem__,
        audit_fn=fake_audit,
    )

    assert len(results) == 2
    assert results[0].changed is False
    assert results[1].changed is True
    assert len(events) == 2
    assert all(e["action"] == "SOURCE_RECHECKED" for e in events)


def test_stage_updated_source_to_pending_review() -> None:
    conn = _create_test_db()
    conn.execute(
        """INSERT INTO sources (doc_id, title, source_url, source_kind, sha256, status)
        VALUES ('DOC-01', 'Quy chế gốc', 'https://school.edu.vn/qc.pdf', 'url', 'old_hash', 'ACTIVE')"""
    )
    conn.commit()

    from core.poller import PollCheckResult

    new_payload = b"new regulation amended 2026"
    import hashlib

    new_sha = hashlib.sha256(new_payload).hexdigest()

    check = PollCheckResult(
        doc_id="DOC-01",
        url="https://school.edu.vn/qc.pdf",
        title="Quy chế gốc",
        changed=True,
        status_message="Đã đổi",
        skipped_download=False,
        new_sha256=new_sha,
        payload=new_payload,
    )

    events: list[dict[str, object]] = []
    staged_id = stage_updated_source(
        conn,
        check,
        actor="ADMIN:lead",
        audit_fn=lambda **kw: events.append(kw),
    )

    assert staged_id.startswith("DOC-")
    assert len(events) == 1
    assert events[0]["action"] == "SOURCE_UPLOADED"

    # Verify in DB: staged source is in PENDING_REVIEW
    row = conn.execute(
        "SELECT status, sha256 FROM sources WHERE doc_id = ?", (staged_id,)
    ).fetchone()
    assert row[0] == "PENDING_REVIEW"
    assert row[1] == new_sha

    # Anti-duplicate test: staging same check again returns same doc_id without error
    staged_again = stage_updated_source(conn, check, actor="ADMIN:lead")
    assert staged_again == staged_id


def test_smart_poller_triggers_rerun_case_integration() -> None:
    inp = CaseInput(
        sender="student@example.edu.vn",
        subject="Xin rút môn học",
        body="Thưa thầy cô cho em hỏi hạn rút môn học kỳ này là khi nào?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    initial_res = process_case(inp)
    assert initial_res.case_id.startswith("c_")

    # When regulation updates to cv_v2, poller triggers rerun
    rerun_res, diff = check_and_rerun_affected_case(
        initial_res.case_id,
        new_corpus_version="cv_v2_updated",
    )
    assert rerun_res.case_id.startswith("c_")
    assert diff["case_id"] == initial_res.case_id
    assert diff["rerun_case_id"] == rerun_res.case_id
    assert "corpus_version_before" in diff
    assert "corpus_version_after" in diff
