"""Các ngưỡng vận hành có thể ghi đè bằng biến môi trường cùng tên."""

from __future__ import annotations

import os


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


# Ngưỡng điểm truy xuất tối thiểu để một nguồn được xem là liên quan.
SIMILARITY_THRESHOLD = _float("SIMILARITY_THRESHOLD", 0.35)
# Tỷ lệ câu khẳng định phải có trích dẫn.
CITATION_RATIO_MIN = _float("CITATION_RATIO_MIN", 0.6)
# Thời gian người dùng có thể dừng gửi tự động.
PENDING_SEND_SECONDS = _int("PENDING_SEND_SECONDS", 60)
# Email ngắn hơn ngưỡng này bị xem là thiếu nội dung.
MIN_WORDS_GUARD = _int("MIN_WORDS_GUARD", 15)
# Giới hạn chờ một lượt gọi LLM.
LLM_TIMEOUT_S = _int("LLM_TIMEOUT_S", 20)
# Số lần thử lại sau lỗi LLM.
LLM_RETRIES = _int("LLM_RETRIES", 1)
# Số chunk tối đa lấy từ corpus.
RETRIEVAL_TOP_K = _int("RETRIEVAL_TOP_K", 6)
# Độ dài câu hỏi chuyển tiếp hợp lệ.
QUESTION_WORDS_MIN = _int("QUESTION_WORDS_MIN", 8)
QUESTION_WORDS_MAX = _int("QUESTION_WORDS_MAX", 45)
# Khoảng thời gian rà lại case khi rollback tài liệu.
RECHECK_WINDOW_DAYS = _int("RECHECK_WINDOW_DAYS", 30)
