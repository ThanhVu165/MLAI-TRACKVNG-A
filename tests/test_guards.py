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
    # E02: Hỏi học phí hoàn lại khi rút môn
    (
        "Hỏi về hoàn học phí rút môn",
        "Dạ cho em hỏi nếu sinh viên xin rút môn học trong 4 tuần đầu tiên thì được hoàn trả bao nhiêu phần trăm học phí đã đóng ạ? Em cảm ơn.",
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
    with patch("core.pipeline.extract_facts", side_effect=TimeoutError("LLM call timed out after 20s")):
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
    empty_ev = EvidenceResult(status=EvidenceStatus.NO_AUTHORITATIVE_SOURCE, chunks=[], failed_checks=["No chunks retrieved"])
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
