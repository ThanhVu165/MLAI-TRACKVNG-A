from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.types import CaseStatus, DraftReply

logger = logging.getLogger(__name__)

# Thời gian đếm ngược mặc định (giây) trước khi tự động gửi
DISPATCH_COUNTDOWN_SECONDS = 60


@dataclass
class PendingDispatchRecord:
    case_id: str
    trace_id: str
    draft: DraftReply
    status: CaseStatus
    scheduled_at: float
    expires_at: float
    parent_case_id: str | None = None
    audit_trail: list[dict[str, str]] = field(default_factory=list)


# Registry quản lý các case đang trong hàng chờ dispatch (in-memory, đồng bộ với DB khi có infra)
_DISPATCH_REGISTRY: dict[str, PendingDispatchRecord] = {}


def schedule_dispatch(
    case_id: str,
    draft: DraftReply,
    trace_id: str = "",
    countdown_seconds: int = DISPATCH_COUNTDOWN_SECONDS,
) -> PendingDispatchRecord:
    """R9a: Lập lịch gửi tự động cho case sau thời gian đếm ngược countdown_seconds."""
    now = time.time()
    expires_at = now + countdown_seconds

    record = PendingDispatchRecord(
        case_id=case_id,
        trace_id=trace_id,
        draft=draft,
        status=CaseStatus.PENDING_SEND,
        scheduled_at=now,
        expires_at=expires_at,
    )
    _DISPATCH_REGISTRY[case_id] = record

    _log_dispatch_audit(
        case_id, "SEND_SCHEDULED", actor="SYSTEM", detail=f"countdown={countdown_seconds}s"
    )
    return record


def get_dispatch_record(case_id: str) -> PendingDispatchRecord | None:
    """Lấy bản ghi dispatch theo case_id."""
    return _DISPATCH_REGISTRY.get(case_id)


def cancel_send(case_id: str, actor: str = "HUMAN", reason: str = "") -> tuple[bool, str]:
    """Hành động can thiệp 1: Hủy gửi trong vòng 60 giây (Task A-19 & Tiêu chí 6).

    Chuyển trạng thái case từ PENDING_SEND sang CANCELLED.
    Ghi nhận audit log với actor người thật.
    """
    record = _DISPATCH_REGISTRY.get(case_id)
    if not record:
        return False, f"Không tìm thấy case {case_id} trong hàng chờ gửi."

    if record.status != CaseStatus.PENDING_SEND:
        return False, f"Case {case_id} đang ở trạng thái {record.status}, không thể hủy gửi."

    record.status = CaseStatus.CANCELLED
    _log_dispatch_audit(
        case_id,
        "CANCEL_SEND",
        actor=actor,
        detail=reason or "Chuyên viên bấm hủy gửi trong thời gian đếm ngược",
    )
    return True, f"Đã hủy gửi thành công cho case {case_id}."


def escalate_from_pending(
    case_id: str,
    actor: str = "HUMAN",
    reason: str = "Chuyên viên chuyển tiếp sang xử lý thủ công",
) -> tuple[bool, str]:
    """Hành động can thiệp 2: Chuyển case từ PENDING_SEND sang AWAITING_HUMAN."""
    record = _DISPATCH_REGISTRY.get(case_id)
    if not record:
        return False, f"Không tìm thấy case {case_id} trong hàng chờ gửi."

    if record.status != CaseStatus.PENDING_SEND:
        return False, f"Case {case_id} không ở trạng thái PENDING_SEND."

    record.status = CaseStatus.AWAITING_HUMAN
    _log_dispatch_audit(case_id, "ESCALATE_FROM_PENDING", actor=actor, detail=reason)
    return True, f"Đã chuyển case {case_id} sang hàng chờ chuyên viên."


def dispatch_case(case_id: str, *, force: bool = False) -> tuple[bool, str]:
    """R13: Thực hiện gửi email (mô phỏng) khi hết 60 giây.

    Case chuyển sang trạng thái SENT và bị đóng băng, không được sửa trực tiếp.
    """
    from core.controls import is_automation_paused

    if is_automation_paused():
        return False, "Hệ thống đang tạm dừng tự động hóa, không tự động gửi."

    record = _DISPATCH_REGISTRY.get(case_id)
    if not record:
        return False, f"Không tìm thấy case {case_id}."

    if record.status != CaseStatus.PENDING_SEND:
        return False, f"Case {case_id} không ở trạng thái PENDING_SEND (hiện tại: {record.status})."

    now = time.time()
    if not force and now < record.expires_at:
        remaining = int(record.expires_at - now)
        return False, f"Case {case_id} chưa hết thời gian đếm ngược ({remaining}s còn lại)."

    record.status = CaseStatus.SENT
    _log_dispatch_audit(
        case_id, "SEND_DISPATCHED", actor="SYSTEM", detail="Mô phỏng gửi thành công qua Mock Mailer"
    )
    return True, f"Case {case_id} đã được gửi thành công (SENT)."


def create_correction_email(
    parent_case_id: str,
    correction_body: str,
    actor: str = "HUMAN",
    subject_prefix: str = "[ĐÍNH CHÍNH] ",
) -> tuple[str, str]:
    """Tạo Correction Email mới liên kết ngược parent_case_id (Mục 8.8 spec).

    Tuyệt đối không sửa trên case SENT cũ; sinh case_id mới và lưu parent_case_id.
    """
    parent_record = _DISPATCH_REGISTRY.get(parent_case_id)
    old_subj = parent_record.draft.subject if parent_record else "Thư phản hồi"
    new_subject = f"{subject_prefix}{old_subj}"

    new_case_id = f"c_corr_{uuid.uuid4().hex[:12]}"
    new_trace_id = f"tr_{uuid.uuid4().hex[:12]}"

    new_draft = DraftReply(
        subject=new_subject,
        body=correction_body,
        citations=parent_record.draft.citations if parent_record else [],
        grounded=True,
        guard_failures=[],
    )

    _DISPATCH_REGISTRY[new_case_id] = PendingDispatchRecord(
        case_id=new_case_id,
        trace_id=new_trace_id,
        draft=new_draft,
        status=CaseStatus.PENDING_SEND,
        scheduled_at=time.time(),
        expires_at=time.time() + 60.0,
        parent_case_id=parent_case_id,
        audit_trail=[],
    )

    _log_dispatch_audit(
        new_case_id,
        "CORRECTION_CREATED",
        actor=actor,
        detail=f"Tạo correction cho parent_case_id={parent_case_id}",
    )
    return new_case_id, f"Đã tạo email đính chính {new_case_id} thành công."


def _log_dispatch_audit(case_id: str, action: str, actor: str, detail: str) -> None:
    """Ghi nhận nhật ký kiểm toán cho chu trình Dispatch."""
    if case_id in _DISPATCH_REGISTRY:
        _DISPATCH_REGISTRY[case_id].audit_trail.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "actor": actor,
                "detail": detail,
            }
        )
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(case_id=case_id, actor=actor, action=action, output_ref=detail)
    except ImportError:
        logger.debug("infra.audit chưa cấu hình — bỏ qua")
    except Exception:
        logger.exception("Ghi audit dispatch thất bại")
