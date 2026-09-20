# ==============================================================================
# KHÔNG ĐƯỢC XÓA - CRITICAL INTEGRITY TESTS (Mục 8.0 spec & Task A-25)
# Bộ hai bài kiểm tra sống còn để bảo vệ điểm tiêu chí 7:
# 1. test_no_over_escalation: Case thường quy PHẢI ra AUTO_REPLY, không được đẩy bừa cho người.
# 2. test_no_fail_open: Khi gặp bất kỳ lỗi kỹ thuật nào, hệ thống PHẢI fail-safe về ESCALATE,
#    TUYỆT ĐỐI KHÔNG BAO GIỜ tự động gửi (fail-open) trả lời bậy cho sinh viên.
# ==============================================================================

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.pipeline import process_case
from core.types import (
    CaseInput,
    CaseStatus,
    Decision,
    DraftReply,
    EvidenceResult,
    EvidenceStatus,
    Extraction,
)

# ------------------------------------------------------------------------------
# Test sống còn 1: Chống Over-Escalation
# ------------------------------------------------------------------------------

ROUTINE_CASES = [
    # E01: Hỏi thời hạn rút môn thông thường
    (
        "Hỏi thời hạn rút môn",
        "Kính gửi thầy cô phòng DSA, em muốn hỏi thời hạn rút học phần của học kỳ chính là vào tuần thứ mấy của học kỳ ạ? Em xin cảm ơn quý thầy cô.",
    ),
    # E02: Hỏi hạn chót rút học phần thông thường
    (
        "Hỏi về hạn chót rút học phần",
        "Dạ cho em hỏi sinh viên được phép nộp đơn xin rút học phần muộn nhất vào tuần thứ mấy của học kỳ chính ạ? Em cảm ơn.",
    ),
    # E03: Hỏi quy trình rút môn trực tuyến
    (
        "Quy trình rút môn học trực tuyến",
        "Em chào anh/chị, cho em hỏi thủ tục và quy trình thực hiện rút môn học trực tuyến trên cổng portal diễn ra như thế nào ạ?",
    ),
]


@pytest.mark.parametrize(("subject", "body"), ROUTINE_CASES)
def test_no_over_escalation(subject: str, body: str) -> None:
    """KHÔNG ĐƯỢC XÓA: Khẳng định 100% case thường quy rõ ràng PHẢI ra AUTO_REPLY.

    Nếu tác tử chuyển tiếp mọi trường hợp lên chuyên viên để 'né trách nhiệm',
    sẽ bị trừ điểm nặng nề do vi phạm cam kết tự động hóa của hệ thống.
    """
    inp = CaseInput(
        sender="sinhvien@school.edu.vn",
        subject=subject,
        body=body,
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    result = process_case(inp)

    assert result.decision.decision == Decision.AUTO_REPLY, (
        f"Lỗi Over-Escalation: Case thường quy '{subject}' bị chuyển tiếp thay vì tự động trả lời! "
        f"Rule ID: {result.decision.rule_id}, Lý do: {result.decision.reason}"
    )
    assert result.status == CaseStatus.PENDING_SEND
    assert result.draft is not None
    assert result.draft.grounded is True


# ------------------------------------------------------------------------------
# Test sống còn 2: Chống Fail-Open (Fail-Safe Guarantee)
# ------------------------------------------------------------------------------


def test_no_fail_open_on_llm_timeout() -> None:
    """KHÔNG ĐƯỢC XÓA: Khi LLM timeout, kết quả PHẢI là ESCALATE, KHÔNG ĐƯỢC AUTO_REPLY."""
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Kính chào thầy cô phòng DSA, cho em hỏi hạn chót rút học phần học kỳ này là khi nào ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    with patch(
        "core.pipeline.extract_facts", side_effect=TimeoutError("LLM call timed out after 20s")
    ):
        res = process_case(inp)

    assert res.decision.decision == Decision.ESCALATE
    assert res.decision.rule_id == "P04"
    assert res.status == CaseStatus.ERROR


def test_no_fail_open_on_malformed_llm_json() -> None:
    """KHÔNG ĐƯỢC XÓA: Khi LLM trả về chuỗi JSON hỏng, kết quả PHẢI là ESCALATE."""
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Kính chào thầy cô phòng DSA, cho em hỏi hạn chót rút học phần học kỳ này là khi nào ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    bad_extraction = Extraction(
        language="vi",
        requests=[],
        critical_facts={},
        missing_critical_facts=[],
        injection_suspected=False,
        raw_json="{bad json}",
        llm_error="Failed to parse JSON after retry",
    )
    with patch("core.pipeline.extract_facts", return_value=bad_extraction):
        res = process_case(inp)

    assert res.decision.decision == Decision.ESCALATE
    assert res.decision.rule_id in ("P03", "P04")


def test_no_fail_open_on_empty_corpus() -> None:
    """KHÔNG ĐƯỢC XÓA: Khi corpus không có căn cứ hoặc không tìm thấy chunk, PHẢI là ESCALATE."""
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Kính chào thầy cô phòng DSA, cho em hỏi hạn chót rút học phần học kỳ này là khi nào ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    empty_ev = EvidenceResult(
        status=EvidenceStatus.NO_AUTHORITATIVE_SOURCE,
        chunks=[],
        failed_checks=["No chunks retrieved"],
    )
    with (
        patch("core.pipeline.retrieve_evidence", return_value=[]),
        patch("core.pipeline.validate_evidence", return_value=empty_ev),
    ):
        res = process_case(inp)

    assert res.decision.decision == Decision.ESCALATE
    assert res.decision.rule_id in ("P02", "P03", "P04")


def test_no_fail_open_on_groundedness_guard_failure() -> None:
    """KHÔNG ĐƯỢC XÓA: Khi Groundedness Guard phát hiện bịa số liệu, PHẢI hạ cấp về ESCALATE."""
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Kính chào thầy cô phòng DSA, cho em hỏi hạn chót rút học phần học kỳ này là khi nào ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    # Mô phỏng bản nháp sinh ra có số liệu bịa đặt không có trong căn cứ
    hallucinated_draft = DraftReply(
        subject="Re: Hỏi thời hạn rút môn",
        body="Hạn chót là ngày 31/12/2099 và số tiền là 999.000.000 VNĐ [chunk_cw_01].",
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
    )
    with patch("core.pipeline.generate_reply", return_value=hallucinated_draft):
        res = process_case(inp)

    assert res.decision.decision == Decision.ESCALATE
    assert res.decision.rule_id == "P04"
    assert res.draft is not None
    assert res.draft.grounded is False


def test_extract_internal_llm_exception_fails_safe() -> None:
    """Kiểm tra Item 1: Khi infra.llm tồn tại nhưng ném Exception thật bên trong extract.py.

    Phải trả về Extraction có llm_error, và pipeline phải fail-safe về ESCALATE (P04),
    KHÔNG ĐƯỢC rơi về heuristic rồi ra AUTO_REPLY.
    """
    import sys
    from unittest.mock import MagicMock

    from core.extract import extract_facts

    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Kính chào thầy cô phòng DSA, cho em hỏi hạn chót rút học phần học kỳ này là khi nào ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )

    mock_infra_llm = MagicMock()
    mock_infra_llm.call_json.side_effect = RuntimeError(
        "Database/API connection failed inside call_json"
    )

    with patch.dict(sys.modules, {"infra": MagicMock(), "infra.llm": mock_infra_llm}):
        extraction = extract_facts(inp.body, inp.subject, "c_test", language="vi")
        assert extraction.llm_error == "Database/API connection failed inside call_json"

        # Chạy qua pipeline thật
        res = process_case(inp)
        assert res.decision.decision == Decision.ESCALATE
        assert res.decision.rule_id in ("P03", "P04")


def test_groundedness_guard_catches_number_1_and_2() -> None:
    """Kiểm tra Item 3: Không bỏ qua số 1 hoặc 2.

    Khi draft nói 'thời hạn là 1 tuần' mà evidence chỉ nói '8 tuần',
    guard PHẢI bắt được lỗi hallucinated_number_1.
    """
    from datetime import date

    from core.ground_guard import validate_groundedness
    from core.types import ChunkLabel, Domain, EvidenceChunk

    chunk = EvidenceChunk(
        chunk_id="chunk_01",
        doc_id="qd_01",
        breadcrumb="Quy định > Rút môn",
        text="Thời hạn nộp đơn rút môn học là 8 tuần kể từ ngày bắt đầu học kỳ chính.",
        domain=Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.9,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["all"],
        transitional_clause=False,
        conflict_flag=False,
    )
    ev_res = EvidenceResult(
        status=EvidenceStatus.OK,
        chunks=[chunk],
        failed_checks=[],
    )
    # Draft bịa số 1
    draft = DraftReply(
        subject="Re: Rút môn",
        body="Thời hạn nộp đơn rút môn học là 1 tuần kể từ ngày bắt đầu học kỳ [chunk_01].",
        citations=["chunk_01"],
        grounded=True,
        guard_failures=[],
    )

    passed, failures = validate_groundedness(draft, ev_res)
    assert passed is False
    assert any("hallucinated_number_1" in f for f in failures)


def test_dispatch_paused_and_override_cancels_send() -> None:
    """Kiểm tra Item 2: Pause và Override ngăn chặn dispatch gửi thư."""
    from core.controls import override_decision, pause_automation, resume_automation
    from core.dispatch import _DISPATCH_REGISTRY, dispatch_case

    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Kính chào thầy cô phòng DSA, cho em hỏi hạn chót rút học phần học kỳ này là khi nào ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    res = process_case(inp)
    assert res.decision.decision == Decision.AUTO_REPLY
    case_id = res.case_id

    # 1. Test pause
    pause_automation(actor="ADMIN:test", reason="Testing pause")
    ok, msg = dispatch_case(case_id, force=True)
    assert ok is False
    assert "tạm dừng" in msg
    assert _DISPATCH_REGISTRY[case_id].status == CaseStatus.PENDING_SEND

    # 2. Test resume
    resume_automation(actor="ADMIN:test")

    # 3. Test override sang ESCALATE
    override_decision(
        case_id=case_id,
        new_decision=Decision.ESCALATE,
        actor="SPECIALIST:test",
        reason="Cần kiểm tra",
    )
    ok2, _ = dispatch_case(case_id, force=True)
    assert ok2 is False
    assert _DISPATCH_REGISTRY[case_id].status == CaseStatus.CANCELLED
