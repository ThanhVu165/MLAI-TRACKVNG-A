from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from core.types import PipelineResult
from pages._shared import initialize_app, make_input, render_result, run_and_remember

initialize_app()
st.title("Xử lý email")
st.caption("Chế độ mô phỏng — hệ thống không gửi email thật.")

mode = st.radio("Nguồn email", ["Dán văn bản", "Hộp thư mô phỏng"], horizontal=True)
subject = "Email sinh viên"
body = ""
channel = "paste"

if mode == "Dán văn bản":
    subject = st.text_input("Tiêu đề", value="Email sinh viên")
    body = st.text_area("Nội dung email", height=200)
else:
    channel = "inbox"
    inbox_path = Path(__file__).parents[1] / "data" / "seed_inbox.json"
    try:
        inbox = json.loads(inbox_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        inbox = []
    if not inbox:
        st.error(
            "Không tải được hộp thư mô phỏng. Hãy dùng ô Dán văn bản hoặc kiểm tra seed_inbox.json."
        )
    else:
        selected = st.selectbox(
            "Chọn email mẫu",
            inbox,
            format_func=lambda item: f"{item['id']} · {item['subject']}",
        )
        subject = str(selected["subject"])
        body = str(selected["body"])
        st.text_area("Nội dung email mẫu", value=body, height=180, disabled=True)

if st.button("Xử lý email", type="primary"):
    if not body.strip():
        st.error("Nội dung email đang trống. Hãy nhập hoặc chọn một email rồi thử lại.")
    else:
        with st.status("Đang xử lý R1–R13...", expanded=True) as status:
            st.write("R1–R3: làm sạch và nhận diện yêu cầu")
            st.write("R4–R8: tìm căn cứ, quyết định và kiểm tra")
            result = run_and_remember(make_input(body, channel, subject))
            st.write("R9–R13: cập nhật vòng đời và xếp lịch gửi")
            status.update(label="Đã xử lý xong", state="complete")
        render_result(result, key_prefix="process")
elif isinstance(st.session_state.get("current_result"), PipelineResult):
    render_result(st.session_state["current_result"], key_prefix="process")
else:
    st.info("Hãy dán một email hoặc chọn email mô phỏng, sau đó bấm Xử lý email.")
