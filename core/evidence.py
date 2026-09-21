from __future__ import annotations

import logging

from core.types import (
    ChunkLabel,
    Domain,
    EvidenceChunk,
    EvidenceResult,
    EvidenceStatus,
    Extraction,
)

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.35

DEFAULT_SUPPORTED_DOMAINS = frozenset(
    {
        Domain.CONDUCT_SCORE,
        Domain.COURSE_WITHDRAWAL,
        Domain.GRADE_APPEAL,
    }
)


def get_supported_domains() -> frozenset[Domain]:
    """Lấy danh sách các domain được hỗ trợ trong Sprint 1."""
    try:
        from corpus.api import supported_domains  # type: ignore[import-not-found]

        return frozenset(supported_domains())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Lỗi khi gọi supported_domains từ corpus.api: %s", exc)
        return DEFAULT_SUPPORTED_DOMAINS


def _is_conflict_relevant(chunk: EvidenceChunk, extraction: Extraction) -> bool:
    """Kiểm tra chunk có cờ mâu thuẫn (conflict_flag) có cùng chủ đề với yêu cầu không (Mục 8.4 spec)."""
    if not chunk.conflict_flag:
        return False
    intents = " ".join([req.intent for req in extraction.requests]).casefold()
    chunk_text = chunk.text.casefold()
    # Nếu chunk conflict về tỷ lệ hoàn học phí: chỉ kích hoạt khi yêu cầu thực sự hỏi về hoàn tiền/học phí
    if "hoàn" in chunk_text and "học phí" in chunk_text:
        return "hoàn" in intents or "học phí" in intents
    # Mọi trường hợp conflict khác: coi như có mâu thuẫn
    return True


def validate_evidence(
    chunks: list[EvidenceChunk],
    extraction: Extraction,
    case_id: str = "",
) -> EvidenceResult:
    """R5: Evidence Validator - 7 bài kiểm tra căn cứ pháp lý theo Mục 8.4 spec.

    Thực hiện lần lượt 7 kiểm tra theo đúng thứ tự.
    Trả về status của bài kiểm tra đầu tiên fail, nhưng ghi nhận tất cả kiểm tra fail vào failed_checks.
    """
    failed_checks: list[str] = []
    first_fail_status: EvidenceStatus | None = None

    supported_domains = get_supported_domains()
    requested_domains = [req.domain for req in extraction.requests]
    known_requested_domains = {domain for domain in requested_domains if domain != Domain.UNKNOWN}

    # -----------------------------------------------------------------------
    # Kiểm tra 1: Có >= 1 chunk vượt ngưỡng similarity (0.35)
    # -----------------------------------------------------------------------
    valid_similarity = [c for c in chunks if c.score >= SIMILARITY_THRESHOLD]
    if not valid_similarity:
        failed_checks.append("check_1_similarity_threshold")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.NO_AUTHORITATIVE_SOURCE

    # -----------------------------------------------------------------------
    # Kiểm tra 2: Chunk thuộc đúng domain được hỏi
    # -----------------------------------------------------------------------
    domain_matched_chunks = [c for c in valid_similarity if c.domain in requested_domains]
    matched_domains = {chunk.domain for chunk in domain_matched_chunks}
    if not known_requested_domains.issubset(matched_domains):
        failed_checks.append("check_2_domain_mismatch")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.NO_AUTHORITATIVE_SOURCE

    # -----------------------------------------------------------------------
    # Kiểm tra 3: Domain được hỏi nằm trong supported_domains()
    # -----------------------------------------------------------------------
    has_unsupported_domain = any(d not in supported_domains for d in requested_domains)
    if has_unsupported_domain:
        failed_checks.append("check_3_unsupported_domain")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.UNSUPPORTED_DOMAIN

    # -----------------------------------------------------------------------
    # Kiểm tra 4: Mọi chunk dùng để trả lời có label == auto_answerable
    # -----------------------------------------------------------------------
    has_human_only = any(c.label == ChunkLabel.HUMAN_ONLY for c in domain_matched_chunks)
    if has_human_only:
        failed_checks.append("check_4_authority_content_human_only")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.AUTHORITY_CONTENT

    # -----------------------------------------------------------------------
    # Kiểm tra 5: Không có cặp chunk ACTIVE conflict_flag cùng chủ đề
    # -----------------------------------------------------------------------
    has_conflict = any(_is_conflict_relevant(c, extraction) for c in domain_matched_chunks)
    if has_conflict:
        failed_checks.append("check_5_conflicting_sources")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.CONFLICTING_SOURCES

    # -----------------------------------------------------------------------
    # Kiểm tra 6: Scope khớp (applies_to / cohorts) hoặc không cần
    # -----------------------------------------------------------------------
    user_cohort = (
        extraction.critical_facts.get("cohort")
        or extraction.critical_facts.get("student_cohort")
        or extraction.critical_facts.get("khoa")
    )
    user_applies_to = extraction.critical_facts.get("applies_to")
    scope_failed = any(
        (
            chunk.cohorts
            and "all" not in chunk.cohorts
            and user_cohort
            and user_cohort not in chunk.cohorts
        )
        or (
            chunk.applies_to
            and "all" not in chunk.applies_to
            and user_applies_to
            and user_applies_to not in chunk.applies_to
        )
        for chunk in domain_matched_chunks
    )
    if scope_failed:
        failed_checks.append("check_6_scope_mismatch")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.SCOPE_MISMATCH

    # -----------------------------------------------------------------------
    # Kiểm tra 7: missing_critical_facts rỗng; nếu transitional_clause thì bắt buộc biết khóa
    # -----------------------------------------------------------------------
    facts_missing = False
    if extraction.missing_critical_facts:
        facts_missing = True

    # Nếu chunk có điều khoản chuyển tiếp -> bắt buộc phải biết khóa
    has_transitional = any(c.transitional_clause for c in domain_matched_chunks)
    if has_transitional and not user_cohort:
        facts_missing = True

    if facts_missing:
        failed_checks.append("check_7_fact_missing")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.FACT_MISSING

    # -----------------------------------------------------------------------
    # Tổng kết kết quả
    # -----------------------------------------------------------------------
    final_status = first_fail_status if first_fail_status is not None else EvidenceStatus.OK
    answerable_chunks = [
        chunk
        for chunk in (domain_matched_chunks if requested_domains else valid_similarity)
        if chunk.label == ChunkLabel.AUTO_ANSWERABLE and not chunk.conflict_flag
    ]
    if final_status == EvidenceStatus.OK and not answerable_chunks:
        final_status = EvidenceStatus.NO_AUTHORITATIVE_SOURCE
        failed_checks.append("check_2_domain_mismatch")

    result_chunks = (
        answerable_chunks
        if final_status == EvidenceStatus.OK
        else domain_matched_chunks or valid_similarity or chunks
    )

    _log_evidence_audit(case_id, failed_checks)

    return EvidenceResult(
        status=final_status,
        chunks=result_chunks,
        failed_checks=failed_checks,
    )


def _log_evidence_audit(case_id: str, failed_checks: list[str]) -> None:
    """Ghi nhận audit event EVIDENCE_VALIDATED nếu infra khả dụng."""
    if not case_id:
        return
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(
            case_id=case_id,
            actor="SYSTEM",
            action="EVIDENCE_VALIDATED",
            reason=",".join(failed_checks) if failed_checks else "all_checks_passed",
        )
    except ImportError:
        logger.debug("infra.audit chưa sẵn sàng — bỏ qua ghi audit trong môi trường phát triển")
    except Exception:
        logger.exception("Ghi audit EVIDENCE_VALIDATED thất bại")
