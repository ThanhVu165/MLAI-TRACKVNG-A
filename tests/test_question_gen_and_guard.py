from __future__ import annotations

from datetime import date, datetime, timezone

from core.question_gen import generate_escalation_card, load_fallback_template
from core.question_guard import ensure_valid_escalation_card, validate_question_quality
from core.types import (
    CaseInput,
    ChunkLabel,
    Domain,
    EscalationCard,
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
        breadcrumb="QĐ 3150/2026 · Điều 8",
        text="Thời hạn rút học phần được giải quyết trong 8 tuần đầu của học kỳ.",
        domain=Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.9,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K49"],
        transitional_clause=False,
        conflict_flag=False,
    )
    return EvidenceResult(status=EvidenceStatus.OK, chunks=[chunk], failed_checks=[])


def _make_extraction(asks_exception: bool = True, multi_intent: bool = False) -> Extraction:
    req1 = RequestItem(
        domain=Domain.COURSE_WITHDRAWAL,
        intent="Xin rút môn sau hạn vì lý do sức khỏe",
        is_informational=not asks_exception,
        requires_personal_record=False,
        asks_exception=asks_exception,
        asks_appeal=False,
        asks_authority_decision=asks_exception,
    )
    requests = [req1]
    if multi_intent:
        req2 = RequestItem(
            domain=Domain.COURSE_WITHDRAWAL,
            intent="Hỏi thời hạn rút môn chính thức",
            is_informational=True,
            requires_personal_record=False,
            asks_exception=False,
            asks_appeal=False,
            asks_authority_decision=False,
        )
        requests.append(req2)

    return Extraction(
        language="vi",
        requests=requests,
        critical_facts={"cohort": "K49", "reason": "nằm viện"},
        missing_critical_facts=["giấy xác nhận của bệnh viện"],
        injection_suspected=False,
        raw_json="{}",
    )


def test_generate_escalation_card_structure() -> None:
    ev = _make_evidence()
    ext = _make_extraction(asks_exception=True)

    card = generate_escalation_card(ext, ev, EscalationType.AUTHORITY_REQUIRED)

    # Khẳng định 4 khối bắt buộc
    assert len(card.summary.split()) <= 30
    assert len(card.facts) >= 2
    assert len(card.basis) >= 1
    assert card.question.endswith("?")
    assert 2 <= len(card.options) <= 4
    assert card.escalation_type == EscalationType.AUTHORITY_REQUIRED


def test_generate_escalation_card_multi_intent() -> None:
    ev = _make_evidence()
    ext = _make_extraction(asks_exception=True, multi_intent=True)
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi thời hạn và xin rút môn",
        body="...",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        channel="paste",
    )

    card = generate_escalation_card(ext, ev, EscalationType.AUTHORITY_REQUIRED, inp=inp)

    # Khẳng định thông báo email đa ý định theo Mục 8.2 spec
    assert "Phần A đã soạn sẵn, phần B cần anh/chị quyết" in card.summary
    assert card.partial_draft is not None
    assert len(card.partial_draft.citations) > 0


def test_question_guard_passes_clean_card() -> None:
    card = EscalationCard(
        summary="Yêu cầu xin rút môn sau hạn của sinh viên.",
        facts=["Khóa sinh viên: K49", "Lý do: nằm viện điều trị"],
        basis=[("QĐ 3150/2026 · Điều 8", "Rút môn sau hạn do Trưởng phòng duyệt.")],
        question="Chuyên viên có đồng ý phê duyệt đơn rút môn cho sinh viên K49 này không?",
        options=["Đồng ý phê duyệt", "Từ chối yêu cầu", "Chuyển Trưởng phòng xem xét"],
        escalation_type=EscalationType.AUTHORITY_REQUIRED,
        partial_draft=None,
    )

    passed, violations = validate_question_quality(card)
    assert passed is True
    assert len(violations) == 0


def test_question_guard_blocks_forbidden_blocklist() -> None:
    # Câu hỏi chứa cụm blocklist "vui lòng xem xét" hoặc "nhờ anh/chị xem"
    card = EscalationCard(
        summary="Yêu cầu sinh viên.",
        facts=["Sinh viên K49"],
        basis=[("Quy chế", "...")],
        question="Nhờ anh/chị xem xét trường hợp của sinh viên K49 này có được không?",
        options=["Đồng ý", "Từ chối"],
        escalation_type=EscalationType.AUTHORITY_REQUIRED,
        partial_draft=None,
    )

    passed, violations = validate_question_quality(card)
    assert passed is False
    assert any("forbidden_blocklist" in v for v in violations)


def test_question_guard_blocks_wrong_length_or_multiple_questions() -> None:
    # Câu hỏi quá ngắn (< 8 từ) và có 2 dấu hỏi
    card = EscalationCard(
        summary="Tóm tắt ngắn.",
        facts=["K49"],
        basis=[("Quy chế", "...")],
        question="Duyệt cho K49? Có duyệt không?",
        options=["Có", "Không"],
        escalation_type=EscalationType.AUTHORITY_REQUIRED,
        partial_draft=None,
    )

    passed, violations = validate_question_quality(card)
    assert passed is False
    assert any("word_count" in v for v in violations)
    assert any("question_marks" in v for v in violations)


def test_ensure_valid_escalation_card_fallback_on_invalid() -> None:
    ev = _make_evidence()
    ext = _make_extraction(asks_exception=True)

    # Thẻ xấu vi phạm blocklist
    bad_card = EscalationCard(
        summary="Xấu",
        facts=["K49"],
        basis=[],
        question="Vui lòng xem xét?",
        options=[],
        escalation_type=EscalationType.AUTHORITY_REQUIRED,
        partial_draft=None,
    )

    fixed_card = ensure_valid_escalation_card(bad_card, ext, ev, EscalationType.AUTHORITY_REQUIRED)

    # Khẳng định thẻ sau khi qua guard đã được thay thế bằng thẻ hợp lệ
    passed, violations = validate_question_quality(fixed_card)
    assert passed is True
    assert len(violations) == 0
    assert 2 <= len(fixed_card.options) <= 4


def test_load_fallback_template_for_all_types() -> None:
    for et in [EscalationType.FACT_UNRESOLVED, EscalationType.OUT_OF_POLICY, EscalationType.AUTHORITY_REQUIRED]:
        tpl = load_fallback_template(et)
        assert tpl.question.endswith("?")
        assert len(tpl.options) >= 2
        assert len(tpl.facts) >= 1
        assert len(tpl.basis) >= 1
