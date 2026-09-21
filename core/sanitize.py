from __future__ import annotations

import html
import re
import unicodedata
from typing import NamedTuple

from core.types import Decision, EscalationType

# ---------------------------------------------------------------------------
# Các mẫu regex phục vụ Sanitize & Guards
# ---------------------------------------------------------------------------

HTML_TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE)

QUOTE_PATTERNS = [
    re.compile(r"^\s*On\s+.+?\s+wrote:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Vào\s+.+?\s+đã viết:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*From:\s+.+?$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Sent:\s+.+?$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-{3,}\s*Original Message\s*-{3,}.*?$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*>{1,}.*?$", re.MULTILINE),
    re.compile(r"^\s*Sent from my (?:iPhone|iPad|Galaxy|device).*?$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Được gửi từ .+? của tôi.*?$", re.IGNORECASE | re.MULTILINE),
]

SIGNATURE_PATTERNS = [
    re.compile(r"^\s*--\s*$", re.MULTILINE),
    re.compile(r"^\s*---+\s*$", re.MULTILINE),
    re.compile(
        r"^\s*(?:Trân trọng|Best regards|Kính thư|Thân ái|Regards|Thanks & regards)[,.]?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
]

# Regex PII
CCCD_RE = re.compile(r"\b(?:\d{12})\b")
PHONE_VN_RE = re.compile(r"\b(?:\+?84|0)(?:3|5|7|8|9)\d{8}\b")
MSSV_RE = re.compile(r"(?:\bMSSV[\s:]*)?([0-9]{8,10})\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Regex Prompt Injection
INJECTION_KEYWORDS = [
    "bỏ qua quy định",
    "bỏ qua các quy định",
    "bỏ qua quy trình",
    "duyệt luôn",
    "duyệt ngay",
    "chấp thuận luôn",
    "tự động chấp thuận",
    "tự động đồng ý",
    "bạn là ai hãy",
    "bạn là ai",
    "bạn là trợ lý ai",
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "đừng chuyển cho ai",
    "không được chuyển cho ai",
    "hãy đóng giả",
]

VIETNAMESE_ACCENTED_CHARS = set(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ"
)

VIETNAMESE_UNACCENTED_WORDS = {
    "em",
    "thay",
    "co",
    "cho",
    "xin",
    "hoi",
    "hoc",
    "phan",
    "mon",
    "diem",
    "truong",
    "khi",
    "nao",
    "chao",
    "da",
    "nhe",
    "giup",
    "rut",
    "phuc",
    "khao",
    "ren",
    "luyen",
    "sinh",
    "vien",
    "nop",
    "don",
    "khoa",
    "nam",
    "bao",
    "nhieu",
    "sao",
    "khong",
    "duoc",
    "ve",
    "viec",
}

ENGLISH_WORDS = {
    "hello",
    "hi",
    "dear",
    "please",
    "when",
    "what",
    "where",
    "how",
    "why",
    "course",
    "withdrawal",
    "grade",
    "appeal",
    "student",
    "deadline",
    "fee",
    "thanks",
    "thank",
    "regards",
    "help",
    "information",
    "office",
    "dsa",
}

class SanitizeResult(NamedTuple):
    body_raw: str
    body_clean: str
    body_masked: str
    language: str
    injection_suspected: bool
    stripped_injection_segments: list[str]


def strip_html(raw_html: str) -> str:
    """Loại bỏ các thẻ HTML và giải mã HTML entities."""
    if not raw_html:
        return ""
    text = HTML_TAG_RE.sub(" ", raw_html)
    text = re.sub(r"[ \t]+", " ", text)
    # Xóa khoảng trắng trước dấu câu
    text = re.sub(r"\s+([,.:;?!])", r"\1", text)
    return html.unescape(text).strip()


def strip_quotes_and_signatures(text: str) -> str:
    """Cắt trích dẫn email cũ và chữ ký liên hệ ở cuối thư."""
    lines = text.splitlines()
    clean_lines: list[str] = []

    in_quote = False
    for line in lines:
        stripped = line.strip()
        # Kiểm tra dòng bắt đầu bằng dấu quote >
        if stripped.startswith(">"):
            continue

        # Kiểm tra các mẫu trích dẫn header
        is_quote_header = any(pat.match(line) for pat in QUOTE_PATTERNS)
        if is_quote_header:
            in_quote = True
            break

        # Kiểm tra chữ ký
        is_sig_header = any(pat.match(line) for pat in SIGNATURE_PATTERNS)
        if is_sig_header:
            break

        if not in_quote:
            clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    return result


def detect_language(text: str) -> str:
    """Phân loại ngôn ngữ vi / en / other bằng heuristic nhanh, không gọi LLM."""
    if not text or not text.strip():
        return "vi"

    # Kiểm tra ký tự tượng hình CJK (Nhật, Trung, Hàn)
    for ch in text:
        code = ord(ch)
        if (
            0x3040 <= code <= 0x30FF  # Hiragana, Katakana
            or 0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0xAC00 <= code <= 0xD7AF  # Hangul Syllables
        ):
            return "other"

    # Đếm ký tự có dấu tiếng Việt
    accented_count = sum(1 for ch in text if ch in VIETNAMESE_ACCENTED_CHARS)
    if accented_count >= 2:
        return "vi"

    words = [w.strip(".,?!:;()[]{}\"'").lower() for w in text.split()]
    words = [w for w in words if w]
    if not words:
        return "vi"

    vi_unaccented_hits = sum(1 for w in words if w in VIETNAMESE_UNACCENTED_WORDS)
    en_hits = sum(1 for w in words if w in ENGLISH_WORDS)

    if vi_unaccented_hits > en_hits:
        return "vi"
    elif en_hits > 0:
        return "en"

    return "vi"


def mask_pii(text: str) -> str:
    """Che thông tin PII: MSSV, CCCD, SĐT, Email cá nhân."""
    if not text:
        return ""

    # Che email
    text = EMAIL_RE.sub("[EMAIL]", text)

    # Che CCCD (12 chữ số)
    text = CCCD_RE.sub("[CCCD]", text)

    # Che Số điện thoại VN
    text = PHONE_VN_RE.sub("[SĐT]", text)

    # Che MSSV (8-10 chữ số)
    def _mask_mssv(match: re.Match) -> str:
        prefix = match.group(0)
        digits = match.group(1)
        return prefix.replace(digits, "[MSSV]")

    text = MSSV_RE.sub(_mask_mssv, text)

    return text


def detect_and_strip_injection(text: str) -> tuple[str, bool, list[str]]:
    """Phát hiện prompt injection, tước đoạn đó khỏi văn bản gửi LLM."""
    if not text:
        return text, False, []

    has_injection = False
    stripped_segments: list[str] = []

    # Kiểm tra theo từng câu
    sentences = re.split(r"(?<=[.!?\n])\s+", text)
    safe_sentences: list[str] = []

    for sentence in sentences:
        s_lower = sentence.lower()
        matched_kw = [kw for kw in INJECTION_KEYWORDS if kw in s_lower]
        if matched_kw:
            has_injection = True
            stripped_segments.append(sentence.strip())
        else:
            safe_sentences.append(sentence)

    cleaned_text = " ".join(safe_sentences).strip()
    return cleaned_text, has_injection, stripped_segments


def sanitize_input(body_raw: str) -> SanitizeResult:
    """Thực hiện toàn bộ quy trình R1 Sanitize."""
    if body_raw is None:
        body_raw = ""

    # 1. Bóc HTML
    no_html = strip_html(body_raw)

    # 2. Bóc quote & signature
    no_quote_sig = strip_quotes_and_signatures(no_html)

    # 3. Chuẩn hóa NFC
    nfc_text = unicodedata.normalize("NFC", no_quote_sig)

    # 4. Gộp khoảng trắng thừa
    collapsed = re.sub(r"[ \t]+", " ", nfc_text)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed).strip()

    # 5. Nhận diện ngôn ngữ
    lang = detect_language(collapsed)

    # 6. Phát hiện và tước Prompt Injection
    clean_body, injection_suspected, stripped_segments = detect_and_strip_injection(collapsed)

    # 7. Che PII trên bản sạch
    body_masked = mask_pii(clean_body)

    return SanitizeResult(
        body_raw=body_raw,
        body_clean=clean_body,
        body_masked=body_masked,
        language=lang,
        injection_suspected=injection_suspected,
        stripped_injection_segments=stripped_segments,
    )


def evaluate_cheap_guards(
    body_clean: str, language: str
) -> tuple[Decision | None, EscalationType | None, str | None]:
    """Cài đặt các chốt chặn rẻ ở R1 (Mục 8.1 spec). Không gọi LLM.

    1. Body rỗng -> INVALID_INPUT
    2. Body chỉ có ký hiệu -> INVALID_INPUT
    3. Ngôn ngữ ngoài vi/en -> ESCALATE / OUT_OF_POLICY
    """
    stripped = body_clean.strip()
    if not stripped or not any(char.isalnum() for char in stripped):
        return (
            Decision.INVALID_INPUT,
            None,
            "Nội dung email rỗng hoặc không có thông tin. Vui lòng nêu câu hỏi hoặc yêu cầu cần hỗ trợ.",
        )

    # Ngôn ngữ ngoài vi/en
    if language not in ("vi", "en"):
        return (
            Decision.ESCALATE,
            EscalationType.OUT_OF_POLICY,
            f"Ngôn ngữ '{language}' nằm ngoài phạm vi hỗ trợ tự động (chỉ hỗ trợ Tiếng Việt và Tiếng Anh).",
        )

    return None, None, None
