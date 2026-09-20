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
    domain_matched_chunks = [
        c for c in chunks if any(c.domain == d for d in requested_domains if d != Domain.UNKNOWN)
    ]
    if not domain_matched_chunks and any(d != Domain.UNKNOWN for d in requested_domains):
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
    has_human_only = any(c.label == ChunkLabel.HUMAN_ONLY for c in chunks)
    if has_human_only:
        failed_checks.append("check_4_authority_content_human_only")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.AUTHORITY_CONTENT

    # -----------------------------------------------------------------------
    # Kiểm tra 5: Không có cặp chunk ACTIVE conflict_flag cùng chủ đề
    # -----------------------------------------------------------------------
    has_conflict = any(c.conflict_flag for c in chunks)
    if has_conflict:
        failed_checks.append("check_5_conflicting_sources")
        if first_fail_status is None:
            first_fail_status = EvidenceStatus.CONFLICTING_SOURCES

    # -----------------------------------------------------------------------
    # Kiểm tra 6: Scope khớp (applies_to / cohorts) hoặc không cần
    # -----------------------------------------------------------------------
    user_cohort = extraction.critical_facts.get("cohort")
    scope_failed = False
    for c in chunks:
        if c.cohorts and user_cohort and user_cohort not in c.cohorts:
            scope_failed = True
            break
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
    has_transitional = any(c.transitional_clause for c in chunks)
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

    _log_evidence_audit(case_id, failed_checks)

    return EvidenceResult(
        status=final_status,
        chunks=chunks,
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
