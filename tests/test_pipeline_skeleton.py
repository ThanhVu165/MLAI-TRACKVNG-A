from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from core.pipeline import process_case
from core.types import CaseInput, CaseStatus, Decision, EscalationType


def test_process_case_stub_success():
    inp = CaseInput(
        sender="sinhvien@university.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Cho em hỏi khi nào hết hạn rút môn học kỳ 1 ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )

    result = process_case(inp)

    # Khẳng định định danh và trạng thái
    assert result.case_id.startswith("c_")
    assert result.trace_id.startswith("tr_")
    assert result.status == CaseStatus.PENDING_SEND

    # Khẳng định quyết định stub P05 AUTO_REPLY
    assert result.decision.decision == Decision.AUTO_REPLY
    assert result.decision.rule_id == "P05"
    assert len(result.decision.evidence_ids) > 0

    # Khẳng định bản nháp tồn tại
    assert result.draft is not None
    assert len(result.draft.citations) > 0
    assert result.draft.citations[0].startswith("chunk_")
    assert result.draft.grounded is True

    # Khẳng định đo lường độ trễ các bước
    assert "R0_intake" in result.step_latencies_ms
    assert "R1_sanitize" in result.step_latencies_ms
    assert "R2_extract" in result.step_latencies_ms
    assert "R3_lock" in result.step_latencies_ms
    assert "R4_retrieve" in result.step_latencies_ms
    assert "R5_evidence" in result.step_latencies_ms
    assert "R6_policy" in result.step_latencies_ms
    assert "R9_lifecycle" in result.step_latencies_ms


def test_process_case_empty_body_invalid_input():
    inp = CaseInput(
        sender="sinhvien@university.edu.vn",
        subject="Hỏi thông tin",
        body="   ",
        received_at=datetime.now(timezone.utc),
        channel="inbox",
    )

    result = process_case(inp)
    assert result.status == CaseStatus.INVALID_INPUT
    assert result.decision.decision == Decision.INVALID_INPUT
    assert result.decision.rule_id == "P00"


def test_process_case_fail_safe_on_unexpected_exception():
    inp = CaseInput(
        sender="sinhvien@university.edu.vn",
        subject="Test lỗi",
        body="Email mô phỏng gây lỗi hệ thống đột xuất",
        received_at=datetime.now(timezone.utc),
        channel="verify",
    )

    # Mô phỏng một bước con ném Exception bất ngờ
    with patch("core.pipeline.extract_facts", side_effect=RuntimeError("Mô phỏng sập LLM")):
        result = process_case(inp)

    # KHÔNG ĐƯỢC NÉM EXCEPTION RA NGOÀI
    # Bắt buộc chuyển sang ESCALATE fail-safe P04
    assert result.status == CaseStatus.ERROR
    assert result.decision.decision == Decision.ESCALATE
    assert result.decision.escalation_type == EscalationType.FACT_UNRESOLVED
    assert result.decision.rule_id == "P04"
    assert "RuntimeError" in result.decision.reason
