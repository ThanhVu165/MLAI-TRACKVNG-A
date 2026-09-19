from datetime import datetime, timezone

from core.extract import extract_facts, parse_extraction_data
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
