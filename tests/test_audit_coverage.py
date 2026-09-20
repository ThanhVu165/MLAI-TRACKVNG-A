from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from core.dispatch import schedule_dispatch
from core.pipeline import process_case
from core.types import (
    CaseInput,
    CaseStatus,
    Decision,
    DraftReply,
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
    logged_records: list[dict[str, Any]] = []
    mock_audit = MagicMock()

    # Chữ ký keyword-only nghiêm ngặt khớp Mục 5.3 spec. Nếu bất kỳ hàm nào gọi sai kwarg sẽ ném TypeError ngay.
    def strict_log_event(
        *,
        case_id: str,
        actor: str,
        action: str,
        rule_id: str | None = None,
        input_ref: str | None = None,
        output_ref: str | None = None,
        reason: str | None = None,
        sources: list[str] | None = None,
        corpus_version: str | None = None,
    ) -> None:
        logged_actions.append(action)
        logged_records.append(
            {
                "case_id": case_id,
                "actor": actor,
                "action": action,
                "rule_id": rule_id,
                "input_ref": input_ref,
                "output_ref": output_ref,
                "reason": reason,
                "sources": sources,
                "corpus_version": corpus_version,
            }
        )

    mock_audit.log_event.side_effect = strict_log_event

    with patch.dict("sys.modules", {"infra.audit": mock_audit}):
        from core.controls import (
            cancel_send as ctrl_cancel_send,
        )
        from core.controls import (
            override_decision as ctrl_override,
        )
        from core.controls import (
            pause_automation,
            rerun_case,
            resume_automation,
        )
        from core.explain import explain_plainly
        from core.resume import resume_after_human

        # 1. Tiếp nhận và xử lý case
        inp = _make_routine_input()
        res = process_case(inp)
        assert res.status == CaseStatus.PENDING_SEND

        # 2. Lập lịch gửi dispatch
        draft = res.draft or DraftReply(
            subject="Subj", body="Body", citations=[], grounded=True, guard_failures=[]
        )
        schedule_dispatch("c_audit_01", draft)

        # 3. Chuyên viên hủy gửi
        ctrl_cancel_send("c_audit_01", actor="ADMIN:ChuyenVien1", reason="Hủy để kiểm tra")

        # 4. Tạm dừng / Tiếp tục tự động hóa
        pause_automation(actor="ADMIN:system", reason="Bảo trì hệ thống")
        resume_automation(actor="ADMIN:system")

        # 5. Ghi đè quyết định
        ctrl_override(
            case_id=res.case_id,
            new_decision=Decision.ESCALATE,
            actor="ADMIN:ChuyenVien1",
            reason="Chuyển sang cần duyệt",
        )

        # 6. Tiếp tục sau can thiệp của con người
        resume_after_human(
            case_id=res.case_id, human_choice="Đồng ý", human_reason="Lý do hợp lệ", actor="HUMAN"
        )

        # 7. Giải thích quyết định
        explain_text = explain_plainly(res.case_id)
        assert len(explain_text) > 0

        # 8. Chạy lại case
        rerun_case(case_id=res.case_id, actor="ADMIN:ChuyenVien1")

    # Khẳng định các action kiểm toán cốt lõi đều được ghi nhận
    assert "EVIDENCE_RETRIEVED" in logged_actions
    assert "EVIDENCE_VALIDATED" in logged_actions
    assert "POLICY_DECIDED" in logged_actions
    assert "CASE_PROCESSED" in logged_actions
    assert "SEND_SCHEDULED" in logged_actions
    assert "CANCEL_SEND" in logged_actions
    assert "AUTOMATION_PAUSED" in logged_actions
    assert "AUTOMATION_RESUMED" in logged_actions
    assert "DECISION_OVERRIDDEN" in logged_actions
    assert "CASE_RESUMED" in logged_actions
    assert "EXPLAIN_REQUESTED" in logged_actions
    assert "CASE_RERUN" in logged_actions


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
