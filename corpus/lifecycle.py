from __future__ import annotations

import difflib
import json
import sqlite3
from collections.abc import Callable

from corpus.conflict import detect_conflicts, scheduled_supersedes
from corpus.store import bump_corpus_version, now_iso

REVIEW_DECISIONS = frozenset({"APPROVE", "REJECT", "REQUEST_CHANGES"})


def pending_reviews(conn: sqlite3.Connection) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM sources WHERE status = 'PENDING_REVIEW' ORDER BY created_at, doc_id"
    ).fetchall()
    return [dict(row) for row in rows]


def _document_lines(conn: sqlite3.Connection, doc_id: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT text FROM chunks WHERE doc_id = ? ORDER BY ord", (doc_id,)
        ).fetchall()
    ]


def document_diff(conn: sqlite3.Connection, new_doc_id: str) -> str:
    row = conn.execute(
        "SELECT supersedes_json FROM sources WHERE doc_id = ?", (new_doc_id,)
    ).fetchone()
    supersedes = json.loads(row[0] or "[]") if row else []
    if not supersedes:
        return ""
    old_doc_id = str(supersedes[0])
    return difflib.HtmlDiff(wrapcolumn=100).make_table(
        _document_lines(conn, old_doc_id),
        _document_lines(conn, new_doc_id),
        fromdesc=old_doc_id,
        todesc=new_doc_id,
        context=True,
        numlines=2,
    )


def _audit(
    action: str,
    doc_id: str,
    actor: str,
    reason: str,
    audit: Callable[..., object] | None,
) -> None:
    if audit is None:
        try:
            from infra.audit import log_event

            audit = log_event
        except ImportError:
            return
    audit(
        case_id=None,
        actor=actor,
        action=action,
        input_ref=doc_id,
        reason=reason,
    )


def submit_review(
    conn: sqlite3.Connection,
    doc_id: str,
    decision: str,
    *,
    actor: str,
    reason: str,
    audit: Callable[..., object] | None = None,
) -> None:
    if decision not in REVIEW_DECISIONS:
        raise ValueError("Quyết định duyệt không hợp lệ")
    if not reason.strip():
        raise ValueError("Lý do là bắt buộc")
    if not conn.execute(
        "SELECT 1 FROM sources WHERE doc_id = ? AND status = 'PENDING_REVIEW'", (doc_id,)
    ).fetchone():
        raise ValueError("Tài liệu không ở trạng thái chờ duyệt")

    if decision == "REJECT":
        conn.execute("UPDATE sources SET status = 'REJECTED' WHERE doc_id = ?", (doc_id,))
    conn.execute(
        "INSERT INTO settings (key, value, updated_at, actor) VALUES (?, ?, datetime('now'), ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at, actor=excluded.actor",
        (f"review:{doc_id}", decision, actor),
    )
    conn.commit()
    action = "REJECT_SOURCE" if decision == "REJECT" else "SOURCE_METADATA_EDITED"
    _audit(action, doc_id, actor, f"{decision}: {reason.strip()}", audit)


def activate_source(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: str,
    reason: str,
    audit: Callable[..., object] | None = None,
    reindex: Callable[[], object] | None = None,
) -> str:
    if not actor.startswith("ADMIN:") or actor == "ADMIN:":
        raise ValueError("Kích hoạt tài liệu cần actor quản trị viên cụ thể")
    if not reason.strip():
        raise ValueError("Lý do là bắt buộc")
    source = conn.execute("SELECT status FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    review = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (f"review:{doc_id}",)
    ).fetchone()
    if not source or source[0] != "PENDING_REVIEW" or not review or review[0] != "APPROVE":
        raise ValueError("Tài liệu phải được duyệt trước khi kích hoạt")
    if not conn.execute("SELECT 1 FROM chunks WHERE doc_id = ?", (doc_id,)).fetchone():
        raise ValueError("Tài liệu chưa có chunk")

    activated_at = now_iso()
    old_doc_ids = scheduled_supersedes(conn, doc_id)
    conn.execute(
        "UPDATE sources SET status='ACTIVE', activated_at=?, activated_by=? WHERE doc_id=?",
        (activated_at, actor, doc_id),
    )
    for old_doc_id in old_doc_ids:
        conn.execute(
            "UPDATE sources SET status='SUPERSEDED', superseded_by=?, superseded_at=? "
            "WHERE doc_id=?",
            (doc_id, activated_at, old_doc_id),
        )
    conn.commit()
    detect_conflicts(conn, audit=audit)
    version = bump_corpus_version(conn, actor, f"Kích hoạt {doc_id}: {reason.strip()}")
    _audit("ACTIVATE_SOURCE", doc_id, actor, reason.strip(), audit)
    for old_doc_id in old_doc_ids:
        _audit(
            "SUPERSEDE_SOURCE",
            old_doc_id,
            actor,
            f"Bị thay thế bởi {doc_id}",
            audit,
        )
    if reindex:
        reindex()
    return version
