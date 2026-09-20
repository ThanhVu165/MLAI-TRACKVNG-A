from __future__ import annotations

import logging

from core.ground_guard import validate_groundedness
from core.types import (
    CaseInput,
    CaseStatus,
    DraftReply,
    EvidenceResult,
    EvidenceStatus,
)

logger = logging.getLogger(__name__)


def resume_after_human(
    case_id: str, human_choice: str, human_reason: str, actor: str = "HUMAN"
) -> DraftReply:
    """R11: Tiếp tục xử lý sau khi người quyết định (Mục 5.3 spec).

    Chữ ký chuẩn Mục 5.3 spec: (case_id, human_choice, human_reason, actor) -> DraftReply.
    """
    from core.pipeline import get_stored_case

    stored = get_stored_case(case_id)
    if stored is None:
        raise ValueError(f"Không tìm thấy case {case_id} để tiếp tục.")
    inp, result = stored
    evidence_res = result.evidence or EvidenceResult(
        status=EvidenceStatus.OK, chunks=[], failed_checks=[]
    )
    draft, _ = resume_after_decision(
        case_id,
        choice=human_choice,
        reason=human_reason,
        evidence_res=evidence_res,
        inp=inp,
        actor=actor,
    )
    return draft


def resume_after_decision(
    case_id: str,
    choice: str,
    reason: str,
    evidence_res: EvidenceResult,
    inp: CaseInput,
    *,
    actor: str = "HUMAN",
) -> tuple[DraftReply, CaseStatus]:
    """R11: Tiếp tục xử lý sau khi người quyết định (Task A-20).

    Khẩu hiệu: 'Con người quyết định cái gì, AI lo cách diễn đạt'.
    1. Kiểm tra bắt buộc: reason không được rỗng.
    2. LLM/Heuristic chỉ diễn đạt lại quyết định của con người thành email trang trọng,
       cấm suy đoán hoặc thêm các điều khoản quy định không có trong reason/evidence.
    3. Chạy lại Groundedness Guard rút gọn (kiểm tra cam kết vượt quyền).
    4. Đưa case sang trạng thái PENDING_APPROVAL.
    5. Ghi audit log CASE_RESUMED.
    """
    clean_reason = reason.strip()
    clean_choice = choice.strip()

    if not clean_reason:
        raise ValueError(
            "Lý do quyết định (reason) là bắt buộc, không được để trống theo quy định Mục 8 spec R10."
        )

    citations = [c.chunk_id for c in evidence_res.chunks]
    citation_tag = f"[{citations[0]}]" if citations else ""

    body = (
        f"Chào em,\n\n"
        f"Liên quan đến yêu cầu của em về việc '{inp.subject}', "
        f"Văn phòng Công tác Sinh viên (DSA) đã xem xét và thông báo kết quả như sau:\n\n"
        f"- Kết luận: {clean_choice}\n"
        f"- Căn cứ & Lý do: {clean_reason} {citation_tag}\n\n"
        f"Nếu có thắc mắc cần hỗ trợ thêm, em vui lòng liên hệ trực tiếp tại Văn phòng DSA.\n\n"
        f"Trân trọng,\n"
        f"Văn phòng Công tác Sinh viên (DSA)"
    )

    draft = DraftReply(
        subject=f"Re: {inp.subject} - Thông báo kết quả xử lý",
        body=body,
        citations=citations,
        grounded=True,
        guard_failures=[],
    )

    # Chạy Ground Guard kiểm tra
    validate_groundedness(draft, evidence_res, case_id=case_id)

    _log_resume_audit(case_id, actor, clean_choice, clean_reason)
    return draft, CaseStatus.PENDING_APPROVAL


def _log_resume_audit(case_id: str, actor: str, choice: str, reason: str) -> None:
    """Ghi nhận audit event CASE_RESUMED nếu infra khả dụng."""
    if not case_id:
        return
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(
            case_id=case_id,
            actor=actor,
            action="CASE_RESUMED",
            output_ref=f"choice={choice}; reason={reason}",
        )
    except ImportError:
        logger.debug("infra.audit chưa cấu hình — bỏ qua")
    except Exception:
        logger.exception("Ghi audit resume thất bại")
