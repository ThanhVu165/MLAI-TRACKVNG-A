from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.controls import (
    is_automation_paused,
    override_decision,
    pause_automation,
    rerun_case,
    resume_automation,
)
from core.types import Decision, EscalationType, PipelineResult
from infra.audit import log_event
from pages._shared import (
    initialize_app,
    make_input,
    persist_result,
    render_result,
    run_and_remember,
)

st.set_page_config(
    page_title="Escalation Referee",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)
initialize_app()


def _banner() -> None:
    paused = is_automation_paused()
    message = (
        "TỰ ĐỘNG HÓA ĐANG TẠM DỪNG — mọi phản hồi sẽ chờ chuyên viên."
        if paused
        else "Chế độ mô phỏng — hệ thống không gửi email thật."
    )
    st.markdown(
        f'<div class="simulation-banner">{message}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        .simulation-banner {
          position: sticky; top: 0; z-index: 1000; padding: .7rem 1rem;
          border: 1px solid #0f766e; border-radius: .5rem;
          background: #f0fdfa; color: #134e4a; font-weight: 700;
          margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sidebar_controls() -> None:
    with st.sidebar:
        st.subheader("Điều khiển toàn cục")
        admin = st.text_input("Mã quản trị viên", value="demo").strip() or "demo"
        actor = f"ADMIN:{admin}"
        if is_automation_paused():
            st.warning("Đang tạm dừng")
            if st.button("Tiếp tục", use_container_width=True):
                resume_automation(actor=actor)
                log_event(
                    case_id=None,
                    actor=actor,
                    action="RESUME_AUTOMATION",
                    reason="Quản trị viên tiếp tục chế độ tự động.",
                )
                st.rerun()
        else:
            st.success("Tự động hóa đang hoạt động")
            reason = st.text_input(
                "Lý do tạm dừng", value="Kiểm tra thủ công trong buổi trình diễn."
            )
            if st.button("Tạm dừng tự động", use_container_width=True):
                if not reason.strip():
                    st.error("Hãy nhập lý do tạm dừng.")
                else:
                    pause_automation(actor=actor, reason=reason)
                    log_event(
                        case_id=None,
                        actor=actor,
                        action="PAUSE_AUTOMATION",
                        reason=reason,
                    )
                    st.rerun()

        cases: dict[str, PipelineResult] = st.session_state.get("case_results", {})
        if not cases:
            st.caption("Xử lý ít nhất một email để dùng Ghi đè và Chạy lại.")
            return
        case_id = st.selectbox("Case cần điều khiển", list(cases), key="control_case")
        result = cases[case_id]
        target = st.selectbox(
            "Quyết định mới",
            [Decision.AUTO_REPLY, Decision.ESCALATE],
            format_func=lambda value: {
                Decision.AUTO_REPLY: "Trả lời tự động",
                Decision.ESCALATE: "Chuyển tiếp",
            }[value],
        )
        override_reason = st.text_input("Lý do ghi đè")
        if st.button("Ghi đè quyết định", use_container_width=True):
            if not override_reason.strip():
                st.error("Hãy nhập lý do ghi đè.")
            elif target == result.decision.decision:
                st.error("Quyết định mới phải khác quyết định hiện tại.")
            else:
                updated = override_decision(
                    result,
                    target,
                    actor=actor,
                    reason=override_reason,
                    new_escalation_type=(
                        EscalationType.AUTHORITY_REQUIRED if target == Decision.ESCALATE else None
                    ),
                )
                st.session_state["case_results"][case_id] = updated
                st.session_state["current_result"] = updated
                inp = st.session_state["case_inputs"][case_id]
                persist_result(inp, updated)
                log_event(
                    case_id=case_id,
                    actor=actor,
                    action="OVERRIDE_DECISION",
                    reason=override_reason,
                    rule_id=updated.decision.rule_id,
                )
                st.success("Đã ghi đè quyết định và lưu audit.")

        if st.button("Chạy lại case", use_container_width=True):
            _, diff = rerun_case(result, actor=actor)
            st.session_state["rerun_diff"] = diff
            log_event(
                case_id=case_id,
                actor=actor,
                action="RERUN_CASE",
                reason="Quản trị viên chạy lại case trên corpus hiện tại.",
            )
        diff = st.session_state.get("rerun_diff")
        if diff:
            st.dataframe(
                [
                    {
                        "Quyết định cũ": diff["old_decision"],
                        "Quyết định mới": diff["new_decision"],
                        "Luật cũ": diff["old_rule_id"],
                        "Luật mới": diff["new_rule_id"],
                        "Citation thêm": ", ".join(diff["citations_added"]),
                        "Citation bỏ": ", ".join(diff["citations_removed"]),
                    }
                ],
                hide_index=True,
                use_container_width=True,
            )


def homepage() -> None:
    st.markdown("Dán email sinh viên vào ô bên dưới và bấm Xử lý.")
    _banner()
    body = st.text_area("Nội dung email", height=180, key="home_body")
    if st.button("Xử lý email", type="primary", key="home_process"):
        if not body.strip():
            st.error("Nội dung email đang trống. Hãy dán email rồi bấm Xử lý email.")
        else:
            with st.status("Đang xử lý R1–R13...", expanded=True) as status:
                st.write("R1–R6: làm sạch, tìm căn cứ và áp dụng quy định")
                result = run_and_remember(make_input(body, "paste"))
                st.write("R7–R13: soạn kết quả, kiểm tra và xếp lịch")
                status.update(label="Đã xử lý xong", state="complete")
            render_result(result, key_prefix="home")
    elif isinstance(st.session_state.get("current_result"), PipelineResult):
        render_result(st.session_state["current_result"], key_prefix="home")

    st.divider()
    st.subheader("Đầu vào → Xử lý → Đầu ra")
    flow = Path("docs/slide2_flow.svg")
    if flow.exists():
        st.image(flow, use_container_width=True)
        st.caption(
            "Hai điểm có biểu tượng người là nơi hệ thống bắt buộc chờ quyết định của con người."
        )


def _page(path: str, title: str, icon: str) -> st.Page:
    if Path(path).exists():
        return st.Page(path, title=title, icon=icon)

    def placeholder() -> None:
        st.title(title)
        st.info("Màn hình này đang được hoàn thiện trong task tiếp theo của làn C.")

    return st.Page(placeholder, title=title, icon=icon)


_sidebar_controls()
navigation = st.navigation(
    {
        "Bắt đầu": [st.Page(homepage, title="Trang chủ", icon="🏠", default=True)],
        "Sáu màn hình": [
            _page("pages/1_Xu_ly_email.py", "1 · Xử lý email", "✉️"),
            _page("pages/2_Hang_cho_duyet.py", "2 · Hàng chờ duyệt", "👤"),
            _page("pages/3_Quan_tri_quy_dinh.py", "3 · Quản trị quy định", "📚"),
            _page("pages/4_Nhat_ky_kiem_toan.py", "4 · Nhật ký kiểm toán", "🔎"),
            _page("pages/5_Verify.py", "5 · Verify", "✅"),
            _page("pages/6_Do_luong.py", "6 · Đo lường", "📊"),
        ],
    }
)
navigation.run()
