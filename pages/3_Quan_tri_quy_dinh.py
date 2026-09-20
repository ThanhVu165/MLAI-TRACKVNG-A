from __future__ import annotations

import sqlite3
from collections.abc import Callable

import streamlit as st

from corpus.api import clear_index_cache
from corpus.chunker import chunk_document
from corpus.coverage import LABELS, label_chunk, list_coverage
from corpus.extract_doc import extract_document
from corpus.intake import (
    IntakeResult,
    SourceCheck,
    ingest_rechecked,
    ingest_text,
    ingest_upload,
    ingest_url,
    recheck_urls,
)
from corpus.lifecycle import (
    activate_source,
    affected_cases,
    document_diff,
    pending_reviews,
    rollback_source,
    submit_review,
)
from corpus.metadata import (
    SUPPORTED_DOMAINS,
    SourceMetadata,
    save_metadata,
    suggest_metadata,
)
from corpus.seed import seed_if_empty
from corpus.store import current_corpus_version, list_sources, replace_chunks


def _items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _connection() -> sqlite3.Connection | None:
    existing = st.session_state.get("db_connection")
    if isinstance(existing, sqlite3.Connection):
        return existing
    try:
        from infra.db import get_connection

        return get_connection()
    except (ImportError, AttributeError):
        return None


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
    st.caption("Mặc định human_only. AI chỉ đề xuất; quản trị viên quyết định nhãn cuối cùng.")
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


def _stage(result: IntakeResult) -> None:
    text = extract_document(result.payload, result.filename)
    st.session_state["pending_ingest"] = {
        "doc_id": result.doc_id,
        "text": text,
        "draft": suggest_metadata(text, case_id=result.doc_id),
    }


def render_intake(conn: sqlite3.Connection, actor: str) -> None:
    uploaded = st.file_uploader("Tải PDF hoặc DOCX", type=["pdf", "docx"])
    if uploaded and st.button("Nạp tệp"):
        result = ingest_upload(conn, uploaded.name, uploaded.getvalue(), actor=actor)
        st.info(result.message)
        if not result.duplicate:
            _stage(result)

    url = st.text_input("URL tài liệu")
    if st.button("Nạp từ URL"):
        result = ingest_url(conn, url, actor=actor)
        st.info(result.message)
        if not result.duplicate:
            _stage(result)

    title = st.text_input("Tiêu đề văn bản dán")
    pasted = st.text_area("Nội dung văn bản")
    if st.button("Nạp văn bản"):
        result = ingest_text(conn, pasted, title=title, actor=actor)
        st.info(result.message)
        if not result.duplicate:
            _stage(result)

    pending = st.session_state.get("pending_ingest")
    if isinstance(pending, dict) and isinstance(pending.get("draft"), SourceMetadata):
        edited = render_metadata_form(pending["draft"])
        if edited:
            old_doc_id = str(pending["doc_id"])
            save_metadata(conn, old_doc_id, edited, actor=actor)
            doc_id = str(edited.document_id)
            chunks = chunk_document(
                str(pending["text"]),
                doc_id=doc_id,
                doc_title=edited.title or doc_id,
                domain=edited.domains[0],
            )
            replace_chunks(conn, doc_id, [chunk.to_record() for chunk in chunks])
            pending.update({"doc_id": doc_id, "draft": edited})
            st.success("Đã lưu metadata và tạo chunk human_only.")
        render_coverage_editor(conn, str(pending["doc_id"]), actor)

    render_source_recheck(conn, actor)


def render_source_recheck(conn: sqlite3.Connection, actor: str) -> None:
    if st.button("Kiểm tra nguồn mới"):
        st.session_state["source_checks"] = recheck_urls(conn, actor=actor)
    for check in st.session_state.get("source_checks", []):
        if not isinstance(check, SourceCheck):
            continue
        st.write(f"{check.title or check.url}: **{check.message}**")
        if check.changed and st.button("Nạp bản mới", key=f"ingest_{check.doc_id}"):
            result = ingest_rechecked(conn, check, actor=actor)
            st.success(f"Đã tạo bản chờ duyệt {result.doc_id}.")
            _stage(result)


def render_review_queue(
    conn: sqlite3.Connection,
    actor: str,
    reindex: Callable[[], object] | None = None,
) -> None:
    documents = pending_reviews(conn)
    if not documents:
        st.info("Chưa có tài liệu chờ duyệt. Hãy nạp tài liệu ở tab Nạp tài liệu.")
        return
    for document in documents:
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
            review = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (f"review:{doc_id}",)
            ).fetchone()
            if (
                review
                and review[0] == "APPROVE"
                and st.button("Kích hoạt tài liệu", key=f"activate_{doc_id}")
            ):
                version = activate_source(conn, doc_id, actor=actor, reason=reason, reindex=reindex)
                st.success(f"Đã kích hoạt tài liệu. Corpus hiện tại: {version}")


def render_active(conn: sqlite3.Connection) -> None:
    version = current_corpus_version(conn)
    st.metric("Corpus version", version)
    counts = conn.execute(
        """SELECT chunks.domain, chunks.label, COUNT(*)
           FROM chunks JOIN sources USING(doc_id)
           WHERE sources.status='ACTIVE' GROUP BY chunks.domain, chunks.label"""
    ).fetchall()
    st.dataframe(counts, use_container_width=True)
    st.dataframe(list_sources(conn, "ACTIVE"), use_container_width=True)


def render_history(
    conn: sqlite3.Connection,
    actor: str,
    reindex: Callable[[], object] | None = None,
) -> None:
    conn.row_factory = sqlite3.Row
    sources = conn.execute(
        "SELECT * FROM sources WHERE status IN ('SUPERSEDED', 'REJECTED') ORDER BY created_at DESC"
    ).fetchall()
    if not sources:
        st.info("Chưa có tài liệu trong lịch sử.")
        return
    for source in sources:
        doc_id = str(source["doc_id"])
        with st.expander(f"{source['title'] or doc_id} · {source['status']}"):
            st.write(f"Case cần kiểm tra lại trong 30 ngày: {len(affected_cases(conn, doc_id))}")
            if source["status"] == "SUPERSEDED":
                reason = st.text_input("Lý do rollback", key=f"rollback_reason_{doc_id}")
                if st.button("Rollback tài liệu", key=f"rollback_{doc_id}"):
                    version = rollback_source(
                        conn, doc_id, actor=actor, reason=reason, reindex=reindex
                    )
                    st.success(f"Đã rollback. Corpus hiện tại: {version}")


def main() -> None:
    st.title("Quản trị quy định")
    conn = _connection()
    if conn is None:
        st.error("Chưa có kết nối cơ sở dữ liệu từ infra.db.")
        return
    seed_if_empty(conn)
    admin_id = st.text_input("Mã quản trị viên", value="demo").strip()
    if not admin_id:
        st.error("Hãy nhập mã quản trị viên trước khi thực hiện thao tác.")
        return
    actor = f"ADMIN:{admin_id}"

    intake_tab, review_tab, active_tab, history_tab = st.tabs(
        ["Nạp tài liệu", "Chờ duyệt", "Đang hiệu lực", "Lịch sử"]
    )
    with intake_tab:
        render_intake(conn, actor)
    with review_tab:
        render_review_queue(conn, actor, reindex=clear_index_cache)
    with active_tab:
        render_active(conn)
    with history_tab:
        render_history(conn, actor, reindex=clear_index_cache)


main()
