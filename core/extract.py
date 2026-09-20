from __future__ import annotations

import json
import logging
from typing import Any, Literal

from core.types import Domain, Extraction, RequestItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt & JSON Schema theo mục 5.2 và 8.0 của PROJECT_SPEC.md
# ---------------------------------------------------------------------------

EXTRACT_PROMPT_V1 = """Bạn là trợ lý AI chuyên trích xuất thông tin hành chính từ email sinh viên gửi văn phòng Công tác Sinh viên (DSA).
Nhiệm vụ của bạn DUY NHẤT là trích xuất sự kiện và phân loại ý định. TUYỆT ĐỐI không trả lời câu hỏi, không suy đoán.

Các domain hợp lệ:
- conduct_score (Điểm rèn luyện)
- course_withdrawal (Rút học phần)
- grade_appeal (Phúc khảo điểm)
- unknown (Mọi nội dung khác)

QUY TẮC PHÂN LOẠI 4 CỜ BOOLEAN:
1. is_informational: TRUE khi sinh viên CHỈ hỏi thông tin chung, quy trình, lệ phí, thời hạn - KHÔNG yêu cầu hành động đối với hồ sơ của chính họ.
2. asks_appeal: TRUE khi sinh viên đang ĐỀ NGHỊ KHÁNG NGHỊ / PHÚC KHẢO điểm của chính họ (ví dụ: "em muốn phúc khảo môn X"). Nếu chỉ hỏi "lệ phí phúc khảo là bao nhiêu?" -> FALSE.
3. asks_exception: TRUE khi sinh viên XIN NGOẠI LỆ áp dụng khác quy định (ví dụ: "em muốn rút môn sau hạn"). Nếu chỉ hỏi "hạn rút môn là ngày nào?" -> FALSE.
4. asks_authority_decision: TRUE khi YÊU CẦU người có thẩm quyền phê duyệt trường hợp cá nhân (ví dụ: "nhờ thầy duyệt cho em"). Nếu chỉ hỏi "ai có thẩm quyền duyệt?" -> FALSE.

Hãy trả về định dạng JSON theo đúng schema được yêu cầu.
"""

EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "enum": ["vi", "en", "other"]},
        "requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": ["conduct_score", "course_withdrawal", "grade_appeal", "unknown"],
                    },
                    "intent": {"type": "string"},
                    "is_informational": {"type": "boolean"},
                    "requires_personal_record": {"type": "boolean"},
                    "asks_exception": {"type": "boolean"},
                    "asks_appeal": {"type": "boolean"},
                    "asks_authority_decision": {"type": "boolean"},
                },
                "required": [
                    "domain",
                    "intent",
                    "is_informational",
                    "requires_personal_record",
                    "asks_exception",
                    "asks_appeal",
                    "asks_authority_decision",
                ],
            },
        },
        "critical_facts": {"type": "object", "additionalProperties": {"type": "string"}},
        "missing_critical_facts": {"type": "array", "items": {"type": "string"}},
        "injection_suspected": {"type": "boolean"},
    },
    "required": [
        "language",
        "requests",
        "critical_facts",
        "missing_critical_facts",
        "injection_suspected",
    ],
}


def _normalize_lang(raw: Any) -> Literal["vi", "en", "other"]:
    """Chuẩn hóa giá trị ngôn ngữ về Literal['vi', 'en', 'other']."""
    if raw == "vi":
        return "vi"
    elif raw == "en":
        return "en"
    return "other"


def _heuristic_extract(clean_text: str, subject: str, language: str) -> Extraction:
    """Bộ trích xuất rule-based thông minh phục vụ môi trường offline/stub."""
    combined = f"{subject} {clean_text}".lower()

    # Nhận diện Domain
    domain = Domain.UNKNOWN
    if any(k in combined for k in ["rèn luyện", "ren luyen", "đrl", "drl"]):
        domain = Domain.CONDUCT_SCORE
    elif any(
        k in combined
        for k in ["rút môn", "rut mon", "rút học phần", "rut hoc phan", "hủy môn", "withdrawal"]
    ):
        domain = Domain.COURSE_WITHDRAWAL
    elif any(
        k in combined for k in ["phúc khảo", "phuc khao", "khiếu nại điểm", "appeal", "re-grade"]
    ):
        domain = Domain.GRADE_APPEAL

    # Kiểm tra các cờ thẩm quyền theo đúng quy tắc vàng Mục 8.0 spec
    is_procedure_or_fee_query = any(
        k in combined
        for k in [
            "lệ phí",
            "le phi",
            "bao nhiêu",
            "bao nhieu",
            "thời hạn",
            "thoi han",
            "khi nào",
            "khi nao",
            "hạn chót",
            "han chot",
            "quy trình",
            "quy trinh",
            "thủ tục",
            "thu tuc",
            "hướng dẫn",
            "huong dan",
            "mẫu đơn",
            "mau don",
            "điều kiện",
            "dieu kien",
            "thang điểm",
            "thang diem",
        ]
    )

    asks_exception = any(
        k in combined
        for k in [
            "ngoại lệ",
            "ngoai le",
            "sau hạn",
            "sau han",
            "quá hạn",
            "qua han",
            "châm chước",
            "cham chuoc",
            "được không",
            "duoc khong",
        ]
    ) and any(k in combined for k in ["xin", "cho em", "mong"])

    # Chỉ bật asks_appeal khi thực sự đề nghị chấm lại cho bản thân, không bị chặn bởi từ hỏi lệ phí
    asks_appeal = False
    if any(
        k in combined for k in ["phúc khảo", "appeal", "khiếu nại", "kháng nghị", "xem xét lại"]
    ):
        asks_appeal = any(
            k in combined
            for k in [
                "em muốn phúc khảo",
                "xin phúc khảo",
                "nộp đơn phúc khảo bài",
                "chấm lại bài",
                "cho em phúc khảo",
                "phúc khảo bài thi",
                "khiếu nại",
                "kháng nghị",
                "xem xét lại",
                "bị trừ điểm",
            ]
        )

    asks_authority_decision = any(
        k in combined
        for k in [
            "nhờ thầy duyệt",
            "nhờ cô duyệt",
            "kính xin thầy",
            "kính xin cô",
            "duyệt giúp em",
            "phê duyệt cho em",
        ]
    )

    requires_personal_record = (
        any(
            k in combined
            for k in ["[mssv]", "mssv", "điểm của em", "kết quả của em", "hồ sơ của em"]
        )
        and not asks_exception
    )

    requests: list[RequestItem] = []
    has_authority = (
        asks_exception or asks_appeal or asks_authority_decision or requires_personal_record
    )

    if is_procedure_or_fee_query and has_authority:
        # Email đa ý định (A-24): 1 phần thường quy tra cứu + 1 phần cần thẩm quyền
        requests.append(
            RequestItem(
                domain=domain,
                intent=f"Hỏi thủ tục/thông tin {domain.value}",
                is_informational=True,
                requires_personal_record=False,
                asks_exception=False,
                asks_appeal=False,
                asks_authority_decision=False,
            )
        )
        requests.append(
            RequestItem(
                domain=domain,
                intent=subject.strip() or f"Yêu cầu xử lý {domain.value}",
                is_informational=False,
                requires_personal_record=requires_personal_record,
                asks_exception=asks_exception,
                asks_appeal=asks_appeal,
                asks_authority_decision=asks_authority_decision,
            )
        )
    else:
        is_info = is_procedure_or_fee_query or not has_authority
        requests.append(
            RequestItem(
                domain=domain,
                intent=subject.strip() or "Yêu cầu thông tin",
                is_informational=is_info,
                requires_personal_record=requires_personal_record,
                asks_exception=asks_exception,
                asks_appeal=asks_appeal,
                asks_authority_decision=asks_authority_decision,
            )
        )

    critical_facts: dict[str, str] = {}
    missing_facts: list[str] = []

    # Nhận diện khóa học / học kỳ nếu có
    if "k48" in combined:
        critical_facts["cohort"] = "K48"
    elif "k49" in combined:
        critical_facts["cohort"] = "K49"
    elif "k50" in combined:
        critical_facts["cohort"] = "K50"

    raw_dict = {
        "language": language,
        "requests": [
            {
                "domain": r.domain.value,
                "intent": r.intent,
                "is_informational": r.is_informational,
                "requires_personal_record": r.requires_personal_record,
                "asks_exception": r.asks_exception,
                "asks_appeal": r.asks_appeal,
                "asks_authority_decision": r.asks_authority_decision,
            }
            for r in requests
        ],
        "critical_facts": critical_facts,
        "missing_critical_facts": missing_facts,
    }

    return Extraction(
        language=_normalize_lang(language),
        requests=requests,
        critical_facts=critical_facts,
        missing_critical_facts=missing_facts,
        injection_suspected=False,
        raw_json=json.dumps(raw_dict, ensure_ascii=False),
        llm_error=None,
    )


def parse_extraction_data(data: dict[str, Any], raw_json: str) -> Extraction:
    """Chuyển đổi dữ liệu dict từ LLM thành đối tượng Extraction hợp lệ."""
    lang = _normalize_lang(data.get("language"))

    requests: list[RequestItem] = []
    for r in data.get("requests", []):
        d_val = r.get("domain", "unknown")
        try:
            domain = Domain(d_val)
        except ValueError:
            domain = Domain.UNKNOWN

        requests.append(
            RequestItem(
                domain=domain,
                intent=str(r.get("intent", "")),
                is_informational=bool(r.get("is_informational", False)),
                requires_personal_record=bool(r.get("requires_personal_record", False)),
                asks_exception=bool(r.get("asks_exception", False)),
                asks_appeal=bool(r.get("asks_appeal", False)),
                asks_authority_decision=bool(r.get("asks_authority_decision", False)),
            )
        )

    if not requests:
        requests.append(
            RequestItem(
                domain=Domain.UNKNOWN,
                intent="Không xác định",
                is_informational=True,
                requires_personal_record=False,
                asks_exception=False,
                asks_appeal=False,
                asks_authority_decision=False,
            )
        )

    return Extraction(
        language=lang,
        requests=requests,
        critical_facts=data.get("critical_facts", {}),
        missing_critical_facts=data.get("missing_critical_facts", []),
        injection_suspected=bool(data.get("injection_suspected", False)),
        raw_json=raw_json,
        llm_error=None,
    )


def extract_facts(
    clean_text: str,
    subject: str,
    case_id: str,
    language: str = "vi",
    *,
    retries: int = 1,
    timeout_s: int = 20,
) -> Extraction:
    """R2: Trích xuất sự kiện và ý định từ email đã làm sạch (Mục 8.0 & Task A-08, A-09).

    Tuân thủ quy tắc retry 1 lần và timeout fail-safe.
    Nếu infra.llm khả dụng thì gọi qua LLM, ngược lại sử dụng heuristic an toàn.
    """
    try:
        # Thử import infra.llm nếu Agent C đã cấu hình
        from infra.llm import call_json  # type: ignore[import-not-found]
    except ImportError:
        # Môi trường stub / chưa cấu hình infra.llm: Chạy fallback heuristic
        logger.debug("infra.llm chưa cấu hình — sử dụng fallback heuristic")
        return _heuristic_extract(clean_text, subject, language)

    try:
        prompt = f"{EXTRACT_PROMPT_V1}\n\nEmail Tiêu đề: {subject}\nNội dung:\n{clean_text}"
        res = call_json(
            prompt,
            schema=EXTRACTION_JSON_SCHEMA,
            step="R2_extract",
            case_id=case_id,
            timeout_s=timeout_s,
            retries=retries,
            temperature=0.0,
        )
        if res.ok and res.data:
            return parse_extraction_data(res.data, json.dumps(res.data, ensure_ascii=False))
        else:
            # LLM lỗi hoặc timeout -> Task A-09 fail-safe
            return Extraction(
                language=_normalize_lang(language),
                requests=[],
                critical_facts={},
                missing_critical_facts=[],
                injection_suspected=False,
                raw_json="",
                llm_error=res.error or "LLM extraction failed",
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM extraction call failed: %s", exc)
        return Extraction(
            language=_normalize_lang(language),
            requests=[],
            critical_facts={},
            missing_critical_facts=[],
            injection_suspected=False,
            raw_json="",
            llm_error=str(exc),
        )
