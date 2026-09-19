from __future__ import annotations

import logging
from pathlib import Path

import yaml

from core.question_gen import generate_escalation_card, load_fallback_template
from core.types import (
    EscalationCard,
    EscalationType,
    EvidenceResult,
    Extraction,
)

logger = logging.getLogger(__name__)

DEFAULT_BLOCKLIST = [
    "vui lòng xem xét",
    "kiểm tra lại",
    "xử lý giúp",
    "nhờ anh/chị xem",
    "please review",
    "kindly check",
    "cần xem xét thêm",
]


def load_blocklist(blocklist_path: str = "policies/blocklist.yaml") -> list[str]:
    """Tải danh sách các cụm từ chung chung bị cấm từ blocklist.yaml."""
    path = Path(blocklist_path)
    if not path.is_file():
        return DEFAULT_BLOCKLIST

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("blocklist", DEFAULT_BLOCKLIST)
    except Exception:  # noqa: BLE001
        return DEFAULT_BLOCKLIST


def validate_question_quality(
    card: EscalationCard,
    blocklist_path: str = "policies/blocklist.yaml",
) -> tuple[bool, list[str]]:
    """R8b: Question Quality Guard - Bộ lọc deterministic bảo vệ chất lượng thẻ escalation (Mục 8.7 spec).

    Các luật kiểm tra:
    1. Câu hỏi kết thúc bằng dấu '?'.
    2. Độ dài câu hỏi từ 8 đến 45 từ.
    3. Đúng duy nhất một dấu '?'.
    4. Chứa ít nhất một dữ kiện cụ thể lấy từ khối [2] (đối sánh chuỗi không phân biệt hoa thường).
    5. options có từ 2 đến 4 phương án, không rỗng.
    6. Khối [3] có >= 1 breadcrumb (trừ OUT_OF_POLICY khi không có nguồn).
    7. Không chứa cụm từ bị cấm trong blocklist.yaml.

    Trả về (passed: bool, violations: list[str]).
    """
    violations: list[str] = []
    question = card.question.strip()

    # 1. Kết thúc bằng dấu '?'
    if not question.endswith("?"):
        violations.append("rule_1:question_must_end_with_question_mark")

    # 2. Độ dài từ 8 đến 45 từ
    words = question.split()
    if len(words) < 8 or len(words) > 45:
        violations.append(f"rule_2:word_count_{len(words)}_outside_8_45")

    # 3. Đúng duy nhất một dấu '?'
    if question.count("?") != 1:
        violations.append(f"rule_3:question_has_{question.count('?')}_question_marks")

    # 4. Chứa ít nhất một dữ kiện cụ thể từ Khối [2]
    fact_keywords: set[str] = set()
    for f in card.facts:
        f_clean = f.lower().replace(":", " ").replace("-", " ")
        for token in f_clean.split():
            clean_token = token.strip(".,;:!?()[]\"'")
            if not clean_token:
                continue
            if any(ch.isdigit() for ch in clean_token) or len(clean_token) >= 3 and clean_token not in (
                "sinh", "viên", "yêu", "cầu", "thông", "tin", "hiện", "tại", "đang",
                "được", "trong", "theo", "quy", "định", "nhà", "trường",
            ):
                fact_keywords.add(clean_token)

    q_lower = question.lower()
    has_fact_match = any(kw in q_lower for kw in fact_keywords)
    if not has_fact_match and fact_keywords:
        violations.append("rule_4:question_missing_anchor_from_facts")

    # 5. options có 2-4 phương án không rỗng
    valid_options = [opt.strip() for opt in card.options if opt.strip()]
    if len(valid_options) < 2 or len(valid_options) > 4:
        violations.append(f"rule_5:options_count_{len(valid_options)}_outside_2_4")

    # 6. Khối [3] có >= 1 breadcrumb
    if not card.basis:
        if card.escalation_type != EscalationType.OUT_OF_POLICY:
            violations.append("rule_6:basis_missing_breadcrumb")
    else:
        has_breadcrumb = any(b[0].strip() for b in card.basis)
        if not has_breadcrumb and card.escalation_type != EscalationType.OUT_OF_POLICY:
            violations.append("rule_6:basis_missing_breadcrumb")

    # 7. Không chứa cụm blocklist
    blocklist = load_blocklist(blocklist_path)
    for forbidden in blocklist:
        if forbidden.lower() in q_lower:
            violations.append(f"rule_7:forbidden_blocklist_{forbidden}")
            break

    return len(violations) == 0, violations


def ensure_valid_escalation_card(
    card: EscalationCard,
    extraction: Extraction,
    evidence_res: EvidenceResult,
    escalation_type: EscalationType,
    case_id: str = "",
    blocklist_path: str = "policies/blocklist.yaml",
    fallback_path: str = "policies/fallback_questions.yaml",
) -> EscalationCard:
    """Đảm bảo EscalationCard vượt qua Question Guard: Thử sửa 1 lần, nếu vẫn fail thì dùng fallback template."""
    passed, violations = validate_question_quality(card, blocklist_path)
    if passed:
        return card

    logger.warning("Thẻ Escalation vi phạm guard (%s), tiến hành tái tạo 1 lần...", violations)

    # Thử regenerate 1 lần
    card_v2 = generate_escalation_card(
        extraction,
        evidence_res,
        escalation_type,
        case_id=case_id,
    )
    passed_v2, violations_v2 = validate_question_quality(card_v2, blocklist_path)
    if passed_v2:
        return card_v2

    logger.warning("Thẻ tái tạo vẫn vi phạm (%s), kích hoạt template cứng từ fallback_questions.yaml.", violations_v2)
    # Lấy fallback template chuẩn
    fallback_card = load_fallback_template(escalation_type, fallback_path)
    # Giữ lại partial_draft nếu có
    fallback_card.partial_draft = card.partial_draft
    return fallback_card
