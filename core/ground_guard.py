from __future__ import annotations

import logging
import re

from core.types import DraftReply, EvidenceResult

logger = logging.getLogger(__name__)

# Danh sách cụm từ cam kết vượt quyền bị cấm tuyệt đối theo Mục 8.5 spec
FORBIDDEN_COMMITMENTS = (
    "chúng tôi đồng ý",
    "đã được duyệt",
    "được chấp thuận",
    "ngoại lệ",
    "bạn sẽ được",
    "we approve",
)

# Regex trích xuất số liệu, ngày tháng, điều khoản, mẫu đơn
RE_NUMBERS_AND_DATES = re.compile(r"\b\d+[\d.,/]*\b")
RE_ARTICLE = re.compile(r"\bĐiều\s+\d+\b", re.IGNORECASE)
RE_FORM = re.compile(r"\bMẫu\s+[A-Z0-9-]+\b", re.IGNORECASE)
RE_CITATION = re.compile(r"\[([a-zA-Z0-9_\-]+)\]")


def _is_chunk_active(chunk_id: str) -> bool:
    """Kiểm tra chunk có đang ACTIVE trên corpus.api không."""
    try:
        from corpus.api import is_active  # type: ignore[import-not-found]

        return bool(is_active(chunk_id))
    except ImportError:
        # Môi trường stub / offline: chunk tồn tại là active
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Kiểm tra chunk active thất bại: %s", exc)
        return False


def _clean_body_for_sentence_counting(body: str) -> list[str]:
    """Tách body thành danh sách các câu có nghĩa để tính tỷ lệ citation."""
    # Loại bỏ các dòng chào hỏi và chữ ký thông thường
    skip_phrases = [
        "chào em",
        "kính gửi",
        "thân chào",
        "dear",
        "hello",
        "cảm ơn em",
        "thank you",
        "chúc em",
        "trân trọng",
        "thân ái",
        "văn phòng công tác sinh viên",
        "department of student affairs",
        "sincerely",
        "regards",
        "best regards",
    ]
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    content_lines: list[str] = []

    for line in lines:
        line_lower = line.lower()
        if any(line_lower.startswith(p) or line_lower == p for p in skip_phrases):
            continue
        content_lines.append(line)

    full_content = " ".join(content_lines)
    # Tách câu theo dấu chấm, chấm than, chấm hỏi hoặc ngắt đoạn
    raw_sentences = re.split(r"[.!?]+", full_content)
    sentences = [s.strip() for s in raw_sentences if len(s.strip().split()) >= 3]
    return sentences


def validate_groundedness(
    draft: DraftReply,
    evidence_res: EvidenceResult,
    case_id: str = "",
) -> tuple[bool, list[str]]:
    """R8a: Groundedness Guard (Mục 8.5 spec & Task A-16).

    Thực hiện 4 kiểm tra nghiêm ngặt:
    1. Mọi citation tồn tại và chunk đang ACTIVE.
    2. Mọi con số, ngày tháng, biểu mẫu trong body xuất hiện trong evidence text.
    3. Không chứa cụm cam kết vượt quyền.
    4. Tỷ lệ câu có citation >= 0.6.

    Trả về (passed: bool, failed_reasons: list[str]).
    Nếu thất bại: Cập nhật draft.grounded = False và ghi audit log.
    """
    failed_reasons: list[str] = []
    chunk_map = {c.chunk_id: c for c in evidence_res.chunks}
    evidence_combined_text = " ".join(
        f"{c.breadcrumb} {c.doc_id} {c.text}" for c in evidence_res.chunks
    )

    # -----------------------------------------------------------------------
    # Kiểm tra 1: Mọi citation tồn tại và chunk active
    # -----------------------------------------------------------------------
    if not draft.citations:
        failed_reasons.append("groundedness_failed:missing_citations")
    else:
        for cid in draft.citations:
            if cid not in chunk_map:
                failed_reasons.append(f"groundedness_failed:unknown_citation_{cid}")
            elif not _is_chunk_active(cid):
                failed_reasons.append(f"groundedness_failed:inactive_citation_{cid}")

    # -----------------------------------------------------------------------
    # Kiểm tra 2: Mọi con số, ngày tháng, tên biểu mẫu xuất hiện trong evidence
    # -----------------------------------------------------------------------
    # Tách body, loại bỏ các chuỗi citation dạng [chunk_id] để không bị so khớp nhầm số ID
    body_no_citations = RE_CITATION.sub(" ", draft.body)

    # 2a. Đối chiếu con số, ngày tháng
    body_numbers = set(RE_NUMBERS_AND_DATES.findall(body_no_citations))
    evidence_numbers = set(RE_NUMBERS_AND_DATES.findall(evidence_combined_text))

    for num in body_numbers:
        if num not in evidence_numbers:
            # Kiểm tra xem có phải dạng chuẩn hóa khác (ví dụ: 50.000 vs 50000)
            clean_num = num.replace(".", "").replace(",", "")
            clean_evidence_numbers = {
                en.replace(".", "").replace(",", "") for en in evidence_numbers
            }
            if clean_num not in clean_evidence_numbers:
                failed_reasons.append(f"groundedness_failed:hallucinated_number_{num}")
                break

    # 2b. Đối chiếu tên Điều khoản
    body_articles = set(RE_ARTICLE.findall(body_no_citations))
    for art in body_articles:
        if art.lower() not in evidence_combined_text.lower():
            failed_reasons.append(f"groundedness_failed:hallucinated_article_{art}")
            break

    # 2c. Đối chiếu tên Biểu mẫu
    body_forms = set(RE_FORM.findall(body_no_citations))
    for form in body_forms:
        if form.lower() not in evidence_combined_text.lower():
            failed_reasons.append(f"groundedness_failed:hallucinated_form_{form}")
            break

    # -----------------------------------------------------------------------
    # Kiểm tra 3: Không chứa cụm cam kết vượt quyền
    # -----------------------------------------------------------------------
    body_lower = draft.body.lower()
    for forbidden in FORBIDDEN_COMMITMENTS:
        if forbidden in body_lower:
            failed_reasons.append(f"groundedness_failed:authority_commitment_{forbidden}")
            break

    # -----------------------------------------------------------------------
    # Kiểm tra 4: Tỷ lệ câu có citation >= 0.6
    # -----------------------------------------------------------------------
    sentences = _clean_body_for_sentence_counting(draft.body)
    if sentences:
        cited_sentences = 0
        for s in sentences:
            if RE_CITATION.search(s):
                cited_sentences += 1
        ratio = cited_sentences / len(sentences)
        if ratio < 0.6:
            failed_reasons.append(f"groundedness_failed:low_citation_ratio_{ratio:.2f}")
    elif not draft.citations:
        failed_reasons.append("groundedness_failed:low_citation_ratio_0.00")

    # -----------------------------------------------------------------------
    # Tổng kết
    # -----------------------------------------------------------------------
    passed = len(failed_reasons) == 0
    draft.grounded = passed
    draft.guard_failures = failed_reasons

    if not passed:
        _log_groundedness_audit(case_id, failed_reasons)

    return passed, failed_reasons


def _log_groundedness_audit(case_id: str, failed_reasons: list[str]) -> None:
    """Ghi nhận audit event GROUNDEDNESS_FAILED nếu infra khả dụng."""
    if not case_id:
        return
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(
            case_id=case_id,
            actor="SYSTEM",
            action="GROUNDEDNESS_FAILED",
            reason="; ".join(failed_reasons),
        )
    except ImportError:
        logger.debug("infra.audit chưa cấu hình — bỏ qua")
    except Exception:
        logger.exception("Ghi audit GROUNDEDNESS_FAILED thất bại")
