from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from core.types import (
    CaseInput,
    CaseStatus,
    ChunkLabel,
    Decision,
    Domain,
    DraftReply,
    EscalationCard,
    EscalationType,
    EvidenceChunk,
    EvidenceResult,
    EvidenceStatus,
    Extraction,
    PipelineResult,
    PolicyDecision,
    RequestItem,
    SourceStatus,
)


def test_enums_members_and_values():
    # Decision: 3 members
    assert set(Decision) == {Decision.AUTO_REPLY, Decision.ESCALATE, Decision.INVALID_INPUT}
    assert Decision.AUTO_REPLY.value == "AUTO_REPLY"
    assert Decision.ESCALATE.value == "ESCALATE"
    assert Decision.INVALID_INPUT.value == "INVALID_INPUT"

    # EscalationType: 3 members
    assert set(EscalationType) == {
        EscalationType.FACT_UNRESOLVED,
        EscalationType.OUT_OF_POLICY,
        EscalationType.AUTHORITY_REQUIRED,
    }
    assert EscalationType.FACT_UNRESOLVED.value == "FACT_UNRESOLVED"
    assert EscalationType.OUT_OF_POLICY.value == "OUT_OF_POLICY"
    assert EscalationType.AUTHORITY_REQUIRED.value == "AUTHORITY_REQUIRED"

    # EvidenceStatus: 7 members
    assert set(EvidenceStatus) == {
        EvidenceStatus.OK,
        EvidenceStatus.NO_AUTHORITATIVE_SOURCE,
        EvidenceStatus.AUTHORITY_CONTENT,
        EvidenceStatus.CONFLICTING_SOURCES,
        EvidenceStatus.SCOPE_MISMATCH,
        EvidenceStatus.FACT_MISSING,
        EvidenceStatus.UNSUPPORTED_DOMAIN,
    }
    assert EvidenceStatus.OK.value == "ok"
    assert EvidenceStatus.NO_AUTHORITATIVE_SOURCE.value == "no_authoritative_source"
    assert EvidenceStatus.AUTHORITY_CONTENT.value == "authority_content"
    assert EvidenceStatus.CONFLICTING_SOURCES.value == "conflicting_sources"
    assert EvidenceStatus.SCOPE_MISMATCH.value == "scope_mismatch"
    assert EvidenceStatus.FACT_MISSING.value == "fact_missing"
    assert EvidenceStatus.UNSUPPORTED_DOMAIN.value == "unsupported_domain"

    # CaseStatus: 12 members
    assert set(CaseStatus) == {
        CaseStatus.RECEIVED,
        CaseStatus.PROCESSING,
        CaseStatus.INVALID_INPUT,
        CaseStatus.PENDING_SEND,
        CaseStatus.SENT,
        CaseStatus.CANCELLED,
        CaseStatus.AWAITING_HUMAN,
        CaseStatus.HUMAN_DECIDED,
        CaseStatus.PENDING_APPROVAL,
        CaseStatus.RESOLVED,
        CaseStatus.NEEDS_RECHECK,
        CaseStatus.ERROR,
    }

    # Domain: 4 members
    assert set(Domain) == {
        Domain.CONDUCT_SCORE,
        Domain.COURSE_WITHDRAWAL,
        Domain.GRADE_APPEAL,
        Domain.UNKNOWN,
    }
    assert Domain.CONDUCT_SCORE.value == "conduct_score"
    assert Domain.COURSE_WITHDRAWAL.value == "course_withdrawal"
    assert Domain.GRADE_APPEAL.value == "grade_appeal"
    assert Domain.UNKNOWN.value == "unknown"

    # SourceStatus: 4 members
    assert set(SourceStatus) == {
        SourceStatus.PENDING_REVIEW,
        SourceStatus.ACTIVE,
        SourceStatus.SUPERSEDED,
        SourceStatus.REJECTED,
    }

    # ChunkLabel: 2 members
    assert set(ChunkLabel) == {
        ChunkLabel.AUTO_ANSWERABLE,
        ChunkLabel.HUMAN_ONLY,
    }
    assert ChunkLabel.AUTO_ANSWERABLE.value == "auto_answerable"
    assert ChunkLabel.HUMAN_ONLY.value == "human_only"


def test_dataclasses_instantiation():
    now = datetime.now(timezone.utc)
    today = now.date()

    # CaseInput (frozen)
    inp = CaseInput(
        sender="sinhvien@university.edu.vn",
        subject="Hỏi thời hạn rút học phần",
        body="Thầy cô cho em hỏi hạn rút học phần kỳ 1 là ngày nào ạ?",
        received_at=now,
        channel="paste",
        external_id="ext-001",
    )
    assert inp.channel == "paste"
    with pytest.raises(FrozenInstanceError):
        inp.sender = "other@edu.vn"  # type: ignore[misc]

    # RequestItem
    req = RequestItem(
        domain=Domain.COURSE_WITHDRAWAL,
        intent="hỏi hạn rút học phần",
        is_informational=True,
        requires_personal_record=False,
        asks_exception=False,
        asks_appeal=False,
        asks_authority_decision=False,
    )
    assert req.domain == Domain.COURSE_WITHDRAWAL

    # Extraction
    ext = Extraction(
        language="vi",
        requests=[req],
        critical_facts={"term": "HK1"},
        missing_critical_facts=[],
        injection_suspected=False,
        raw_json='{"requests": []}',
        llm_error=None,
    )
    assert ext.language == "vi"

    # EvidenceChunk (frozen)
    chunk = EvidenceChunk(
        chunk_id="chunk_01",
        doc_id="doc_01",
        breadcrumb="QĐ 3150/2026 · Điều 8 · Khoản 2",
        text="Thời hạn rút học phần trước tuần thứ 8 của học kỳ.",
        domain=Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.88,
        effective_from=today,
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49"],
        transitional_clause=False,
        conflict_flag=False,
    )
    assert chunk.chunk_id == "chunk_01"
    with pytest.raises(FrozenInstanceError):
        chunk.score = 0.99  # type: ignore[misc]

    # EvidenceResult
    ev_res = EvidenceResult(
        status=EvidenceStatus.OK,
        chunks=[chunk],
        failed_checks=[],
    )
    assert ev_res.status == EvidenceStatus.OK

    # PolicyDecision
    p_dec = PolicyDecision(
        decision=Decision.AUTO_REPLY,
        escalation_type=None,
        rule_id="P05",
        reason="Câu hỏi thường quy có căn cứ quy định.",
        evidence_ids=["chunk_01"],
        corpus_version="cv_abc123",
    )
    assert p_dec.rule_id == "P05"

    # DraftReply
    draft = DraftReply(
        subject="Re: Hỏi thời hạn rút học phần",
        body="Chào em, hạn rút học phần là trước tuần thứ 8 [chunk_01].",
        citations=["chunk_01"],
        grounded=True,
        guard_failures=[],
    )
    assert draft.grounded is True

    # EscalationCard
    card = EscalationCard(
        summary="Sinh viên hỏi hạn rút môn",
        facts=["Sinh viên K48", "Học kỳ 1"],
        basis=[("QĐ 3150/2026 · Điều 8", "Hạn rút tuần 8")],
        question="Chấp thuận đơn rút môn hay từ chối?",
        options=["Chấp thuận", "Từ chối"],
        escalation_type=EscalationType.OUT_OF_POLICY,
        partial_draft=None,
    )
    assert card.escalation_type == EscalationType.OUT_OF_POLICY

    # PipelineResult
    pipe_res = PipelineResult(
        case_id="c_01ABC",
        trace_id="tr_01ABC",
        status=CaseStatus.PENDING_SEND,
        decision=p_dec,
        extraction=ext,
        evidence=ev_res,
        draft=draft,
        card=None,
        corpus_version="cv_abc123",
        step_latencies_ms={"R0": 5, "R1": 10},
        started_at=now,
        finished_at=now,
    )
    assert pipe_res.case_id == "c_01ABC"
    assert pipe_res.decision.decision == Decision.AUTO_REPLY
