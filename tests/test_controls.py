from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.controls import (
    is_automation_paused,
    override_decision,
    pause_automation,
    rerun_case,
    resume_automation,
)
from core.pipeline import process_case
from core.types import (
    CaseInput,
    CaseStatus,
    Decision,
    EscalationType,
)


def _make_routine_input() -> CaseInput:
    return CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Cho em hỏi khi nào hết hạn rút môn học kỳ này ạ?",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )


def test_pause_and_resume_automation() -> None:
    # Ban đầu không pause
    resume_automation()
    assert is_automation_paused() is False

    # Chạy email thường quy -> PENDING_SEND
    inp = _make_routine_input()
    res1 = process_case(inp)
    assert res1.status == CaseStatus.PENDING_SEND
    assert res1.decision.decision == Decision.AUTO_REPLY

    # Bật Pause
    pause_automation(actor="ADMIN:LeaderCTSV")
    assert is_automation_paused() is True

    # Chạy email thường quy khi Pause -> dừng tại hàng chờ AWAITING_HUMAN
    res2 = process_case(inp)
    assert res2.status == CaseStatus.AWAITING_HUMAN
    assert (
        res2.decision.decision == Decision.AUTO_REPLY
    )  # Quyết định vẫn là AUTO_REPLY nhưng dừng lại không gửi

    # Khôi phục bình thường
    resume_automation(actor="ADMIN:LeaderCTSV")
    assert is_automation_paused() is False

    res3 = process_case(inp)
    assert res3.status == CaseStatus.PENDING_SEND


def test_override_decision_empty_reason_raises() -> None:
    inp = _make_routine_input()
    res = process_case(inp)

    with pytest.raises(ValueError, match="Lý do ghi đè"):
        override_decision(res, Decision.ESCALATE, reason="   ")


def test_override_decision_same_decision_raises() -> None:
    inp = _make_routine_input()
    res = process_case(inp)

    with pytest.raises(ValueError, match="trùng với quyết định hiện tại"):
        override_decision(res, Decision.AUTO_REPLY, reason="Vẫn muốn giữ nguyên")


def test_override_decision_auto_to_escalate() -> None:
    inp = _make_routine_input()
    res = process_case(inp)
    assert res.decision.decision == Decision.AUTO_REPLY

    overridden = override_decision(
        res,
        new_decision=Decision.ESCALATE,
        new_escalation_type=EscalationType.AUTHORITY_REQUIRED,
        reason="Chuyên viên phát hiện sinh viên này đang trong diện tạm đình chỉ",
        actor="ADMIN:ChuyenVien1",
    )

    assert overridden.decision.decision == Decision.ESCALATE
    assert overridden.decision.escalation_type == EscalationType.AUTHORITY_REQUIRED
    assert overridden.status == CaseStatus.AWAITING_HUMAN
    assert overridden.decision.rule_id == "P01_OVERRIDE"
    assert "tạm đình chỉ" in overridden.decision.reason
    assert "ADMIN:ChuyenVien1" in overridden.decision.reason


def test_rerun_case_diff() -> None:
    inp = _make_routine_input()
    original_res = process_case(inp)

    result, diff = rerun_case(original_res, inp, actor="ADMIN:Tester")

    assert diff["case_id"] == original_res.case_id
    assert "rerun_case_id" in diff
    assert "decision_changed" in diff
    assert isinstance(diff["citations_added"], list)
    assert isinstance(diff["citations_removed"], list)
    assert result.case_id == diff["rerun_case_id"]
