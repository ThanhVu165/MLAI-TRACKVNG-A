from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from core.dispatch import (
    cancel_send,
    create_correction_email,
    dispatch_case,
    escalate_from_pending,
    get_dispatch_record,
)
from core.explain import explain_plainly
from core.pipeline import process_case
from core.types import CaseInput, CaseStatus, Decision, EscalationType, PipelineResult
from corpus.seed import seed_if_empty
from infra.audit import log_event
from infra.db import get_connection, now_iso, to_local

DECISION_LABELS = {
    Decision.AUTO_REPLY: "Trả lời tự động",
    Decision.ESCALATE: "Chuyển tiếp",
    Decision.INVALID_INPUT: "Đầu vào không hợp lệ",
}
ESCALATION_LABELS = {
    EscalationType.FACT_UNRESOLVED: "Thiếu dữ kiện",
    EscalationType.OUT_OF_POLICY: "Ngoài phạm vi quy định",
    EscalationType.AUTHORITY_REQUIRED: "Cần phê duyệt",
}


def initialize_app() -> None:
    """Create the database and seed the synthetic corpus once."""
    with get_connection() as conn:
        seed_if_empty(conn)


def make_input(body: str, channel: str, subject: str = "Email sinh viên") -> CaseInput:
    return CaseInput(
        sender="sinhvien.demo@university.edu.vn",
        subject=subject.strip() or "Email sinh viên",
        body=body.strip(),
        received_at=datetime.now(timezone.utc),
        channel=channel,  # type: ignore[arg-type]
    )


def run_and_remember(inp: CaseInput) -> PipelineResult:
    result = process_case(inp)
    st.session_state.setdefault("case_inputs", {})[result.case_id] = inp
    st.session_state.setdefault("case_results", {})[result.case_id] = result
    order = st.session_state.setdefault("case_order", [])
    if result.case_id not in order:
        order.insert(0, result.case_id)
    st.session_state["current_result"] = result
    persist_result(inp, result)
    return result


def persist_result(inp: CaseInput, result: PipelineResult) -> None:
    """Mirror the in-memory pipeline result for audit, queue and telemetry screens."""
    dispatch = get_dispatch_record(result.case_id)
    deadline = (
        datetime.fromtimestamp(dispatch.expires_at, timezone.utc).isoformat().replace("+00:00", "Z")
        if dispatch
        else None
    )
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO cases(
                   case_id, trace_id, channel, sender, subject, body_raw, received_at,
                   created_at, status, corpus_version, send_deadline
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(case_id) DO UPDATE SET
                   status=excluded.status, send_deadline=excluded.send_deadline""",
            (
                result.case_id,
                result.trace_id,
                inp.channel,
                inp.sender,
                inp.subject,
                inp.body,
                inp.received_at.isoformat(),
                result.started_at.isoformat(),
                result.status.value,
                result.corpus_version,
                deadline,
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO decisions(
                   decision_id, case_id, decision, escalation_type, rule_id, reason,
                   evidence_ids_json, evidence_status, corpus_version, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"dec_{result.case_id}",
                result.case_id,
                result.decision.decision.value,
                result.decision.escalation_type.value if result.decision.escalation_type else None,
                result.decision.rule_id,
                result.decision.reason,
                json.dumps(result.decision.evidence_ids, ensure_ascii=False),
                result.evidence.status.value if result.evidence else None,
                result.corpus_version,
                result.finished_at.isoformat(),
            ),
        )
        if result.draft:
            conn.execute(
                """INSERT OR REPLACE INTO drafts(
                       draft_id, case_id, kind, subject, body, citations_json,
                       grounded, guard_failures_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"draft_{result.case_id}",
                    result.case_id,
                    "auto" if result.decision.decision == Decision.AUTO_REPLY else "partial",
                    result.draft.subject,
                    result.draft.body,
                    json.dumps(result.draft.citations, ensure_ascii=False),
                    int(result.draft.grounded),
                    json.dumps(result.draft.guard_failures, ensure_ascii=False),
                    result.finished_at.isoformat(),
                ),
            )
        if result.card:
            conn.execute(
                """INSERT OR REPLACE INTO escalations(
                       case_id, escalation_type, summary, facts_json, basis_json,
                       question, options_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.case_id,
                    result.card.escalation_type.value,
                    result.card.summary,
                    json.dumps(result.card.facts, ensure_ascii=False),
                    json.dumps(result.card.basis, ensure_ascii=False),
                    result.card.question,
                    json.dumps(result.card.options, ensure_ascii=False),
                    result.finished_at.isoformat(),
                ),
            )
        conn.execute("DELETE FROM step_latencies WHERE case_id = ?", (result.case_id,))
        conn.executemany(
            "INSERT INTO step_latencies(case_id, step, ms, ok, ts) VALUES (?, ?, ?, 1, ?)",
            [
                (result.case_id, step, milliseconds, now_iso())
                for step, milliseconds in result.step_latencies_ms.items()
            ],
        )
        conn.commit()
    log_event(
        case_id=result.case_id,
        actor="SYSTEM",
        action="POLICY_DECIDED",
        rule_id=result.decision.rule_id,
        reason=result.decision.reason,
        sources=result.decision.evidence_ids,
        corpus_version=result.corpus_version,
    )


def update_case_status(case_id: str, status: CaseStatus) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE cases SET status = ? WHERE case_id = ?", (status.value, case_id))
        conn.commit()
    stored = st.session_state.get("case_results", {}).get(case_id)
    if isinstance(stored, PipelineResult):
        updated = replace(stored, status=status)
        st.session_state["case_results"][case_id] = updated
        if st.session_state.get("current_result", stored).case_id == case_id:
            st.session_state["current_result"] = updated


def render_escalation_card(result: PipelineResult) -> None:
    card = result.card
    if card is None:
        st.info("Case đã được chuyển tiếp nhưng chưa tạo được thẻ. Hãy xem lý do quyết định.")
        return
    st.subheader(ESCALATION_LABELS[card.escalation_type])
    with st.container(border=True):
        st.markdown("**1. Tóm tắt**")
        st.write(card.summary)
        st.markdown("**2. Dữ kiện**")
        for fact in card.facts:
            st.write(f"- {fact}")
        st.markdown("**3. Căn cứ**")
        if card.basis:
            for breadcrumb, text in card.basis:
                with st.expander(breadcrumb):
                    st.write(text)
        else:
            st.caption("Chưa có điều khoản phù hợp trong phạm vi quy định hiện tại.")
        st.markdown("**4. Câu hỏi cần quyết định**")
        st.info(card.question)
        if card.options:
            st.radio("Phương án", card.options, key=f"card_option_{result.case_id}")
    if card.partial_draft:
        with st.expander("Phần A đã soạn sẵn"):
            st.write(card.partial_draft.body)


def render_explanation(case_id: str, key: str) -> None:
    if st.button("Giải thích cho người không chuyên", key=key):
        explanation = explain_plainly(case_id)
        st.session_state[f"explanation_{case_id}"] = explanation
        log_event(
            case_id=case_id,
            actor="HUMAN:demo",
            action="EXPLAIN_REQUESTED",
            reason="Người dùng yêu cầu lời giải thích dễ hiểu.",
        )
    explanation = st.session_state.get(f"explanation_{case_id}")
    if explanation:
        st.success(str(explanation))


def _deadline(case_id: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT send_deadline FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def render_dispatch(result: PipelineResult) -> None:
    record = get_dispatch_record(result.case_id)
    if record is None:
        return
    deadline = _deadline(result.case_id)
    remaining = max(0, int(record.expires_at - time.time()))
    if deadline:
        st.metric("Thời gian còn lại để dừng", f"{remaining} giây")
        st.caption(f"Mốc hết hạn lưu trong DB: {to_local(deadline)}")
    if remaining == 0 and record.status == CaseStatus.PENDING_SEND:
        sent, _ = dispatch_case(result.case_id)
        if sent:
            update_case_status(result.case_id, CaseStatus.SENT)
    if record.status == CaseStatus.PENDING_SEND:
        reason = st.text_input(
            "Lý do can thiệp",
            value="Chuyên viên cần kiểm tra lại nội dung trước khi gửi.",
            key=f"dispatch_reason_{result.case_id}",
        )
        cancel_col, escalate_col = st.columns(2)
        if cancel_col.button("Hủy gửi", key=f"cancel_{result.case_id}"):
            ok, message = cancel_send(result.case_id, actor="HUMAN:demo", reason=reason)
            if ok:
                update_case_status(result.case_id, CaseStatus.CANCELLED)
                st.success(message)
            else:
                st.error(message)
        if escalate_col.button("Chuyển cho người", key=f"escalate_{result.case_id}"):
            ok, message = escalate_from_pending(result.case_id, actor="HUMAN:demo", reason=reason)
            if ok:
                update_case_status(result.case_id, CaseStatus.AWAITING_HUMAN)
                log_event(
                    case_id=result.case_id,
                    actor="HUMAN:demo",
                    action="CASE_QUEUED",
                    reason=reason,
                )
                st.success(message)
            else:
                st.error(message)
    elif record.status == CaseStatus.SENT:
        st.success("Đã gửi (mô phỏng). Email gốc được giữ nguyên.")
        correction = st.text_area("Nội dung email đính chính", key=f"correction_{result.case_id}")
        if st.button("Tạo email đính chính", key=f"create_correction_{result.case_id}"):
            if not correction.strip():
                st.error("Hãy nhập nội dung đính chính trước khi tạo.")
            else:
                _, message = create_correction_email(result.case_id, correction, actor="HUMAN:demo")
                st.success(message)
    elif record.status == CaseStatus.CANCELLED:
        st.warning("Đã hủy gửi.")
    elif record.status == CaseStatus.AWAITING_HUMAN:
        st.info("Đã chuyển case sang hàng chờ chuyên viên.")


def render_result(result: PipelineResult, *, key_prefix: str) -> None:
    elapsed = int((result.finished_at - result.started_at).total_seconds() * 1000)
    st.subheader(DECISION_LABELS[result.decision.decision])
    st.caption(
        f"Case {result.case_id} · {result.decision.rule_id} · {elapsed} ms · "
        f"Corpus {result.corpus_version}"
    )
    st.write(result.decision.reason)
    if result.decision.decision == Decision.AUTO_REPLY and result.draft:
        st.markdown(f"**{result.draft.subject}**")
        st.write(result.draft.body)
        st.markdown("**Căn cứ**")
        chunks = (
            {chunk.chunk_id: chunk for chunk in result.evidence.chunks} if result.evidence else {}
        )
        for citation in result.draft.citations:
            chunk = chunks.get(citation)
            with st.expander(chunk.breadcrumb if chunk else citation):
                st.write(chunk.text if chunk else "Không tải được nguyên văn điều khoản.")
        render_dispatch(result)
    elif result.decision.decision == Decision.ESCALATE:
        render_escalation_card(result)
    else:
        st.warning("Hãy kiểm tra lại nội dung email rồi thử lại.")
    render_explanation(result.case_id, f"{key_prefix}_explain_{result.case_id}")
    if Path("pages/4_Nhat_ky_kiem_toan.py").exists():
        st.page_link(
            "pages/4_Nhat_ky_kiem_toan.py",
            label="Xem nhật ký kiểm toán",
            query_params={"case_id": result.case_id},
        )


def result_to_json(result: PipelineResult) -> dict[str, Any]:
    return asdict(result)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
