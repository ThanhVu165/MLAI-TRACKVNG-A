from datetime import datetime, timezone

from core.extract import _heuristic_extract, extract_facts, parse_extraction_data
from core.pipeline import process_case
from core.prepolicy import evaluate_prepolicy_lock
from core.types import CaseInput, Decision, Domain, EscalationType


def test_informational_request():
    # Email chỉ hỏi thông tin -> is_informational=True, lock=None
    subject = "Hỏi lệ phí phúc khảo"
    body = "Thầy cô cho em hỏi lệ phí nộp đơn phúc khảo môn học là bao nhiêu tiền ạ?"
    ext = extract_facts(body, subject, case_id="c_test_01", language="vi")

    assert len(ext.requests) > 0
    req = ext.requests[0]
    assert req.domain == Domain.GRADE_APPEAL
    assert req.is_informational is True
    assert req.asks_appeal is False
    assert req.asks_exception is False

    lock = evaluate_prepolicy_lock(ext)
    assert lock is None


def test_asks_exception_triggers_lock():
    # Email xin ngoại lệ -> asks_exception=True, lock=AUTHORITY_REQUIRED
    subject = "Xin rút môn sau hạn"
    body = "Em bị ốm nên lỡ hạn, thầy cho em xin rút môn sau hạn được không ạ?"
    ext = extract_facts(body, subject, case_id="c_test_02", language="vi")

    assert len(ext.requests) > 0
    req = ext.requests[0]
    assert req.asks_exception is True

    lock = evaluate_prepolicy_lock(ext)
    assert lock == "AUTHORITY_REQUIRED"


def test_asks_appeal_triggers_lock():
    # Email yêu cầu phúc khảo cho bản thân -> asks_appeal=True, lock=AUTHORITY_REQUIRED
    subject = "Phúc khảo điểm thi"
    body = "Em muốn phúc khảo bài thi kết thúc học phần môn Toán cao cấp điểm không đúng."
    ext = extract_facts(body, subject, case_id="c_test_03", language="vi")

    assert len(ext.requests) > 0
    req = ext.requests[0]
    assert req.asks_appeal is True

    lock = evaluate_prepolicy_lock(ext)
    assert lock == "AUTHORITY_REQUIRED"


def test_pipeline_with_authority_required_yields_p01():
    inp = CaseInput(
        sender="sinhvien@edu.vn",
        subject="Xin rút môn sau hạn",
        body="Kính xin thầy cô xem xét cho em rút môn quá hạn với ạ, em xin ngoại lệ trường hợp này.",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )
    result = process_case(inp)

    # Khi có cờ xin ngoại lệ -> lock -> Policy Engine ra P01 AUTHORITY_REQUIRED
    assert result.decision.decision == Decision.ESCALATE
    assert result.decision.escalation_type == EscalationType.AUTHORITY_REQUIRED
    assert result.decision.rule_id == "P01"
    # Quan trọng: Căn cứ quy định vẫn được tra cứu (không nhảy tắt R4-R5)
    assert result.evidence is not None
    assert len(result.evidence.chunks) > 0


def test_parse_extraction_data_schema():
    raw_data = {
        "language": "vi",
        "requests": [
            {
                "domain": "conduct_score",
                "intent": "Hỏi điểm rèn luyện",
                "is_informational": True,
                "requires_personal_record": False,
                "asks_exception": False,
                "asks_appeal": False,
                "asks_authority_decision": False,
            }
        ],
        "critical_facts": {"cohort": "K48"},
        "missing_critical_facts": [],
        "injection_suspected": False,
    }
    ext = parse_extraction_data(raw_data, '{"raw": true}')
    assert ext.language == "vi"
    assert len(ext.requests) == 1
    assert ext.requests[0].domain == Domain.CONDUCT_SCORE
    assert ext.critical_facts["cohort"] == "K48"


def test_nlp_normalizes_unaccented_short_query() -> None:
    ext = _heuristic_extract("Han rut hoc phan?", "", "vi")

    request = ext.requests[0]
    assert request.domain == Domain.COURSE_WITHDRAWAL
    assert request.is_informational is True
    assert request.asks_exception is False
    assert request.intent == "Hỏi thời hạn rút học phần"


def test_nlp_distinguishes_appeal_information_from_personal_request() -> None:
    info = _heuristic_extract("Em muốn biết thủ tục phúc khảo và lệ phí.", "", "vi")
    personal = _heuristic_extract("Em đề nghị xem lại điểm bài thi Giải tích của em.", "", "vi")

    assert info.requests[0].is_informational is True
    assert info.requests[0].asks_appeal is False
    assert personal.requests[0].domain == Domain.GRADE_APPEAL
    assert personal.requests[0].asks_appeal is True
    assert personal.requests[0].intent == "Yêu cầu phúc khảo điểm cá nhân"


def test_nlp_recognizes_short_exception_and_approval_requests() -> None:
    exception = _heuristic_extract("Cho em xin rút học phần trễ vì nằm viện.", "", "vi")
    approval = _heuristic_extract("Nhờ duyệt cho em rút học phần.", "", "vi")

    assert exception.requests[0].asks_exception is True
    assert exception.requests[0].intent == "Xin ngoại lệ rút học phần"
    assert approval.requests[0].asks_authority_decision is True
    assert approval.requests[0].intent == "Yêu cầu phê duyệt rút học phần"


def test_nlp_preserves_review_topics_for_policy_and_retrieval() -> None:
    conduct_appeal = _heuristic_extract(
        "Em đề nghị xem xét lại điểm rèn luyện của bản thân em.", "", "vi"
    )
    refund = _heuristic_extract(
        "Cho em hỏi rút môn thì được hoàn bao nhiêu phần trăm học phí?", "", "vi"
    )
    terse_exception = _heuristic_extract("Rút môn sau hạn.", "", "vi")

    assert conduct_appeal.requests[0].asks_appeal is True
    assert "hoàn học phí" in refund.requests[0].intent
    assert terse_exception.requests[0].asks_exception is True


def test_nlp_keeps_multiple_known_domains() -> None:
    extraction = _heuristic_extract(
        "Cho em hỏi hạn rút học phần và lệ phí phúc khảo?",
        "Hai thủ tục",
        "vi",
    )

    assert [request.domain for request in extraction.requests] == [
        Domain.COURSE_WITHDRAWAL,
        Domain.GRADE_APPEAL,
    ]
    assert all(request.is_informational for request in extraction.requests)


def test_nlp_extracts_program_scope() -> None:
    extraction = _heuristic_extract(
        "Em là học viên cao học, cho em hỏi hạn rút học phần?",
        "Rút học phần",
        "vi",
    )

    assert extraction.critical_facts["applies_to"] == "graduate"
