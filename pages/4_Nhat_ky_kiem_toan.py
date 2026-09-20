from __future__ import annotations

from datetime import date

import streamlit as st

from infra.audit import AuditEvent, recent_events
from infra.db import to_local
from pages._shared import initialize_app, render_explanation

initialize_app()
st.title("Nhật ký kiểm toán")
st.caption("Tra được ai làm gì, lúc nào, trên dữ liệu nào và vì sao.")

query_case = str(st.query_params.get("case_id", ""))
events = recent_events(500)
actors = sorted({event.actor for event in events})
actions = sorted({event.action for event in events})

filter_case = st.text_input("Case ID", value=query_case)
actor = st.selectbox("Actor", ["Tất cả", *actors])
action = st.selectbox("Hành động", ["Tất cả", *actions])
date_range = st.date_input("Khoảng ngày", value=[])


def _date_ok(event: AuditEvent) -> bool:
    if not isinstance(date_range, tuple) or len(date_range) != 2:
        return True
    event_date = date.fromisoformat(to_local(event.ts)[:10])
    return date_range[0] <= event_date <= date_range[1]


filtered = [
    event
    for event in events
    if (not filter_case or event.case_id == filter_case)
    and (actor == "Tất cả" or event.actor == actor)
    and (action == "Tất cả" or event.action == action)
    and _date_ok(event)
]

if not filtered:
    st.info("Chưa có sự kiện phù hợp. Hãy xử lý một email hoặc nới bộ lọc.")
else:
    st.dataframe(
        [
            {
                "Thời gian (+07:00)": to_local(event.ts),
                "Case": event.case_id or "—",
                "Actor": event.actor,
                "Hành động": event.action,
                "Luật": event.rule_id or "—",
            }
            for event in filtered
        ],
        hide_index=True,
        use_container_width=True,
    )
    for event in filtered:
        with st.expander(
            f"{to_local(event.ts)} · {event.action} · {event.case_id or 'toàn hệ thống'}"
        ):
            st.write(f"**Làm gì:** {event.action}")
            st.write(f"**Lúc nào:** {to_local(event.ts)}")
            st.write(f"**Ai:** {event.actor}")
            st.write(f"**Trên dữ liệu:** {event.input_ref or '—'}")
            st.write(f"**Đầu ra:** {event.output_ref or '—'}")
            st.write(f"**Vì sao:** {event.reason or 'Không yêu cầu lý do cho hành động này.'}")
            st.write(f"**Theo luật:** {event.rule_id or '—'}")
            st.write(f"**Nguồn:** {', '.join(event.sources) or '—'}")
            st.write(f"**Corpus:** {event.corpus_version or '—'}")

if filter_case:
    render_explanation(filter_case, f"audit_explain_{filter_case}")
