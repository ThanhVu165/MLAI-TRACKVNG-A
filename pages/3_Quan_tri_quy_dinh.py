from __future__ import annotations

import sqlite3

import streamlit as st

from corpus.coverage import LABELS, label_chunk, list_coverage
from corpus.lifecycle import document_diff, pending_reviews, submit_review
from corpus.metadata import SUPPORTED_DOMAINS, SourceMetadata


def _items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def render_metadata_form(draft: SourceMetadata) -> SourceMetadata | None:
    with st.form("metadata_form"):
        document_id = st.text_input("Mã văn bản", value=draft.document_id or "")
        title = st.text_input("Tiêu đề", value=draft.title or "")
        issuer = st.text_input("Đơn vị ban hành", value=draft.issuer or "")
        published_at = st.text_input("Ngày ban hành (YYYY-MM-DD)", value=draft.published_at or "")
        effective_from = st.text_input("Hiệu lực từ (YYYY-MM-DD)", value=draft.effective_from or "")
        effective_to = st.text_input(
            "Hiệu lực đến (YYYY-MM-DD, có thể trống)", value=draft.effective_to or ""
        )
        applies_to = st.text_input("Đối tượng áp dụng", value=", ".join(draft.applies_to))
        cohorts = st.text_input("Khóa áp dụng", value=", ".join(draft.cohorts))
        supersedes = st.text_input("Thay thế văn bản", value=", ".join(draft.supersedes))
        domains = st.multiselect("Nhóm nghiệp vụ", sorted(SUPPORTED_DOMAINS), default=draft.domains)
        transitional = st.selectbox(
            "Có điều khoản chuyển tiếp?",
            [None, False, True],
            index=[None, False, True].index(draft.transitional_clause),
            format_func=lambda value: {None: "Chưa xác nhận", False: "Không", True: "Có"}[value],
        )
        submitted = st.form_submit_button("Lưu metadata")
    if not submitted:
        return None
    return SourceMetadata(
        document_id=document_id.strip() or None,
        title=title.strip() or None,
        issuer=issuer.strip() or None,
        published_at=published_at.strip() or None,
        effective_from=effective_from.strip() or None,
        effective_to=effective_to.strip() or None,
        applies_to=_items(applies_to),
        cohorts=_items(cohorts),
        supersedes=_items(supersedes),
        transitional_clause=transitional,
        domains=domains,
        status="PENDING_REVIEW",
        content_hash=draft.content_hash,
    )


def render_coverage_editor(conn: sqlite3.Connection, doc_id: str, actor: str) -> None:
    st.subheader("Quyền trả lời theo từng điều khoản")
    st.caption("Mặc định là human_only. AI chỉ đề xuất; quản trị viên quyết định nhãn cuối cùng.")
    for chunk in list_coverage(conn, doc_id):
        with st.container(border=True):
            st.markdown(f"**{chunk['breadcrumb']}**")
            st.write(str(chunk["text"])[:300])
            label = st.selectbox(
                "Nhãn thẩm quyền",
                sorted(LABELS),
                index=sorted(LABELS).index(str(chunk["label"])),
                key=f"label_{chunk['chunk_id']}",
            )
            if st.button("Lưu nhãn", key=f"save_{chunk['chunk_id']}"):
                changed = label_chunk(conn, str(chunk["chunk_id"]), label, actor=actor)
                st.success("Đã lưu nhãn.") if changed else st.info("Nhãn không thay đổi.")


def render_review_queue(conn: sqlite3.Connection, actor: str) -> None:
    for document in pending_reviews(conn):
        doc_id = str(document["doc_id"])
        with st.expander(f"{document['title'] or doc_id} · {doc_id}"):
            st.json(document)
            st.dataframe(list_coverage(conn, doc_id), use_container_width=True)
            diff = document_diff(conn, doc_id)
            if diff:
                st.markdown(diff, unsafe_allow_html=True)
            reason = st.text_input("Lý do", key=f"review_reason_{doc_id}")
            approve, reject, change = st.columns(3)
            if approve.button("Duyệt", key=f"approve_{doc_id}"):
                submit_review(conn, doc_id, "APPROVE", actor=actor, reason=reason)
                st.success("Đã duyệt. Tài liệu sẵn sàng để kích hoạt.")
            if reject.button("Từ chối", key=f"reject_{doc_id}"):
                submit_review(conn, doc_id, "REJECT", actor=actor, reason=reason)
                st.warning("Đã từ chối tài liệu.")
            if change.button("Yêu cầu chỉnh sửa", key=f"change_{doc_id}"):
                submit_review(conn, doc_id, "REQUEST_CHANGES", actor=actor, reason=reason)
                st.info("Đã ghi nhận yêu cầu chỉnh sửa.")


st.title("Quản trị quy định")
draft = st.session_state.get("metadata_draft")
if isinstance(draft, SourceMetadata):
    edited = render_metadata_form(draft)
    if edited:
        st.session_state["metadata_draft"] = edited
        st.success("Đã cập nhật bản nháp metadata. Hãy kiểm tra trước khi duyệt.")
else:
    st.info("Nạp tài liệu để tạo và xác nhận metadata.")
