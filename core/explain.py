from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from core.types import Decision, PipelineResult

logger = logging.getLogger(__name__)

# Danh sách các thuật ngữ kỹ thuật cấm tuyệt đối xuất hiện trong văn bản giải thích cho người không chuyên
FORBIDDEN_TECH_TERMS = [
    "rule_id",
    "similarity",
    "chunk",
    "chunk_id",
    "p01",
    "p02",
    "p03",
    "p04",
    "p05",
    "llm",
    "ast",
    "token",
    "vector",
    "embedding",
    "pipeline",
]


def explain_decision(result: PipelineResult, actor: str = "USER") -> str:
    """A-23: Giải thích quyết định của hệ thống cho người không chuyên (Tiêu chí 6 spec).

    Đặc tả:
    - Độ dài: <= 120 từ.
    - Trả lời đủ 4 câu hỏi:
      1. Hệ thống đã làm gì?
      2. Vì sao quyết định như vậy?
      3. Dựa trên văn bản/quy định nào (nói tên văn bản, KHÔNG dùng chunk_id)?
      4. Người dùng hoặc chuyên viên có thể làm gì tiếp?
    - Tuyệt đối không chứa thuật ngữ kỹ thuật (không rule_id, chunk, similarity...).
    - Ghi audit log EXPLAIN_REQUESTED.
    """
    _log_explain_audit(result.case_id, actor)

    # 1. Xác định tên văn bản quy định thân thiện (từ breadcrumb hoặc doc_id, loại bỏ mã chunk)
    doc_name = "Quy định đào tạo và công tác sinh viên hiện hành"
    if result.evidence and result.evidence.chunks:
        first_chunk = result.evidence.chunks[0]
        if first_chunk.breadcrumb:
            # Lấy tên văn bản từ breadcrumb
            parts = first_chunk.breadcrumb.split(">")
            doc_name = parts[0].strip()
        elif first_chunk.doc_id:
            clean_doc = re.sub(r"[_\-]", " ", first_chunk.doc_id).title()
            doc_name = f"Văn bản {clean_doc}"

    # 2. Xây dựng nội dung 4 phần
    decision = result.decision.decision
    reason_vi = result.decision.reason or ""

    # Làm sạch các thuật ngữ kỹ thuật khỏi reason_vi nếu có
    clean_reason = reason_vi
    for term in FORBIDDEN_TECH_TERMS:
        clean_reason = re.sub(rf"\b{term}\b", "", clean_reason, flags=re.IGNORECASE)
    clean_reason = re.sub(r"\s+", " ", clean_reason).strip()

    if decision == Decision.AUTO_REPLY:
        hanhdong = "Hệ thống đã tiếp nhận câu hỏi và tự động soạn thảo phản hồi giải đáp cho sinh viên."
        lydo = f"Câu hỏi thuộc nội dung tra cứu thông tin thường quy: {clean_reason}." if clean_reason else "Yêu cầu có đầy đủ thông tin tra cứu rõ ràng theo quy định."
        can_cu = f"Nội dung trả lời căn cứ theo {doc_name}."
        buoc_tiep = "Email đã được lên lịch gửi đến sinh viên. Chuyên viên có thể xem lại trong hàng chờ hoặc can thiệp nếu cần."
    elif decision == Decision.ESCALATE:
        hanhdong = "Hệ thống đã chuyển tiếp email này đến chuyên viên phụ trách để xem xét và xử lý trực tiếp."
        lydo = f"Trường hợp này cần người có thẩm quyền quyết định: {clean_reason}." if clean_reason else "Yêu cầu có tính chất ngoại lệ, khiếu nại hoặc hồ sơ cá nhân cần phê duyệt thủ công."
        can_cu = f"Quy trình xử lý đối chiếu theo {doc_name}."
        buoc_tiep = "Chuyên viên vui lòng kiểm tra thẻ thông tin, lựa chọn phương án xử lý hoặc phản hồi lại cho sinh viên."
    else:  # INVALID_INPUT
        hanhdong = "Hệ thống đã tạm dừng xử lý do thông tin gửi đến chưa đầy đủ hoặc không hợp lệ."
        lydo = f"Nguyên nhân: {clean_reason}." if clean_reason else "Nội dung thư quá ngắn hoặc chưa nêu rõ yêu cầu."
        can_cu = "Theo hướng dẫn tiếp nhận yêu cầu hành chính của nhà trường."
        buoc_tiep = "Sinh viên vui lòng gửi lại email mới với thông tin chi tiết và câu hỏi cụ thể hơn."

    explanation = f"{hanhdong} {lydo} {can_cu} {buoc_tiep}"

    # Đảm bảo làm sạch triệt để mọi từ cấm
    for term in FORBIDDEN_TECH_TERMS:
        explanation = re.sub(rf"\b{term}\b", "thành phần", explanation, flags=re.IGNORECASE)

    # Đảm bảo giới hạn độ dài <= 120 từ
    words = explanation.split()
    if len(words) > 120:
        words = words[:119]
        explanation = " ".join(words).rstrip(".,:;") + "."

    return explanation


def _log_explain_audit(case_id: str, actor: str) -> None:
    """Ghi nhận audit event khi có yêu cầu giải thích quyết định."""
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]
        log_event(
            case_id=case_id,
            actor=actor,
            action="EXPLAIN_REQUESTED",
            detail="Người dùng đã yêu cầu giải thích quyết định",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except (ImportError, Exception):  # noqa: BLE001, S110
        pass
