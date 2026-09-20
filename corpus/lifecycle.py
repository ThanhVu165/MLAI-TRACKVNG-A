from __future__ import annotations

import difflib
import html
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

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
        fromdesc=html.escape(old_doc_id),
        todesc=html.escape(new_doc_id),
        context=True,
        numlines=2,
    )


def _audit(
    action: str,
    doc_id: str,
    actor: str,
    reason: str,
    audit: Callable[..., object] | None,
    case_id: str | None = None,
) -> None:
    if audit is None:
        try:
            from infra.audit import log_event

            audit = log_event
        except ImportError:
            return
    audit(
        case_id=case_id,
        actor=actor,
        action=action,
        input_ref=doc_id,
        reason=reason,
    )


def affected_cases(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    now: datetime | None = None,
    days: int = 30,
) -> list[str]:
    chunk_ids = {
        str(row[0])
        for row in conn.execute("SELECT chunk_id FROM chunks WHERE doc_id = ?", (doc_id,))
    }
    if not chunk_ids:
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    rows = conn.execute(
        """SELECT cases.case_id, cases.created_at, decisions.evidence_ids_json
           FROM cases JOIN decisions ON decisions.case_id = cases.case_id"""
    ).fetchall()
    affected: set[str] = set()
    for case_id, created_at, evidence_json in rows:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        evidence_ids = set(json.loads(evidence_json or "[]"))
        if created >= cutoff and evidence_ids & chunk_ids:
            affected.add(str(case_id))
    return sorted(affected)


def flag_cases_for_recheck(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: str,
    audit: Callable[..., object] | None = None,
    now: datetime | None = None,
) -> list[str]:
    case_ids = affected_cases(conn, doc_id, now=now)
    for case_id in case_ids:
        old_status = conn.execute(
            "SELECT status FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if old_status and old_status[0] != "NEEDS_RECHECK":
            conn.execute("UPDATE cases SET status='NEEDS_RECHECK' WHERE case_id = ?", (case_id,))
            _audit(
                "FLAG_NEEDS_RECHECK",
                doc_id,
                actor,
                f"Case đã dùng căn cứ từ tài liệu {doc_id} vừa rời ACTIVE",
                audit,
                case_id=case_id,
            )
    conn.commit()
    return case_ids


def _mark_superseded(
    conn: sqlite3.Connection,
    doc_id: str,
    replacement_id: str,
    superseded_at: str,
) -> None:
    conn.execute(
        "UPDATE sources SET status='SUPERSEDED', superseded_by=?, superseded_at=? "
        "WHERE doc_id=?",
        (replacement_id, superseded_at, doc_id),
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
        _mark_superseded(conn, old_doc_id, doc_id, activated_at)
    conn.commit()
    for old_doc_id in old_doc_ids:
        flag_cases_for_recheck(conn, old_doc_id, actor="SYSTEM", audit=audit)
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


def supersede_source(
    conn: sqlite3.Connection,
    doc_id: str,
    replacement_id: str,
    *,
    actor: str,
    reason: str,
    audit: Callable[..., object] | None = None,
    reindex: Callable[[], object] | None = None,
) -> str:
    if not actor.startswith("ADMIN:") or actor == "ADMIN:":
        raise ValueError("Supersede cần actor quản trị viên cụ thể")
    if not reason.strip():
        raise ValueError("Lý do là bắt buộc")
    target = conn.execute("SELECT status FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    replacement = conn.execute(
        "SELECT status FROM sources WHERE doc_id = ?", (replacement_id,)
    ).fetchone()
    if not target or target[0] != "ACTIVE":
        raise ValueError("Chỉ có thể hạ cấp tài liệu ACTIVE")
    if not replacement or replacement[0] != "ACTIVE":
        raise ValueError("Tài liệu thay thế phải đang ACTIVE")

    _mark_superseded(conn, doc_id, replacement_id, now_iso())
    conn.commit()
    flag_cases_for_recheck(conn, doc_id, actor="SYSTEM", audit=audit)
    version = bump_corpus_version(conn, actor, f"Hạ cấp {doc_id}: {reason.strip()}")
    _audit(
        "SUPERSEDE_SOURCE",
        doc_id,
        actor,
        f"Bị thay thế bởi {replacement_id}: {reason.strip()}",
        audit,
    )
    if reindex:
        reindex()
    return version


def rollback_source(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: str,
    reason: str,
    audit: Callable[..., object] | None = None,
    reindex: Callable[[], object] | None = None,
) -> str:
    if not actor.startswith("ADMIN:") or actor == "ADMIN:":
        raise ValueError("Rollback cần actor quản trị viên cụ thể")
    if not reason.strip():
        raise ValueError("Lý do là bắt buộc")
    row = conn.execute(
        "SELECT status, superseded_by FROM sources WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if not row or row[0] != "SUPERSEDED":
        raise ValueError("Chỉ rollback tài liệu SUPERSEDED")
    replacement_id = str(row[1] or "")
    if (
        not replacement_id
        or not conn.execute(
            "SELECT 1 FROM sources WHERE doc_id = ? AND status = 'ACTIVE'", (replacement_id,)
        ).fetchone()
    ):
        raise ValueError("Không tìm thấy tài liệu ACTIVE cần rollback")
    rolled_back_at = now_iso()
    conn.execute(
        "UPDATE sources SET status='ACTIVE', superseded_by=NULL, superseded_at=NULL, "
        "activated_at=?, activated_by=? WHERE doc_id=?",
        (rolled_back_at, actor, doc_id),
    )
    _mark_superseded(
        conn,
        replacement_id,
        doc_id,
        rolled_back_at,
    )
    conn.commit()
    flag_cases_for_recheck(conn, replacement_id, actor="SYSTEM", audit=audit)
    detect_conflicts(conn, audit=audit)
    version = bump_corpus_version(conn, actor, f"Rollback {doc_id}: {reason.strip()}")
    _audit(
        "ROLLBACK_SOURCE",
        doc_id,
        actor,
        f"Khôi phục {doc_id}, hạ cấp {replacement_id}: {reason.strip()}",
        audit,
    )
    if reindex:
        reindex()
    return version
