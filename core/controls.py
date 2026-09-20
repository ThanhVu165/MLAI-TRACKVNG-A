from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Self

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


def pause_automation(actor: str = "ADMIN:system", reason: str = "") -> None:
    """Tạm dừng tự động gửi phản hồi: Mọi case sẽ dừng tại hàng chờ chuyên viên (Mục 5.3 spec)."""
    global _AUTOMATION_PAUSED
    _AUTOMATION_PAUSED = True
    _log_control_audit(
        actor, "AUTOMATION_PAUSED", reason or "Đã bật chế độ tạm dừng tự động hóa khẩn cấp"
    )
    logger.warning("Quản trị viên %s đã tạm dừng tự động hóa. Lý do: %s", actor, reason)


def resume_automation(actor: str = "ADMIN:system") -> None:
    """Khôi phục chế độ tự động gửi phản hồi bình thường (Mục 5.3 spec)."""
    global _AUTOMATION_PAUSED
    _AUTOMATION_PAUSED = False
    _log_control_audit(actor, "AUTOMATION_RESUMED", "Đã khôi phục chế độ tự động hóa bình thường")
    logger.info("Quản trị viên %s đã khôi phục tự động hóa.", actor)


def cancel_send(case_id: str, actor: str = "HUMAN", reason: str = "") -> None:
    """R9a: Hủy gửi email đang trong hàng chờ đếm ngược (Mục 5.3 spec)."""
    from core.dispatch import cancel_send as dispatch_cancel_send

    dispatch_cancel_send(case_id, actor=actor, reason=reason)


class RerunResult(tuple):
    """Tuple (PipelineResult, dict) hỗ trợ tương thích ngược truy cập như dict."""

    def __new__(cls, result: PipelineResult, diff: dict[str, Any]) -> Self:
        return super().__new__(cls, (result, diff))

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self[1][key]
        return super().__getitem__(key)

    def __contains__(self, key: Any) -> bool:
        return key in self[1]


def override_decision(
    case_id: str | PipelineResult,
    new_decision: Decision,
    actor: str = "HUMAN",
    reason: str = "",
    *,
    new_escalation_type: EscalationType | None = None,
    **kwargs: Any,
) -> PipelineResult:
    """Ghi đè quyết định của hệ thống (Mục 5.3 spec & Task A-22 & Tiêu chí 6).

    Bắt buộc phải có lý do (reason) giải thích việc ghi đè.
    Đồng bộ hủy gửi trong _DISPATCH_REGISTRY nếu quyết định mới không phải AUTO_REPLY.
    """
    from core.pipeline import get_stored_case, store_case

    if isinstance(case_id, PipelineResult):
        result = case_id
        cid = result.case_id
    else:
        cid = str(case_id)
        stored = get_stored_case(cid)
        if stored is None:
            raise ValueError(f"Không tìm thấy case {cid} để ghi đè.")
        result = stored[1]

    # Hỗ trợ reason truyền qua kwargs nếu có
    if not reason and "reason" in kwargs:
        reason = kwargs["reason"]

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("Lý do ghi đè (reason) là bắt buộc, không được để trống theo quy định.")

    old_decision = result.decision.decision
    if old_decision == new_decision:
        raise ValueError(f"Quyết định mới ({new_decision.value}) trùng với quyết định hiện tại.")

    # Nếu đổi khỏi AUTO_REPLY -> Hủy gửi trong hàng chờ dispatch ngay lập tức
    if new_decision != Decision.AUTO_REPLY:
        cancel_send(
            cid, actor=actor, reason=f"Ghi đè quyết định sang {new_decision.value}: {clean_reason}"
        )

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
        reason=f"Quản trị viên ({actor}) ghi đè: {clean_reason}",
        evidence_ids=result.decision.evidence_ids,
        corpus_version=result.decision.corpus_version,
    )

    updated_result = replace(
        result,
        decision=overridden_policy,
        status=new_status,
    )

    stored = get_stored_case(cid)
    if stored is not None:
        store_case(cid, stored[0], updated_result)

    _log_control_audit(
        actor,
        "DECISION_OVERRIDDEN",
        f"Case {cid}: {old_decision.value} -> {new_decision.value}; Lý do: {clean_reason}",
        case_id=cid,
    )
    return updated_result


def rerun_case(
    case_id: str | PipelineResult,
    *args: Any,
    actor: str = "ADMIN:operator",
    inp: CaseInput | None = None,
    new_corpus_version: str | None = None,
    **kwargs: Any,
) -> tuple[PipelineResult, dict[str, Any]]:
    """Chạy lại case trên phiên bản quy định mới và sinh bản phân tích sai khác (diff) (Mục 5.3 spec)."""
    from core.pipeline import get_stored_case, process_case

    # Phân giải đối số linh hoạt
    for arg in args:
        if isinstance(arg, CaseInput):
            inp = arg
        elif isinstance(arg, str):
            actor = arg
    if "actor" in kwargs:
        actor = kwargs["actor"]
    if "inp" in kwargs:
        inp = kwargs["inp"]

    if isinstance(case_id, PipelineResult):
        original_result = case_id
        cid = original_result.case_id
    else:
        cid = str(case_id)
        stored = get_stored_case(cid)
        if stored is None and inp is None:
            raise ValueError(f"Không tìm thấy case {cid} để chạy lại.")
        original_result = stored[1] if stored else None

    if inp is None:
        stored = get_stored_case(cid)
        if stored is not None:
            inp = stored[0]
        else:
            raise ValueError(f"Không tìm thấy input của case {cid} để chạy lại.")

    # Chạy lại case bằng pipeline chính quy
    new_result = process_case(inp, actor=actor)

    # Phân tích sai khác (Diff analysis)
    old_cits = set(original_result.decision.evidence_ids) if original_result else set()
    new_cits = set(new_result.decision.evidence_ids)
    old_decision_val = original_result.decision.decision.value if original_result else "UNKNOWN"
    old_rule_id = original_result.decision.rule_id if original_result else "NONE"
    corpus_before = original_result.corpus_version if original_result else "UNKNOWN"

    diff: dict[str, Any] = {
        "case_id": cid,
        "rerun_case_id": new_result.case_id,
        "decision_changed": (original_result is not None)
        and (original_result.decision.decision != new_result.decision.decision),
        "old_decision": old_decision_val,
        "new_decision": new_result.decision.decision.value,
        "rule_id_changed": (original_result is not None)
        and (original_result.decision.rule_id != new_result.decision.rule_id),
        "old_rule_id": old_rule_id,
        "new_rule_id": new_result.decision.rule_id,
        "citations_added": sorted(new_cits - old_cits),
        "citations_removed": sorted(old_cits - new_cits),
        "corpus_version_before": corpus_before,
        "corpus_version_after": new_result.corpus_version,
        "new_result": new_result,
    }

    _log_control_audit(
        actor,
        "CASE_RERUN",
        f"Chạy lại case {cid} -> {new_result.case_id}; Quyết định đổi: {diff['decision_changed']}",
        case_id=cid,
    )
    return RerunResult(new_result, diff)


def _log_control_audit(actor: str, action: str, detail: str, case_id: str | None = None) -> None:
    """Ghi nhận audit event quản trị nếu infra khả dụng."""
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(
            case_id=case_id,
            actor=actor,
            action=action,
            output_ref=detail,
        )
    except ImportError:
        logger.debug("infra.audit chưa cấu hình — bỏ qua")
    except Exception:
        logger.exception("Ghi audit control thất bại")
