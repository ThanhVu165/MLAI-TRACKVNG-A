from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core.dispatch import (
    cancel_send,
    create_correction_email,
    dispatch_case,
    escalate_from_pending,
    get_dispatch_record,
    schedule_dispatch,
)
from core.resume import resume_after_decision
from core.types import (
    CaseInput,
    CaseStatus,
    ChunkLabel,
    Domain,
    DraftReply,
    EvidenceChunk,
    EvidenceResult,
    EvidenceStatus,
)


def _make_draft() -> DraftReply:
    return DraftReply(
        subject="Re: Thời hạn rút môn",
        body="Chào em,\n\nThời hạn rút môn là 8 tuần [chunk_cw_01].\n\nTrân trọng,\nDSA",
        citations=["chunk_cw_01"],
        grounded=True,
        guard_failures=[],
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


def test_schedule_dispatch_and_get_record() -> None:
    case_id = "c_test_disp_01"
    draft = _make_draft()

    record = schedule_dispatch(case_id, draft, trace_id="tr_01", countdown_seconds=60)
    assert record.status == CaseStatus.PENDING_SEND
    assert record.expires_at > record.scheduled_at

    fetched = get_dispatch_record(case_id)
    assert fetched is not None
    assert fetched.case_id == case_id


def test_cancel_send_success() -> None:
    case_id = "c_test_disp_02"
    draft = _make_draft()
    schedule_dispatch(case_id, draft, countdown_seconds=60)

    ok, msg = cancel_send(case_id, actor="ADMIN:ChuyenVienA")
    assert ok is True
    assert "hủy gửi thành công" in msg.lower()

    record = get_dispatch_record(case_id)
    assert record is not None
    assert record.status == CaseStatus.CANCELLED

    # Không thể hủy lần 2
    ok2, _ = cancel_send(case_id)
    assert ok2 is False


def test_escalate_from_pending() -> None:
    case_id = "c_test_disp_03"
    draft = _make_draft()
    schedule_dispatch(case_id, draft, countdown_seconds=60)

    ok, msg = escalate_from_pending(case_id, actor="ADMIN:ChuyenVienA", reason="Cần kiểm tra lại điểm số")
    assert ok is True
    assert "chuyên viên" in msg.lower()

    record = get_dispatch_record(case_id)
    assert record is not None
    assert record.status == CaseStatus.AWAITING_HUMAN


def test_dispatch_sent_and_correction_email() -> None:
    case_id = "c_test_disp_04"
    draft = _make_draft()
    schedule_dispatch(case_id, draft, countdown_seconds=60)

    # Chưa hết giờ và không force -> từ chối gửi
    ok, _ = dispatch_case(case_id, force=False)
    assert ok is False

    # Hết giờ hoặc force gửi -> thành công
    ok_force, _ = dispatch_case(case_id, force=True)
    assert ok_force is True
    record = get_dispatch_record(case_id)
    assert record is not None
    assert record.status == CaseStatus.SENT

    # Tạo email đính chính mới cho case đã SENT (Mục 8.8 spec)
    corr_id, corr_msg = create_correction_email(
        parent_case_id=case_id,
        correction_body="Xin đính chính: Hạn nộp đơn rút môn là trước ngày 15/10/2026 [chunk_cw_01].",
        actor="ADMIN:ChuyenVienA",
    )
    assert corr_id.startswith("c_corr_")
    assert "đính chính" in corr_msg.lower()
    corr_record = get_dispatch_record(corr_id)
    assert corr_record is not None
    assert corr_record.parent_case_id == case_id
    assert "[ĐÍNH CHÍNH]" in corr_record.draft.subject


def test_resume_after_decision_empty_reason_raises() -> None:
    ev = _make_evidence()
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi xin ngoại lệ",
        body="...",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )

    with pytest.raises(ValueError, match="bắt buộc, không được để trống"):
        resume_after_decision("c_res_01", choice="Đồng ý", reason="   ", evidence_res=ev, inp=inp)


def test_resume_after_decision_success() -> None:
    ev = _make_evidence()
    inp = CaseInput(
        sender="sv@school.edu.vn",
        subject="Hỏi xin rút môn sau hạn",
        body="...",
        received_at=datetime.now(timezone.utc),
        channel="paste",
    )

    draft, status = resume_after_decision(
        "c_res_02",
        choice="Đồng ý phê duyệt",
        reason="Sinh viên có hoàn cảnh đặc biệt kèm bệnh án đầy đủ hợp lệ theo quy định",
        evidence_res=ev,
        inp=inp,
        actor="CHUYEN_VIEN_1",
    )

    assert status == CaseStatus.PENDING_APPROVAL
    assert "Đồng ý phê duyệt" in draft.body
    assert "Sinh viên có hoàn cảnh đặc biệt" in draft.body
    assert "[chunk_cw_01]" in draft.body
