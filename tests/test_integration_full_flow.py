"""Integration test: Full lifecycle Pipeline → Dispatch → Controls → Poller.

Kiểm tra toàn bộ luồng chạy ổn định end-to-end, bao gồm:
1. Pipeline xử lý case → quyết định AUTO_REPLY hoặc ESCALATE
2. Dispatch lập lịch gửi → Pause chặn gửi → Resume khôi phục
3. Override ghi đè quyết định + đồng bộ registry
4. Rerun case sau khi quy chế cập nhật
5. Smart Poller phát hiện thay đổi quy chế
6. Audit log ghi đúng contract kwargs
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from core.controls import (
    is_automation_paused,
    override_decision,
    pause_automation,
    rerun_case,
    resume_automation,
)
from core.dispatch import (
    cancel_send,
    dispatch_case,
    escalate_from_pending,
    get_dispatch_record,
    schedule_dispatch,
)
from core.explain import explain_decision
from core.pipeline import process_case
from core.poller import (
    HeadInfo,
    check_source_update,
    poll_sources_from_db,
    stage_updated_source,
)
from core.resume import resume_after_human
from core.types import CaseInput, CaseStatus, Decision, DraftReply


def _make_input(subject: str, body: str) -> CaseInput:
    return CaseInput(
        sender="sv@school.edu.vn",
        subject=subject,
        body=body,
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )


def _make_db() -> sqlite3.Connection:
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


# ─── Test 1: Full pipeline → dispatch → pause blocks send ─────────────
def test_pipeline_dispatch_pause_blocks_send() -> None:
    """Issue #2: Pause phải chặn được dispatch_case."""
    inp = _make_input(
        "Hỏi thời hạn rút môn",
        "Cho em hỏi hạn chót rút môn học kỳ chính là ngày nào ạ?",
    )
    result = process_case(inp)
    assert result.case_id.startswith("c_")

    # Lập lịch gửi
    draft = DraftReply(
        subject="Re: test",
        body="Trả lời test",
        citations=[],
        grounded=True,
        guard_failures=[],
    )
    record = schedule_dispatch(result.case_id, draft, countdown_seconds=0)
    assert record.status == CaseStatus.PENDING_SEND

    # Pause → dispatch phải fail
    pause_automation(actor="ADMIN:test", reason="Test pause")
    assert is_automation_paused() is True

    success, msg = dispatch_case(result.case_id, force=True)
    assert success is False
    assert "tạm dừng" in msg

    # Resume → dispatch phải thành công
    resume_automation(actor="ADMIN:test")
    assert is_automation_paused() is False

    success, msg = dispatch_case(result.case_id, force=True)
    assert success is True
    assert get_dispatch_record(result.case_id).status == CaseStatus.SENT


# ─── Test 2: Override đồng bộ cancel registry ─────────────────────────
def test_override_syncs_with_dispatch_registry() -> None:
    """Issue #2: Override sang ESCALATE phải cancel dispatch."""
    inp = _make_input(
        "Hỏi lệ phí rút môn",
        "Cho em hỏi lệ phí rút môn có phải đóng gì thêm không ạ?",
    )
    result = process_case(inp)

    # Schedule dispatch
    draft = DraftReply(
        subject="Re: test",
        body="Trả lời",
        citations=[],
        grounded=True,
        guard_failures=[],
    )
    schedule_dispatch(result.case_id, draft, countdown_seconds=60)

    # Override sang ESCALATE
    updated = override_decision(
        result.case_id,
        Decision.ESCALATE,
        actor="ADMIN:tester",
        reason="Case cần xem xét lại vì chính sách mới",
    )
    assert updated.decision.decision == Decision.ESCALATE
    assert updated.status == CaseStatus.AWAITING_HUMAN

    # Dispatch registry phải đã bị cancel
    record = get_dispatch_record(result.case_id)
    assert record.status == CaseStatus.CANCELLED


# ─── Test 3: Override bắt buộc reason ─────────────────────────────────
def test_override_requires_reason() -> None:
    """Override không có reason phải raise ValueError."""
    inp = _make_input("Test", "Em hỏi quy trình rút môn học kỳ chính")
    result = process_case(inp)
    try:
        override_decision(result.case_id, Decision.ESCALATE, reason="")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "bắt buộc" in str(e)


# ─── Test 4: Rerun case sinh diff analysis ─────────────────────────────
def test_rerun_case_produces_diff() -> None:
    """Issue #4: rerun_case trả về tuple (PipelineResult, dict)."""
    inp = _make_input(
        "Hỏi hạn chót rút môn",
        "Cho em hỏi hạn cuối cùng để rút môn học kỳ này là khi nào ạ?",
    )
    result = process_case(inp)

    _rerun_result, diff = rerun_case(result.case_id, actor="ADMIN:qa")
    assert isinstance(diff, dict)
    assert diff["case_id"] == result.case_id
    assert "decision_changed" in diff
    assert "old_decision" in diff
    assert "new_decision" in diff
    assert "citations_added" in diff
    assert "citations_removed" in diff
    assert "corpus_version_before" in diff


# ─── Test 5: Explain không chứa thuật ngữ kỹ thuật ────────────────────
def test_explain_decision_no_tech_terms() -> None:
    """explain_decision phải trả về text <= 120 từ, không chứa thuật ngữ cấm."""
    inp = _make_input(
        "Phúc khảo điểm",
        "Em muốn nộp đơn phúc khảo bài thi kết thúc môn Giải tích của em vì điểm thấp bất thường.",
    )
    result = process_case(inp)
    explanation = explain_decision(result)

    word_count = len(explanation.split())
    assert word_count <= 120, f"Giải thích quá dài: {word_count} từ"

    from core.explain import FORBIDDEN_TECH_TERMS

    lower_text = explanation.lower()
    for term in FORBIDDEN_TECH_TERMS:
        assert term not in lower_text, f"Chứa thuật ngữ cấm: {term}"


# ─── Test 6: resume_after_human bắt buộc reason ───────────────────────
def test_resume_after_human_requires_reason() -> None:
    inp = _make_input(
        "Xin rút môn sau hạn",
        "Em bị tai nạn nằm viện nên muốn xin rút môn sau hạn quy định.",
    )
    result = process_case(inp)
    try:
        resume_after_human(result.case_id, "Duyệt", "", actor="ADMIN:staff")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "bắt buộc" in str(e)


# ─── Test 7: Fail-safe — pipeline exception escalate, không AUTO_REPLY
def test_fail_safe_no_auto_reply_on_exception() -> None:
    """Issue #1: Lỗi thật không được trả AUTO_REPLY."""
    inp = _make_input("", "")  # empty input → phải escalate/invalid
    result = process_case(inp)
    # Empty input must NOT get AUTO_REPLY
    assert result.decision.decision != Decision.AUTO_REPLY


# ─── Test 8: Smart Poller ETag fast-path ───────────────────────────────
def test_poller_etag_fast_path_skips_download() -> None:
    download_called = False

    def dummy_fetcher(url: str) -> bytes:
        nonlocal download_called
        download_called = True
        return b"content"

    def head_checker(url: str) -> HeadInfo:
        return HeadInfo(
            url=url,
            etag="stable-etag-v1",
            last_modified=None,
            content_length=1024,
            accessible=True,
        )

    res = check_source_update(
        doc_id="D01",
        url="https://school.edu.vn/qc.pdf",
        title="QC",
        stored_sha256="anything",
        stored_etag="stable-etag-v1",
        head_checker=head_checker,
        body_fetcher=dummy_fetcher,
    )
    assert res.changed is False
    assert res.skipped_download is True
    assert download_called is False


# ─── Test 9: Smart Poller content change detection ─────────────────────
def test_poller_content_change_detection() -> None:
    new_content = b"updated regulation 2026"
    old_sha = "0" * 64

    def head_checker(url: str) -> HeadInfo:
        return HeadInfo(
            url=url, etag="new-etag", last_modified=None, content_length=None, accessible=True
        )

    res = check_source_update(
        doc_id="D01",
        url="https://school.edu.vn/qc.pdf",
        title="QC",
        stored_sha256=old_sha,
        stored_etag="old-etag",
        head_checker=head_checker,
        body_fetcher=lambda _: new_content,
    )
    assert res.changed is True
    assert res.new_sha256 == hashlib.sha256(new_content).hexdigest()


# ─── Test 10: stage_updated_source PENDING_REVIEW ──────────────────────
def test_stage_source_pending_review() -> None:
    conn = _make_db()
    new_payload = b"new regulation text"
    new_sha = hashlib.sha256(new_payload).hexdigest()

    from core.poller import PollCheckResult

    check = PollCheckResult(
        doc_id="D01",
        url="https://school.edu.vn/qc.pdf",
        title="QC",
        changed=True,
        status_message="Đã đổi",
        skipped_download=False,
        new_sha256=new_sha,
        payload=new_payload,
    )
    staged_id = stage_updated_source(conn, check)
    row = conn.execute(
        "SELECT status FROM sources WHERE doc_id = ?", (staged_id,)
    ).fetchone()
    assert row[0] == "PENDING_REVIEW"


# ─── Test 11: poll_sources_from_db audit logging ───────────────────────
def test_poll_audit_logs_contract() -> None:
    """Audit phải gọi đúng kwargs contract: case_id, actor, action, input_ref, reason."""
    conn = _make_db()
    content = b"test content"
    sha = hashlib.sha256(content).hexdigest()
    conn.execute(
        "INSERT INTO sources (doc_id, title, source_url, source_kind, sha256, status) "
        "VALUES ('D01', 'QC1', 'https://school.edu.vn/qc.pdf', 'url', ?, 'ACTIVE')",
        (sha,),
    )
    conn.commit()

    events: list[dict] = []

    def strict_audit(**kwargs: object) -> None:
        allowed = {"case_id", "actor", "action", "input_ref", "reason"}
        bad_keys = set(kwargs.keys()) - allowed
        assert not bad_keys, f"Audit nhận kwargs ngoài contract: {bad_keys}"
        events.append(kwargs)

    def dummy_head(url: str) -> HeadInfo:
        return HeadInfo(
            url=url, etag=None, last_modified=None, content_length=None, accessible=True
        )

    poll_sources_from_db(
        conn,
        head_checker=dummy_head,
        body_fetcher=lambda _: content,
        audit_fn=strict_audit,
    )
    assert len(events) == 1
    assert events[0]["action"] == "SOURCE_RECHECKED"


# ─── Test 12: Escalate from pending ────────────────────────────────────
def test_escalate_from_pending() -> None:
    draft = DraftReply(
        subject="Re: test",
        body="Trả lời test",
        citations=[],
        grounded=True,
        guard_failures=[],
    )
    record = schedule_dispatch("case-esc-test", draft, countdown_seconds=60)
    assert record.status == CaseStatus.PENDING_SEND

    ok, _msg = escalate_from_pending("case-esc-test", actor="ADMIN:staff")
    assert ok is True
    assert get_dispatch_record("case-esc-test").status == CaseStatus.AWAITING_HUMAN

    # After escalate, dispatch must fail
    ok2, _msg2 = dispatch_case("case-esc-test", force=True)
    assert ok2 is False


# ─── Test 13: Cancel send within countdown ─────────────────────────────
def test_cancel_send_within_countdown() -> None:
    draft = DraftReply(
        subject="Re: test",
        body="Trả lời",
        citations=[],
        grounded=True,
        guard_failures=[],
    )
    schedule_dispatch("case-cancel-test", draft, countdown_seconds=300)
    ok, _msg = cancel_send("case-cancel-test", actor="ADMIN:staff", reason="Phát hiện sai sót")
    assert ok is True
    assert get_dispatch_record("case-cancel-test").status == CaseStatus.CANCELLED
