from __future__ import annotations

from datetime import datetime

import streamlit as st

from core.resume import resume_after_human
from core.types import CaseStatus, DraftReply, PipelineResult
from infra.audit import log_event
from infra.db import get_connection, now_iso
from pages._shared import (
    initialize_app,
    new_id,
    render_escalation_card,
    render_explanation,
    update_case_status,
)

initialize_app()
st.title("Hàng chờ duyệt")
st.caption("Case chuyển tiếp chỉ được gửi sau thao tác rõ ràng của chuyên viên.")

cases: dict[str, PipelineResult] = st.session_state.get("case_results", {})
queued = [
    result
    for result in cases.values()
    if result.status in (CaseStatus.AWAITING_HUMAN, CaseStatus.PENDING_APPROVAL)
]
queued.sort(key=lambda result: result.started_at)

if not queued:
    st.info("Hàng chờ đang trống. Hãy xử lý một email cần chuyển tiếp ở trang Xử lý email.")
    st.stop()

case_id = st.selectbox(
    "Case đang chờ",
    [result.case_id for result in queued],
    format_func=lambda value: f"{value} · {cases[value].decision.reason}",
)
result = cases[case_id]
shown_key = f"shown_at_{case_id}"
if shown_key not in st.session_state:
    st.session_state[shown_key] = now_iso()

render_escalation_card(result)
render_explanation(case_id, f"queue_explain_{case_id}")

card_options = result.card.options if result.card and result.card.options else []
choices = card_options + [
    item for item in ["Chấp thuận", "Từ chối", "Quyết định khác"] if item not in card_options
]
with st.form(f"human_decision_{case_id}"):
    choice = st.selectbox("Quyết định của chuyên viên", choices)
    reason = st.text_area("Lý do quyết định (bắt buộc)")
    submitted = st.form_submit_button("Ghi quyết định và tạo bản xem trước", type="primary")

if submitted:
    if not reason.strip():
        st.error("Không thể ghi quyết định khi chưa có lý do.")
    else:
        try:
            draft = resume_after_human(case_id, choice, reason, actor="HUMAN:demo")
        except ValueError as exc:
            st.error(f"Không tạo được bản xem trước: {exc}")
        else:
            decided_at = now_iso()
            shown_at = str(st.session_state[shown_key])
            review_seconds = (
                datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
                - datetime.fromisoformat(shown_at.replace("Z", "+00:00"))
            ).total_seconds()
            with get_connection() as conn:
                conn.execute(
                    """INSERT INTO human_decisions(
                           id, case_id, actor, choice, reason, shown_at, decided_at, review_seconds
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_id("human"),
                        case_id,
                        "HUMAN:demo",
                        choice,
                        reason.strip(),
                        shown_at,
                        decided_at,
                        review_seconds,
                    ),
                )
                conn.commit()
            log_event(
                case_id=case_id,
                actor="HUMAN:demo",
                action="HUMAN_DECISION",
                reason=reason.strip(),
                rule_id=result.decision.rule_id,
                sources=result.decision.evidence_ids,
                corpus_version=result.corpus_version,
            )
            st.session_state[f"human_draft_{case_id}"] = draft
            update_case_status(case_id, CaseStatus.PENDING_APPROVAL)

draft = st.session_state.get(f"human_draft_{case_id}")
if isinstance(draft, DraftReply):
    st.divider()
    st.subheader("Xem trước trước khi gửi")
    if draft.guard_failures:
        st.warning("Bản nháp đã được rút gọn do phát hiện: " + ", ".join(draft.guard_failures))
    edited_body = st.text_area("Nội dung phản hồi", value=draft.body, height=220)
    approve, edit, return_queue = st.columns(3)
    if approve.button("Duyệt và gửi", type="primary", use_container_width=True):
        log_event(
            case_id=case_id,
            actor="HUMAN:demo",
            action="HUMAN_APPROVED_SEND",
            reason="Chuyên viên đã đọc và duyệt bản phản hồi.",
        )
        update_case_status(case_id, CaseStatus.RESOLVED)
        st.success("Đã gửi (mô phỏng) sau khi chuyên viên duyệt.")
    if edit.button("Sửa nội dung", use_container_width=True):
        st.session_state[f"human_draft_{case_id}"] = DraftReply(
            subject=draft.subject,
            body=edited_body,
            citations=draft.citations,
            grounded=draft.grounded,
            guard_failures=draft.guard_failures,
        )
        st.success("Đã lưu nội dung sửa để chuyên viên duyệt lại.")
    if return_queue.button("Trả lại hàng chờ", use_container_width=True):
        st.session_state.pop(f"human_draft_{case_id}", None)
        update_case_status(case_id, CaseStatus.AWAITING_HUMAN)
        st.info("Đã trả case về hàng chờ, chưa gửi email.")
