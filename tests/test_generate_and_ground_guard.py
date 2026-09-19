from __future__ import annotations

from datetime import date, datetime, timezone

from core.generate import generate_reply
from core.ground_guard import validate_groundedness
from core.pipeline import process_case
from core.types import (
    CaseInput,
    CaseStatus,
    ChunkLabel,
    Decision,
    Domain,
    DraftReply,
    EscalationType,
    EvidenceChunk,
    EvidenceResult,
    EvidenceStatus,
    Extraction,
    RequestItem,
)


def _make_evidence() -> EvidenceResult:
    chunk = EvidenceChunk(
        chunk_id="chunk_cw_01",
        doc_id="RL-2026-3150",
        breadcrumb="QĐ 3150/2026 · Điều 8 · Khoản 2",
        text="Thời hạn rút học phần được giải quyết trong 8 tuần đầu của học kỳ chính. "
             "Sinh viên nộp đơn online qua cổng thông tin và được hoàn 50% học phí nếu rút trước tuần thứ 4.",
        domain=Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.92,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49", "K50"],
        transitional_clause=False,
        conflict_flag=False,
    )
    return EvidenceResult(status=EvidenceStatus.OK, chunks=[chunk], failed_checks=[])


def _make_case_input(lang: str = "vi") -> CaseInput:
    subject = "Hỏi thời hạn rút môn" if lang == "vi" else "Question about course withdrawal deadline"
    body = "Khi nào hết hạn rút môn học kỳ này ạ?" if lang == "vi" else "When is the course withdrawal deadline?"
    return CaseInput(
        sender="sv@school.edu.vn",
        subject=subject,
        body=body,
        received_at=datetime.now(timezone.utc),
        channel="inbox",
    )


def _make_extraction(lang: str = "vi") -> Extraction:
    req = RequestItem(
        domain=Domain.COURSE_WITHDRAWAL,
        intent="hoi_thoi_han_rut_mon",
        is_informational=True,
        requires_personal_record=False,
        asks_exception=False,
        asks_appeal=False,
        asks_authority_decision=False,
    )
    return Extraction(
        language="en" if lang == "en" else "vi",
        requests=[req],
        critical_facts={},
        missing_critical_facts=[],
        injection_suspected=False,
        raw_json="{}",
    )


def test_generate_reply_vietnamese() -> None:
    ev = _make_evidence()
    inp = _make_case_input("vi")
    ext = _make_extraction("vi")

    draft = generate_reply(ev, inp, ext)
    assert draft.subject.startswith("Re:")
    assert "Chào em" in draft.body
    assert "[chunk_cw_01]" in draft.body
    assert "chunk_cw_01" in draft.citations


def test_generate_reply_english() -> None:
    ev = _make_evidence()
    inp = _make_case_input("en")
    ext = _make_extraction("en")

    draft = generate_reply(ev, inp, ext)
    assert draft.subject.startswith("Re:")
    assert "Dear student" in draft.body
    assert "[chunk_cw_01]" in draft.body


def test_ground_guard_passes_clean_draft() -> None:
    ev = _make_evidence()
    draft = DraftReply(
        subject="Re: Thời hạn rút môn",
        body="Chào em,\n\nTheo quy định của nhà trường, thời hạn rút học phần được giải quyết trong 8 tuần đầu của học kỳ chính [chunk_cw_01]. Sinh viên được hoàn 50% học phí nếu rút trước tuần thứ 4 [chunk_cw_01].\n\nTrân trọng,\nDSA",
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
    )

    passed, violations = validate_groundedness(draft, ev)
    assert passed is True
    assert len(violations) == 0
    assert draft.grounded is True


def test_ground_guard_fails_on_unknown_citation() -> None:
    ev = _make_evidence()
    draft = DraftReply(
        subject="Re: Test",
        body="Theo quy định [chunk_hacker_99], thời hạn rút môn là 8 tuần.",
        citations=["chunk_hacker_99"],
        grounded=True,
        guard_failures=[],
    )

    passed, violations = validate_groundedness(draft, ev)
    assert passed is False
    assert any("unknown_citation" in v for v in violations)
    assert draft.grounded is False


def test_ground_guard_fails_on_hallucinated_numbers() -> None:
    ev = _make_evidence()
    # Con số 999.000 không hề có trong evidence
    draft = DraftReply(
        subject="Re: Test",
        body="Chào em,\n\nLệ phí rút học phần của em là 999.000 VNĐ [chunk_cw_01].\n\nTrân trọng,\nDSA",
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
    )

    passed, violations = validate_groundedness(draft, ev)
    assert passed is False
    assert any("hallucinated_number" in v for v in violations)


def test_ground_guard_fails_on_forbidden_commitment() -> None:
    ev = _make_evidence()
    draft = DraftReply(
        subject="Re: Test",
        body="Chào em,\n\nChúng tôi đồng ý phê duyệt ngoại lệ rút học phần cho em trong 8 tuần [chunk_cw_01].\n\nTrân trọng,\nDSA",
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
    )

    passed, violations = validate_groundedness(draft, ev)
    assert passed is False
    assert any("authority_commitment" in v for v in violations)


def test_ground_guard_fails_on_low_citation_ratio() -> None:
    ev = _make_evidence()
    # 3 câu dài nhưng chỉ có 1 câu có citation -> tỷ lệ 1/3 = 0.33 < 0.6
    draft = DraftReply(
        subject="Re: Test",
        body=(
            "Chào em,\n\n"
            "Thời hạn rút học phần được giải quyết trong 8 tuần đầu [chunk_cw_01]. "
            "Sinh viên cần lưu ý nộp đơn đúng thời gian quy định tại văn phòng. "
            "Sau thời hạn này nhà trường sẽ không giải quyết bất kỳ trường hợp nào.\n\n"
            "Trân trọng,\nDSA"
        ),
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
    )

    passed, violations = validate_groundedness(draft, ev)
    assert passed is False
    assert any("low_citation_ratio" in v for v in violations)


def test_pipeline_downgrades_to_escalate_when_groundedness_fails() -> None:
    """Mục 8.5 spec: Fail bất kỳ mục nào -> ESCALATE / FACT_UNRESOLVED, giữ bản nháp cho người xem."""
    from unittest.mock import patch

    inp = _make_case_input("vi")

    # Mô phỏng generator sinh ra bản thảo chứa con số bịa đặt 999.000
    hallucinated_draft = DraftReply(
        subject=f"Re: {inp.subject}",
        body="Chào em,\n\nLệ phí hủy môn của em là 999.000 VNĐ [chunk_cw_01].\n\nTrân trọng,\nDSA",
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
    )

    with patch("core.pipeline.generate_reply", return_value=hallucinated_draft):
        res = process_case(inp)

    # Hệ thống lập tức hạ cấp về ESCALATE, KHÔNG TỰ SỬA SỐ
    assert res.decision.decision == Decision.ESCALATE
    assert res.decision.escalation_type == EscalationType.FACT_UNRESOLVED
    assert res.decision.rule_id == "P04"
    assert "groundedness_failed" in res.decision.reason
    assert res.status == CaseStatus.AWAITING_HUMAN
    # Bản thảo vẫn được giữ lại với grounded=False để chuyên viên đối chiếu
    assert res.draft is not None
    assert res.draft.grounded is False
    assert res.card is not None
