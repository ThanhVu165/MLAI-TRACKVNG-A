from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from corpus.store import create_source, get_source_by_sha256, now_iso

MAX_SOURCE_BYTES = 20 * 1024 * 1024
AuditFn = Callable[..., object]


@dataclass(frozen=True)
class IntakeResult:
    doc_id: str
    duplicate: bool
    message: str
    payload: bytes
    filename: str


def _audit_source(actor: str, doc_id: str, reason: str, audit: AuditFn | None) -> None:
    if audit is None:
        try:
            from infra.audit import log_event

            audit = log_event
        except ImportError:
            return
    audit(
        case_id=None,
        actor=actor,
        action="SOURCE_UPLOADED",
        input_ref=doc_id,
        reason=reason,
    )


def _ingest(
    conn: Connection,
    payload: bytes,
    *,
    filename: str,
    title: str,
    source_kind: str,
    source_url: str | None,
    actor: str,
    fetched_at: str | None,
    audit: AuditFn | None,
) -> IntakeResult:
    if not payload:
        raise ValueError("Tài liệu không được để trống")
    if len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("Tài liệu vượt quá giới hạn 20 MB")

    digest = hashlib.sha256(payload).hexdigest()
    existing = get_source_by_sha256(conn, digest)
    if existing:
        return IntakeResult(
            doc_id=str(existing["doc_id"]),
            duplicate=True,
            message="Tài liệu không thay đổi",
            payload=payload,
            filename=filename,
        )

    doc_id = "DOC-" + digest[:12].upper()
    create_source(
        conn,
        {
            "doc_id": doc_id,
            "title": title.strip() or filename,
            "source_url": source_url,
            "source_kind": source_kind,
            "sha256": digest,
            "fetched_at": fetched_at,
            "status": "PENDING_REVIEW",
            "content_hash": digest,
        },
    )
    _audit_source(actor, doc_id, f"Nạp tài liệu từ {source_kind}", audit)
    return IntakeResult(doc_id, False, "Đã nạp tài liệu", payload, filename)


def ingest_upload(
    conn: Connection,
    filename: str,
    payload: bytes,
    *,
    actor: str,
    audit: AuditFn | None = None,
) -> IntakeResult:
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError("Chỉ chấp nhận tệp PDF hoặc DOCX")
    return _ingest(
        conn,
        payload,
        filename=Path(filename).name,
        title=Path(filename).stem,
        source_kind=suffix[1:],
        source_url=None,
        actor=actor,
        fetched_at=None,
        audit=audit,
    )


def ingest_text(
    conn: Connection,
    text: str,
    *,
    title: str,
    actor: str,
    audit: AuditFn | None = None,
) -> IntakeResult:
    return _ingest(
        conn,
        text.encode("utf-8"),
        filename=f"{title.strip() or 'van-ban'}.txt",
        title=title,
        source_kind="text",
        source_url=None,
        actor=actor,
        fetched_at=None,
        audit=audit,
    )


def _fetch_once(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "EscalationReferee/1.0"}), timeout=10) as res:
        return res.read(MAX_SOURCE_BYTES + 1)


def ingest_url(
    conn: Connection,
    url: str,
    *,
    actor: str,
    title: str = "",
    fetcher: Callable[[str], bytes] = _fetch_once,
    audit: AuditFn | None = None,
) -> IntakeResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL phải dùng http hoặc https")
    payload = fetcher(url)
    filename = Path(parsed.path).name or "tai-lieu-url"
    return _ingest(
        conn,
        payload,
        filename=filename,
        title=title or filename,
        source_kind="url",
        source_url=url,
        actor=actor,
        fetched_at=now_iso(),
        audit=audit,
    )
