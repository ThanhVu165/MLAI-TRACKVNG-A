from __future__ import annotations

from core.types import Extraction


def evaluate_prepolicy_lock(extraction: Extraction | None) -> str | None:
    """R3: Pre-policy Lock (Task A-10).

    Kiểm tra xem yêu cầu có chạm tới các yếu tố vượt thẩm quyền tự động hay không:
    - requires_personal_record: Đụng tới dữ liệu hồ sơ cá nhân
    - asks_exception: Xin ngoại lệ trái quy định
    - asks_appeal: Khiếu nại / phúc khảo kết quả
    - asks_authority_decision: Yêu cầu người có thẩm quyền phê duyệt

    Nếu có bất kỳ cờ nào = True -> trả về 'AUTHORITY_REQUIRED'.
    Ngược lại trả về None.
    Lưu ý: Không nhảy tắt pipeline; R4 và R5 vẫn chạy để lấy căn cứ quy định cho thẻ escalation.
    """
    if extraction is None or not extraction.requests:
        return None

    for req in extraction.requests:
        if (
            req.requires_personal_record
            or req.asks_exception
            or req.asks_appeal
            or req.asks_authority_decision
        ):
            return "AUTHORITY_REQUIRED"

    return None
