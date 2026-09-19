from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from core.controls import override_decision
from core.dispatch import cancel_send, schedule_dispatch
from core.pipeline import process_case
from core.resume import resume_after_decision
from core.types import (
    CaseInput,
    CaseStatus,
    Decision,
    DraftReply,
    EvidenceResult,
    EvidenceStatus,
)


def _make_routine_input() -> CaseInput:
    return CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn rút môn",
        body="Cho em hỏi khi nào hết hạn rút môn học kỳ 1 ạ?",
        received_at=datetime.now(timezone.utc),
        channel="inbox",
    )


def test_step_latencies_coverage() -> None:
    """Khẳng định mọi bước từ R0 đến R14 đều được đo lường thời gian (Task A-24)."""
    inp = _make_routine_input()
    res = process_case(inp)

    required_steps = [
        "R0_intake",
        "R1_sanitize",
        "R2_extract",
        "R3_lock",
        "R4_retrieve",
        "R5_evidence",
        "R6_policy",
        "R7_R8_generate_guard",
        "R9_lifecycle",
        "R13_dispatch",
        "R14_audit",
    ]

    for step in required_steps:
        assert step in res.step_latencies_ms, f"Thiếu đo lường latency cho bước {step}"
        assert res.step_latencies_ms[step] >= 0


def test_audit_events_logged_on_state_transitions() -> None:
    logged_actions: list[str] = []
    mock_audit = MagicMock()

    def fake_log_event(*args: Any, **kwargs: Any) -> None:
        action = kwargs.get("action") or (args[2] if len(args) > 2 else "UNKNOWN")
        logged_actions.append(action)

    mock_audit.log_event.side_effect = fake_log_event

    with patch.dict("sys.modules", {"infra.audit": mock_audit}):
        # 1. Tiếp nhận và xử lý case
        inp = _make_routine_input()
        res = process_case(inp)
        assert res.status == CaseStatus.PENDING_SEND

        # 2. Lập lịch gửi dispatch
        draft = res.draft or DraftReply(subject="Subj", body="Body", citations=[], grounded=True, guard_failures=[])
        schedule_dispatch("c_audit_01", draft)

        # 3. Chuyên viên hủy gửi
        cancel_send("c_audit_01", actor="ADMIN:ChuyenVien1")

        # 4. Ghi đè quyết định
        override_decision(res, Decision.ESCALATE, reason="Chuyển sang cần duyệt", actor="ADMIN:ChuyenVien1")

        # 5. Tiếp tục sau quyết định
        ev = res.evidence or EvidenceResult(status=EvidenceStatus.OK, chunks=[], failed_checks=[])
        resume_after_decision("c_audit_01", choice="Đồng ý", reason="Lý do hợp lệ", evidence_res=ev, inp=inp)

    # Khẳng định các action kiểm toán cốt lõi đều được ghi nhận
    assert "EVIDENCE_RETRIEVED" in logged_actions
    assert "EVIDENCE_VALIDATED" in logged_actions
    assert "POLICY_DECIDED" in logged_actions
    assert "CASE_PROCESSED" in logged_actions
    assert "SEND_SCHEDULED" in logged_actions
    assert "CANCEL_SEND" in logged_actions
    assert "DECISION_OVERRIDDEN" in logged_actions
    assert "CASE_RESUMED" in logged_actions


def test_pipeline_latency_benchmark_p95() -> None:
    """Benchmark độ trễ p95 của pipeline, đảm bảo < 2 giây trong môi trường kiểm thử (SLA yêu cầu < 25s)."""
    latencies_ms: list[float] = []
    inp = _make_routine_input()

    for _ in range(15):
        t0 = time.perf_counter()
        res = process_case(inp)
        t1 = time.perf_counter()
        assert res.status in (CaseStatus.PENDING_SEND, CaseStatus.AWAITING_HUMAN)
        latencies_ms.append((t1 - t0) * 1000)

    latencies_ms.sort()
    # Tính p95 (phần tử thứ 95%)
    p95_idx = int(len(latencies_ms) * 0.95)
    p95_latency = latencies_ms[p95_idx]

    # Khẳng định p95 cực nhanh (thường < 50ms)
    assert p95_latency < 2000, f"Độ trễ p95 vượt quá 2000ms: {p95_latency:.2f}ms"
