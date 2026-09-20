from __future__ import annotations

import streamlit as st

from infra.telemetry import snapshot
from pages._shared import initialize_app

initialize_app()
st.title("Đo lường")
st.warning("Dữ liệu hiện tại đến từ chạy nội bộ trên dữ liệu giả lập, chưa phải người dùng thật.")
metrics = snapshot()

st.subheader("Chỉ số hiệu quả")
st.metric("Tỷ lệ trả lời tự động", f"{float(metrics['auto_rate']):.1%}")
st.caption("AUTO_REPLY / (AUTO_REPLY + ESCALATE).")
st.write("**Tỷ lệ chuyển tiếp theo loại**")
st.json(metrics["escalation_rate_by_type"])
st.caption("Số case của từng loại / tổng case ESCALATE.")
st.write("**Độ trễ p50 theo bước (ms)**")
st.json(metrics["p50_latency_ms"])
st.caption("Trung vị thời gian của từng bước R1–R13 trên các lượt chạy thành công.")
st.write("**Độ trễ p95 theo bước (ms)**")
st.json(metrics["p95_latency_ms"])
st.caption("Phân vị 95 của thời gian từng bước R1–R13.")
st.metric("Trung vị thời gian duyệt", f"{float(metrics['median_review_seconds']):.1f} giây")
st.caption("Trung vị decided_at − shown_at của các quyết định con người.")
verify_one, verify_two = st.columns(2)
verify_one.metric("Bỏ sót escalation", f"{float(metrics['missed_escalation_rate']):.1%}")
verify_two.metric("Escalate thừa", f"{float(metrics['over_escalation_rate']):.1%}")
st.caption("Tính từ bảng expected/actual của lần Chạy toàn bộ 15 trường hợp gần nhất.")

st.subheader("Chỉ số rủi ro")
risk_one, risk_two, risk_three = st.columns(3)
risk_one.metric("Duyệt dưới 5 giây", f"{float(metrics['pct_approved_under_5s']):.1%}")
risk_two.metric("Tỷ lệ ghi đè", f"{float(metrics['override_rate']):.1%}")
risk_three.metric("Groundedness fail", f"{float(metrics['groundedness_fail_rate']):.1%}")
st.caption(
    "Duyệt <5s = số lượt review_seconds < 5 / tổng lượt duyệt · "
    "Ghi đè = OVERRIDE_DECISION / tổng quyết định · "
    "Groundedness fail = GROUNDEDNESS_FAILED / tổng ứng viên phản hồi tự động."
)
