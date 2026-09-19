from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from core.explain import FORBIDDEN_TECH_TERMS, explain_decision
from core.pipeline import process_case
from core.types import (
    CaseInput,
    Decision,
    PipelineResult,
)


def _make_sample_result(decision: Decision) -> PipelineResult:
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi hạn rút học phần",
        body="Kính chào thầy cô, em muốn hỏi thời hạn rút học phần của học kỳ này là khi nào ạ? Em xin cảm ơn.",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    res = process_case(inp)
    return res


def test_explain_auto_reply_non_technical() -> None:
    """Test giải thích cho case AUTO_REPLY: văn phong thân thiện, không từ kỹ thuật, <= 120 từ."""
    res = _make_sample_result(Decision.AUTO_REPLY)
    assert res.decision.decision == Decision.AUTO_REPLY

    exp = explain_decision(res)
    words = exp.split()
    assert len(words) <= 120, f"Văn bản quá dài ({len(words)} từ > 120 từ)"

    # Khẳng định trả lời đủ 4 phần (hệ thống làm gì, vì sao, căn cứ văn bản, bước tiếp theo)
    assert any(k in exp.lower() for k in ["hệ thống đã", "tiếp nhận", "soạn thảo"])
    assert any(k in exp.lower() for k in ["quy định", "căn cứ"])
    assert any(k in exp.lower() for k in ["hàng chờ", "chuyên viên", "gửi"])

    # Khẳng định không có từ kỹ thuật cấm
    exp_lower = exp.lower()
    for term in FORBIDDEN_TECH_TERMS:
        assert term not in exp_lower, f"Phát hiện thuật ngữ kỹ thuật cấm '{term}' trong lời giải thích!"


def test_explain_escalate_non_technical() -> None:
    """Test giải thích cho case ESCALATE."""
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Xin rút môn sau hạn",
        body="Kính chào thầy cô, em bị ốm nằm viện nên muốn xin rút môn sau hạn có được không ạ? Nhờ thầy duyệt giúp em.",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    res = process_case(inp)
    assert res.decision.decision == Decision.ESCALATE

    exp = explain_decision(res)
    words = exp.split()
    assert len(words) <= 120

    # Khẳng định không có từ kỹ thuật cấm
    exp_lower = exp.lower()
    for term in FORBIDDEN_TECH_TERMS:
        assert term not in exp_lower, f"Phát hiện thuật ngữ cấm '{term}' trong lời giải thích!"


def test_explain_logs_audit_event() -> None:
    """Khẳng định gọi audit log EXPLAIN_REQUESTED khi người dùng xem giải thích."""
    res = _make_sample_result(Decision.AUTO_REPLY)
    logged_actions: list[str] = []

    mock_audit = MagicMock()
    def fake_log(*args: Any, **kwargs: Any) -> None:
        action = kwargs.get("action") or (args[2] if len(args) > 2 else "UNKNOWN")
        logged_actions.append(action)
    mock_audit.log_event.side_effect = fake_log

    with patch.dict("sys.modules", {"infra.audit": mock_audit}):
        explain_decision(res, actor="USER:ChuyenVien1")

    assert "EXPLAIN_REQUESTED" in logged_actions
