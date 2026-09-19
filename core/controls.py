from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from core.types import (
    CaseInput,
    CaseStatus,
    Decision,
    EscalationType,
    PipelineResult,
    PolicyDecision,
)

logger = logging.getLogger(__name__)

# Cờ điều khiển trạng thái tự động hóa toàn cục
_AUTOMATION_PAUSED = False


def is_automation_paused() -> bool:
    """Kiểm tra xem hệ thống có đang ở chế độ tạm dừng tự động hóa không."""
    return _AUTOMATION_PAUSED


def pause_automation(actor: str = "ADMIN:system") -> bool:
    """Tạm dừng tự động gửi phản hồi: Mọi case sẽ dừng tại hàng chờ chuyên viên."""
    global _AUTOMATION_PAUSED
    _AUTOMATION_PAUSED = True
    _log_control_audit(actor, "AUTOMATION_PAUSED", "Đã bật chế độ tạm dừng tự động hóa khẩn cấp")
    logger.warning("Quản trị viên %s đã tạm dừng tự động hóa toàn hệ thống.", actor)
    return True


def resume_automation(actor: str = "ADMIN:system") -> bool:
    """Khôi phục chế độ tự động gửi phản hồi bình thường."""
    global _AUTOMATION_PAUSED
    _AUTOMATION_PAUSED = False
    _log_control_audit(actor, "AUTOMATION_RESUMED", "Đã khôi phục chế độ tự động hóa bình thường")
    logger.info("Quản trị viên %s đã khôi phục tự động hóa.", actor)
    return True


def override_decision(
    result: PipelineResult,
    new_decision: Decision,
    reason: str,
    *,
    new_escalation_type: EscalationType | None = None,
    actor: str = "ADMIN:operator",
) -> PipelineResult:
    """Ghi đè quyết định của hệ thống (Task A-22 & Tiêu chí 6).

    Bắt buộc phải có lý do (reason) giải thích việc ghi đè.
    Cập nhật trạng thái case và ghi nhận audit log chi tiết.
    """
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("Lý do ghi đè (reason) là bắt buộc, không được để trống theo quy định.")

    old_decision = result.decision.decision
    if old_decision == new_decision:
        raise ValueError(f"Quyết định mới ({new_decision.value}) trùng với quyết định hiện tại.")

    # Xác định trạng thái vòng đời mới
    if new_decision == Decision.AUTO_REPLY:
        new_status = CaseStatus.PENDING_SEND
        rule_id = "P05_OVERRIDE"
    elif new_decision == Decision.ESCALATE:
        new_status = CaseStatus.AWAITING_HUMAN
        rule_id = "P01_OVERRIDE"
        if new_escalation_type is None:
            new_escalation_type = EscalationType.AUTHORITY_REQUIRED
    else:
        new_status = CaseStatus.INVALID_INPUT
        rule_id = "P00_OVERRIDE"

    overridden_policy = PolicyDecision(
        decision=new_decision,
        escalation_type=new_escalation_type,
        rule_id=rule_id,
        reason=f"[GHI ĐÈ BỞI {actor}]: {clean_reason}",
        evidence_ids=result.decision.evidence_ids,
        corpus_version=result.decision.corpus_version,
    )

    updated_result = replace(
        result,
        decision=overridden_policy,
        status=new_status,
    )

    _log_control_audit(
        actor,
        "DECISION_OVERRIDDEN",
        f"Case {result.case_id}: {old_decision.value} -> {new_decision.value}; Lý do: {clean_reason}",
    )
    return updated_result


def rerun_case(
    original_result: PipelineResult,
    inp: CaseInput,
    *,
    new_corpus_version: str | None = None,
    actor: str = "ADMIN:operator",
) -> dict[str, Any]:
    """Chạy lại case trên phiên bản quy định mới và sinh bản phân tích sai khác (diff) (Task A-22)."""
    from core.pipeline import process_case

    # Chạy lại case bằng pipeline chính quy
    new_result = process_case(inp, actor=actor)

    # Phân tích sai khác (Diff analysis)
    old_cits = set(original_result.decision.evidence_ids)
    new_cits = set(new_result.decision.evidence_ids)

    diff: dict[str, Any] = {
        "case_id": original_result.case_id,
        "rerun_case_id": new_result.case_id,
        "decision_changed": original_result.decision.decision != new_result.decision.decision,
        "old_decision": original_result.decision.decision.value,
        "new_decision": new_result.decision.decision.value,
        "rule_id_changed": original_result.decision.rule_id != new_result.decision.rule_id,
        "old_rule_id": original_result.decision.rule_id,
        "new_rule_id": new_result.decision.rule_id,
        "citations_added": sorted(new_cits - old_cits),
        "citations_removed": sorted(old_cits - new_cits),
        "corpus_version_before": original_result.corpus_version,
        "corpus_version_after": new_result.corpus_version,
        "new_result": new_result,
    }

    _log_control_audit(
        actor,
        "CASE_RERUN",
        f"Chạy lại case {original_result.case_id} -> {new_result.case_id}; Quyết định đổi: {diff['decision_changed']}",
    )
    return diff


def _log_control_audit(actor: str, action: str, detail: str) -> None:
    """Ghi nhận audit event quản trị nếu infra khả dụng."""
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]
        log_event(
            case_id="GLOBAL_CONTROL",
            actor=actor,
            action=action,
            output_ref=detail,
            created_at=datetime.now(timezone.utc),
        )
    except (ImportError, Exception):  # noqa: BLE001, S110
        pass
