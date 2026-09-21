from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Literal

from core.types import Domain, Extraction, RequestItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt & JSON Schema theo mục 5.2 và 8.0 của PROJECT_SPEC.md
# ---------------------------------------------------------------------------

EXTRACT_PROMPT_V2 = """Bạn là trợ lý AI chuyên trích xuất thông tin hành chính từ email sinh viên gửi văn phòng Công tác Sinh viên (DSA).
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

Trước khi phân loại, hãy xác định cụm hành động chính và đối tượng mà sinh viên hỏi hoặc yêu cầu. Câu ngắn vẫn hợp lệ. Phân biệt theo ngữ cảnh, không chỉ theo một từ khóa đơn lẻ.

Hãy trả về định dạng JSON theo đúng schema được yêu cầu.
"""

# Giữ alias cho script tạo cassette cũ; prompt đang dùng là phiên bản V2.
EXTRACT_PROMPT_V1 = EXTRACT_PROMPT_V2

DOMAIN_PHRASES = {
    Domain.CONDUCT_SCORE: ("diem ren luyen", "drl"),
    Domain.COURSE_WITHDRAWAL: (
        "rut mon",
        "rut hoc phan",
        "huy mon",
        "course withdrawal",
        "withdraw course",
    ),
    Domain.GRADE_APPEAL: (
        "phuc khao",
        "khieu nai diem",
        "khang nghi diem",
        "cham lai",
        "xem lai diem",
        "grade appeal",
        "re grade",
    ),
}

DOMAIN_LABELS = {
    Domain.CONDUCT_SCORE: "điểm rèn luyện",
    Domain.COURSE_WITHDRAWAL: "rút học phần",
    Domain.GRADE_APPEAL: "phúc khảo điểm",
    Domain.UNKNOWN: "yêu cầu của sinh viên",
}

INFORMATION_PHRASES = (
    "cho em hoi",
    "muon hoi",
    "muon biet",
    "cho em biet",
    "bao nhieu",
    "khi nao",
    "o dau",
    "thu tuc",
    "quy trinh",
    "le phi",
    "han chot",
    "huong dan",
    "what",
    "when",
    "where",
    "how",
    "procedure",
    "deadline",
    "fee",
)

REQUEST_PHRASES = ("xin", "muon", "de nghi", "mong", "cho em", "co the", "please")
EXCEPTION_PHRASES = ("ngoai le", "sau han", "qua han", "tre", "cham chuoc", "mien")
APPEAL_ACTION_PHRASES = (
    "muon phuc khao",
    "xin phuc khao",
    "de nghi phuc khao",
    "cho em phuc khao",
    "phuc khao bai thi",
    "cham lai",
    "xem lai diem",
    "xem xet lai diem",
    "khieu nai diem",
    "khang nghi diem",
)
APPROVAL_PHRASES = (
    "nho duyet",
    "duyet cho em",
    "duyet giup em",
    "phe duyet cho em",
    "kinh xin thay",
    "kinh xin co",
)
PERSONAL_RECORD_PHRASES = (
    "mssv",
    "diem cua em",
    "ket qua cua em",
    "ho so cua em",
    "truong hop cua em",
)

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
    return raw if raw in ("vi", "en") else "other"


def _normalize_for_matching(text: str) -> str:
    """Chuẩn hóa Unicode và dấu câu để so khớp cụm từ ổn định."""
    decomposed = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^\w]+", " ", without_marks).strip()


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {phrase} " in padded for phrase in phrases)


def _detect_domain(text: str) -> Domain:
    return next(
        (domain for domain, phrases in DOMAIN_PHRASES.items() if _contains(text, phrases)),
        Domain.UNKNOWN,
    )


def _information_intent(text: str, domain: Domain) -> str:
    label = DOMAIN_LABELS[domain]
    if _contains(text, ("hoan hoc phi", "hoan bao nhieu")):
        return "Hỏi tỷ lệ hoàn học phí khi rút học phần"
    if _contains(text, ("le phi", "fee", "bao nhieu")):
        return f"Hỏi lệ phí {label}"
    if _contains(text, ("han", "han chot", "deadline", "khi nao")):
        return f"Hỏi thời hạn {label}"
    if _contains(text, ("thu tuc", "quy trinh", "procedure", "huong dan")):
        return f"Hỏi thủ tục {label}"
    return f"Hỏi thông tin {label}"


def _action_intent(
    domain: Domain,
    asks_exception: bool,
    asks_appeal: bool,
    asks_authority: bool,
) -> str:
    label = DOMAIN_LABELS[domain]
    if asks_exception:
        return f"Xin ngoại lệ {label}"
    if asks_appeal:
        return "Yêu cầu phúc khảo điểm cá nhân"
    if asks_authority:
        return f"Yêu cầu phê duyệt {label}"
    return f"Yêu cầu tra cứu hồ sơ cá nhân về {label}"


def _build_requests(text: str, domain: Domain) -> list[RequestItem]:
    information_query = _contains(text, INFORMATION_PHRASES)
    exception_context = _contains(text, EXCEPTION_PHRASES)
    asks_exception = exception_context and (
        _contains(text, REQUEST_PHRASES) or not information_query
    )
    asks_appeal = _contains(text, APPEAL_ACTION_PHRASES)
    asks_authority = _contains(text, APPROVAL_PHRASES)
    requires_record = _contains(text, PERSONAL_RECORD_PHRASES) and not asks_exception
    needs_human = asks_exception or asks_appeal or asks_authority or requires_record
    requests: list[RequestItem] = []
    if information_query and needs_human:
        requests.append(
            RequestItem(
                domain=domain,
                intent=_information_intent(text, domain),
                is_informational=True,
                requires_personal_record=False,
                asks_exception=False,
                asks_appeal=False,
                asks_authority_decision=False,
            )
        )
    if needs_human:
        requests.append(
            RequestItem(
                domain=domain,
                intent=_action_intent(domain, asks_exception, asks_appeal, asks_authority),
                is_informational=False,
                requires_personal_record=requires_record,
                asks_exception=asks_exception,
                asks_appeal=asks_appeal,
                asks_authority_decision=asks_authority,
            )
        )
    elif not requests:
        requests.append(
            RequestItem(
                domain=domain,
                intent=_information_intent(text, domain),
                is_informational=True,
                requires_personal_record=False,
                asks_exception=False,
                asks_appeal=False,
                asks_authority_decision=False,
            )
        )
    return requests


def _critical_facts(text: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    cohort_match = re.search(r"\bk(4[89]|50)\b", text)
    semester_match = re.search(r"\bhoc ky\s*([123])\b", text)
    if cohort_match:
        facts["cohort"] = f"K{cohort_match.group(1)}"
    if semester_match:
        facts["semester"] = f"Học kỳ {semester_match.group(1)}"
    return facts


def _heuristic_extract(clean_text: str, subject: str, language: str) -> Extraction:
    """NLP nhẹ, deterministic cho môi trường offline/replay."""
    combined = _normalize_for_matching(f"{subject} {clean_text}")
    domain = _detect_domain(combined)
    requests = _build_requests(combined, domain)
    critical_facts = _critical_facts(combined)

    missing_facts: list[str] = []

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
        prompt = f"{EXTRACT_PROMPT_V2}\n\nEmail Tiêu đề: {subject}\nNội dung:\n{clean_text}"
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
        elif res.error and (
            "No such file or directory" in res.error
            or "GEMINI_API_KEY" in res.error
            or "mất kết nối" in res.error
        ):
            logger.debug("LLM cassette/key missing (%s), using heuristic fallback", res.error)
            return _heuristic_extract(clean_text, subject, language)
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
