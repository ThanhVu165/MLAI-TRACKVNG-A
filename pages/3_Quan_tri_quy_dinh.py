from __future__ import annotations

import streamlit as st

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


st.title("Quản trị quy định")
draft = st.session_state.get("metadata_draft")
if isinstance(draft, SourceMetadata):
    edited = render_metadata_form(draft)
    if edited:
        st.session_state["metadata_draft"] = edited
        st.success("Đã cập nhật bản nháp metadata. Hãy kiểm tra trước khi duyệt.")
else:
    st.info("Nạp tài liệu để tạo và xác nhận metadata.")
