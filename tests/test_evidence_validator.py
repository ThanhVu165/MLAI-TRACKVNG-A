from __future__ import annotations

from datetime import date

from core.evidence import validate_evidence
from core.types import (
    ChunkLabel,
    Domain,
    EvidenceChunk,
    EvidenceStatus,
    Extraction,
    RequestItem,
)


def _sample_chunk(
    *,
    chunk_id: str = "chunk_01",
    score: float = 0.85,
    domain: Domain = Domain.COURSE_WITHDRAWAL,
    label: ChunkLabel = ChunkLabel.AUTO_ANSWERABLE,
    conflict_flag: bool = False,
    cohorts: list[str] | None = None,
    transitional_clause: bool = False,
    text: str = "Thời hạn rút học phần trước tuần thứ 8.",
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        doc_id="DOC-01",
        breadcrumb="QĐ 3150 · Điều 8",
        text=text,
        domain=domain,
        label=label,
        score=score,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=cohorts if cohorts is not None else ["K48", "K49"],
        transitional_clause=transitional_clause,
        conflict_flag=conflict_flag,
    )


def _sample_extraction(
    domain: Domain = Domain.COURSE_WITHDRAWAL,
    cohort: str = "K48",
    missing_facts: list[str] | None = None,
) -> Extraction:
    req = RequestItem(
        domain=domain,
        intent="hỏi rút môn",
        is_informational=True,
        requires_personal_record=False,
        asks_exception=False,
        asks_appeal=False,
        asks_authority_decision=False,
    )
    critical_facts = {"cohort": cohort} if cohort else {}
    return Extraction(
        language="vi",
        requests=[req],
        critical_facts=critical_facts,
        missing_critical_facts=missing_facts or [],
        injection_suspected=False,
        raw_json="{}",
        llm_error=None,
    )


def test_check_1_similarity_threshold():
    # Chunk có similarity < 0.35 -> NO_AUTHORITATIVE_SOURCE
    chunk = _sample_chunk(score=0.25)
    ext = _sample_extraction()
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.NO_AUTHORITATIVE_SOURCE
    assert "check_1_similarity_threshold" in res.failed_checks


def test_check_2_domain_mismatch():
    # Chunk thuộc GRADE_APPEAL nhưng request hỏi COURSE_WITHDRAWAL
    chunk = _sample_chunk(domain=Domain.GRADE_APPEAL)
    ext = _sample_extraction(domain=Domain.COURSE_WITHDRAWAL)
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.NO_AUTHORITATIVE_SOURCE
    assert "check_2_domain_mismatch" in res.failed_checks


def test_check_3_unsupported_domain():
    # Request thuộc domain UNKNOWN ngoài supported_domains
    chunk = _sample_chunk(domain=Domain.UNKNOWN)
    ext = _sample_extraction(domain=Domain.UNKNOWN)
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.UNSUPPORTED_DOMAIN
    assert "check_3_unsupported_domain" in res.failed_checks


def test_check_4_human_only_label():
    # Chunk có label HUMAN_ONLY -> AUTHORITY_CONTENT
    chunk = _sample_chunk(label=ChunkLabel.HUMAN_ONLY)
    ext = _sample_extraction()
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.AUTHORITY_CONTENT
    assert "check_4_authority_content_human_only" in res.failed_checks


def test_check_5_conflicting_sources():
    # Chunk có cờ conflict_flag=True -> CONFLICTING_SOURCES
    chunk = _sample_chunk(conflict_flag=True)
    ext = _sample_extraction()
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.CONFLICTING_SOURCES
    assert "check_5_conflicting_sources" in res.failed_checks


def test_check_6_scope_mismatch():
    # Chunk chỉ áp dụng cho K48 nhưng sinh viên K50 -> SCOPE_MISMATCH
    chunk = _sample_chunk(cohorts=["K48"])
    ext = _sample_extraction(cohort="K50")
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.SCOPE_MISMATCH
    assert "check_6_scope_mismatch" in res.failed_checks


def test_check_7_transitional_clause_without_cohort():
    # Chunk có transitional_clause=True mà email không nêu rõ khóa -> FACT_MISSING
    chunk = _sample_chunk(transitional_clause=True)
    ext = _sample_extraction(cohort="")  # Không có cohort
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.FACT_MISSING
    assert "check_7_fact_missing" in res.failed_checks


def test_check_7b_missing_critical_facts():
    # missing_critical_facts không rỗng -> FACT_MISSING
    chunk = _sample_chunk()
    ext = _sample_extraction(missing_facts=["term_code"])
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.FACT_MISSING
    assert "check_7_fact_missing" in res.failed_checks


def test_all_checks_ok():
    # Tất cả kiểm tra đều thỏa mãn -> OK
    chunk = _sample_chunk(score=0.90, cohorts=["K48", "K49"])
    ext = _sample_extraction(cohort="K48")
    res = validate_evidence([chunk], ext)
    assert res.status == EvidenceStatus.OK
    assert len(res.failed_checks) == 0


def test_auto_reply_keeps_only_relevant_non_conflicting_evidence() -> None:
    deadline = _sample_chunk(chunk_id="deadline", score=0.9)
    refund_conflict = _sample_chunk(
        chunk_id="refund_conflict",
        score=0.8,
        conflict_flag=True,
        text="Sinh viên được hoàn 60% học phí khi rút học phần trong tuần thứ tư.",
    )
    low_score = _sample_chunk(chunk_id="low_score", score=0.2)
    wrong_domain = _sample_chunk(
        chunk_id="wrong_domain",
        score=0.95,
        domain=Domain.GRADE_APPEAL,
    )
    ext = _sample_extraction()
    ext.requests[0].intent = "Hỏi thời hạn rút học phần"

    res = validate_evidence([refund_conflict, low_score, wrong_domain, deadline], ext)

    assert res.status == EvidenceStatus.OK
    assert [chunk.chunk_id for chunk in res.chunks] == ["deadline"]


def test_relevant_conflict_is_preserved_for_human_review() -> None:
    refund_conflict = _sample_chunk(
        chunk_id="refund_conflict",
        conflict_flag=True,
        text="Sinh viên được hoàn 60% học phí khi rút học phần trong tuần thứ tư.",
    )
    ext = _sample_extraction()
    ext.requests[0].intent = "Hỏi tỷ lệ hoàn học phí khi rút học phần"

    res = validate_evidence([refund_conflict], ext)

    assert res.status == EvidenceStatus.CONFLICTING_SOURCES
    assert [chunk.chunk_id for chunk in res.chunks] == ["refund_conflict"]
