from __future__ import annotations

import json
from dataclasses import asdict

import streamlit as st

from pages._shared import initialize_app
from verify.harness import SETS, VerifyResult, confusion_matrix, error_rates, run_set

initialize_app()
st.title("Verify")
st.caption(
    "Ba nút chạy độc lập, tuần tự và dùng đúng core.pipeline.process_case như giao diện thật."
)


def _run(name: str) -> None:
    with st.status("Đang chạy tuần tự, vui lòng chờ...", expanded=True) as status:
        results = run_set(name)
        st.session_state["verify_results"] = results
        st.session_state["verify_set"] = name
        status.update(
            label=f"Đã xong: {sum(result.passed for result in results)}/{len(results)} PASS",
            state="complete",
        )


verify_col, escalation_col, all_col = st.columns(3)
if verify_col.button("Chạy Verify 4 trường hợp", type="primary", use_container_width=True):
    _run("verify4")
if escalation_col.button(
    "Chạy kiểm tra chuyển tiếp 5 trường hợp",
    use_container_width=True,
    disabled=not SETS["escalation5"].exists(),
):
    _run("escalation5")
if all_col.button(
    "Chạy toàn bộ 15 trường hợp",
    use_container_width=True,
    disabled=not SETS["full15"].exists(),
):
    _run("full15")

results = st.session_state.get("verify_results", [])
if not results:
    st.info("Chưa có kết quả. Chọn đúng bộ cần chấm rồi bấm một trong ba nút phía trên.")
    st.stop()

typed_results: list[VerifyResult] = results
st.dataframe(
    [
        {
            "ID": result.test_id,
            "Tóm tắt input": result.input_summary,
            "Expected": result.expected,
            "Actual": result.actual,
            "rule_id": result.rule_id,
            "Lý do": result.reason,
            "PASS/FAIL": "PASS" if result.passed else "FAIL",
            "Thời gian (ms)": result.elapsed_ms,
            "Timestamp (+07:00)": result.timestamp,
            "Corpus version": result.corpus_version,
            "Câu hỏi chuyển tiếp": result.question,
            "Audit": result.audit_url,
        }
        for result in typed_results
    ],
    hide_index=True,
    use_container_width=True,
)

st.download_button(
    "Xuất JSON",
    json.dumps([asdict(result) for result in typed_results], ensure_ascii=False, indent=2),
    file_name=f"verify_{st.session_state.get('verify_set', 'results')}.json",
    mime="application/json",
)

if st.session_state.get("verify_set") == "full15":
    st.subheader("Ma trận nhầm lẫn 4 lớp")
    matrix = confusion_matrix(typed_results)
    st.dataframe(
        [dict(Lớp_kỳ_vọng=expected, **counts) for expected, counts in matrix.items()],
        hide_index=True,
        use_container_width=True,
    )
    missed, excessive = error_rates(typed_results)
    first, second = st.columns(2)
    first.metric("Tỷ lệ bỏ sót escalation", f"{missed:.1%}")
    second.metric("Tỷ lệ escalate thừa", f"{excessive:.1%}")
    st.caption(
        "Case INVALID_INPUT được hiển thị trong bảng kết quả nhưng không thuộc ma trận 4 lớp."
    )
