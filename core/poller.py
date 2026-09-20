from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB limit
DEFAULT_TIMEOUT_SECS = 10

logger = logging.getLogger(__name__)


def now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format ending with Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class HeadInfo:
    """HTTP HEAD response metadata for lightweight change detection."""

    url: str
    etag: str | None
    last_modified: str | None
    content_length: int | None
    accessible: bool = True
    error: str | None = None


@dataclass(frozen=True)
class PollCheckResult:
    """Result of polling a regulation URL for changes."""

    doc_id: str
    url: str
    title: str
    changed: bool
    status_message: str  # "Không đổi" | "Đã đổi" | "Lỗi kết nối"
    skipped_download: bool
    new_sha256: str | None
    payload: bytes | None
    etag: str | None = None
    last_modified: str | None = None


def check_url_head(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECS,
    opener: Callable[[Request], Any] | None = None,
) -> HeadInfo:
    """Send a lightweight HTTP HEAD request to check ETag / Last-Modified / Content-Length.

    Does not download the response body, saving 95%+ bandwidth.
    """
    req = Request(
        url,
        headers={"User-Agent": "EscalationReferee-SmartPoller/1.0"},
        method="HEAD",
    )
    try:
        call = opener if opener is not None else urlopen
        with call(req, timeout=timeout) as res:  # type: ignore[misc]
            etag = res.headers.get("ETag")
            last_mod = res.headers.get("Last-Modified")
            cl_header = res.headers.get("Content-Length")
            content_length = (
                int(cl_header) if cl_header and cl_header.isdigit() else None
            )
            return HeadInfo(
                url=url,
                etag=etag.strip('"') if etag else None,
                last_modified=last_mod,
                content_length=content_length,
                accessible=True,
            )
    except (URLError, TimeoutError, Exception) as exc:  # noqa: BLE001
        logger.warning("HEAD request thất bại cho %s: %s", url, exc)
        return HeadInfo(
            url=url,
            etag=None,
            last_modified=None,
            content_length=None,
            accessible=False,
            error=str(exc),
        )


def fetch_url_payload(
    url: str,
    *,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: int = DEFAULT_TIMEOUT_SECS,
    fetcher: Callable[[str], bytes] | None = None,
) -> bytes:
    """Download url content safely with timeout and byte limit."""
    if fetcher is not None:
        return fetcher(url)

    req = Request(url, headers={"User-Agent": "EscalationReferee-SmartPoller/1.0"})
    with urlopen(req, timeout=timeout) as res:
        data = res.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(
                f"Tài liệu vượt quá giới hạn {max_bytes // (1024 * 1024)} MB"
            )
        return data


def check_source_update(
    *,
    doc_id: str,
    url: str,
    title: str,
    stored_sha256: str,
    stored_etag: str | None = None,
    stored_last_modified: str | None = None,
    stored_content_length: int | None = None,
    head_checker: Callable[[str], HeadInfo] = check_url_head,
    body_fetcher: Callable[[str], bytes] | None = None,
) -> PollCheckResult:
    """Check if a registered regulation has changed using Smart Polling (Method 1).

    Rung 1: Check HTTP HEAD headers. If ETag/Last-Modified match stored values exactly,
    confirm UNCHANGED without downloading heavy file.
    Rung 2: If HEAD indicates possible change or lacks caching headers, download payload,
    hash with SHA-256, and compare with stored_sha256.
    """
    head = head_checker(url)
    if not head.accessible:
        return PollCheckResult(
            doc_id=doc_id,
            url=url,
            title=title,
            changed=False,
            status_message=f"Lỗi kết nối: {head.error or 'Không truy cập được'}",
            skipped_download=True,
            new_sha256=None,
            payload=None,
        )

    # Fast-path check via ETag / Last-Modified / Content-Length
    if stored_etag and head.etag and stored_etag == head.etag:
        return PollCheckResult(
            doc_id=doc_id,
            url=url,
            title=title,
            changed=False,
            status_message="Không đổi",
            skipped_download=True,
            new_sha256=stored_sha256,
            payload=None,
            etag=head.etag,
            last_modified=head.last_modified,
        )

    if (
        stored_last_modified
        and head.last_modified
        and stored_last_modified == head.last_modified
        and (
            stored_content_length is None
            or head.content_length is None
            or stored_content_length == head.content_length
        )
    ):
        return PollCheckResult(
            doc_id=doc_id,
            url=url,
            title=title,
            changed=False,
            status_message="Không đổi",
            skipped_download=True,
            new_sha256=stored_sha256,
            payload=None,
            etag=head.etag,
            last_modified=head.last_modified,
        )

    # Slow-path: Download payload and compute SHA-256
    try:
        payload = fetch_url_payload(url, fetcher=body_fetcher)
        new_digest = hashlib.sha256(payload).hexdigest()
    except Exception as exc:  # noqa: BLE001
        return PollCheckResult(
            doc_id=doc_id,
            url=url,
            title=title,
            changed=False,
            status_message=f"Lỗi tải file: {exc}",
            skipped_download=False,
            new_sha256=None,
            payload=None,
        )

    changed = new_digest != stored_sha256
    return PollCheckResult(
        doc_id=doc_id,
        url=url,
        title=title,
        changed=changed,
        status_message="Đã đổi" if changed else "Không đổi",
        skipped_download=False,
        new_sha256=new_digest,
        payload=payload if changed else None,
        etag=head.etag,
        last_modified=head.last_modified,
    )


def log_poll_audit(
    *,
    actor: str,
    doc_id: str,
    reason: str,
    audit_fn: Callable[..., object] | None = None,
    action: str = "SOURCE_RECHECKED",
) -> None:
    """Log audit event for regulation check."""
    if audit_fn is None:
        try:
            from infra.audit import log_event

            audit_fn = log_event
        except ImportError:
            return

    try:
        audit_fn(
            case_id=None,
            actor=actor,
            action=action,
            input_ref=doc_id,
            reason=reason,
        )
    except TypeError:
        logger.warning("log_poll_audit: audit_fn không nhận đúng kwargs contract cho doc %s", doc_id)


def poll_sources_from_db(
    conn: sqlite3.Connection,
    *,
    actor: str = "SYSTEM:poller",
    head_checker: Callable[[str], HeadInfo] = check_url_head,
    body_fetcher: Callable[[str], bytes] | None = None,
    audit_fn: Callable[..., object] | None = None,
    etag_cache: dict[str, str] | None = None,
    last_modified_cache: dict[str, str] | None = None,
) -> list[PollCheckResult]:
    """Scan all registered regulation sources in DB that have a source_url.

    Performs smart polling, identifies changed regulations, and logs audit events.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT doc_id, title, source_url, sha256 FROM sources "
        "WHERE source_url IS NOT NULL AND source_url != '' "
        "ORDER BY doc_id"
    ).fetchall()

    results: list[PollCheckResult] = []
    for row in rows:
        url = str(row["source_url"])
        doc_id = str(row["doc_id"])
        stored_etag = (
            etag_cache.get(doc_id) or etag_cache.get(url)
            if etag_cache
            else None
        )
        stored_last_mod = (
            last_modified_cache.get(doc_id) or last_modified_cache.get(url)
            if last_modified_cache
            else None
        )
        res = check_source_update(
            doc_id=doc_id,
            url=url,
            title=str(row["title"] or ""),
            stored_sha256=str(row["sha256"]),
            stored_etag=stored_etag,
            stored_last_modified=stored_last_mod,
            head_checker=head_checker,
            body_fetcher=body_fetcher,
        )
        log_poll_audit(
            actor=actor,
            doc_id=res.doc_id,
            reason=f"Kiểm tra nguồn {url}: {res.status_message.lower()}",
            audit_fn=audit_fn,
        )
        results.append(res)

    return results


def stage_updated_source(
    conn: sqlite3.Connection,
    check: PollCheckResult,
    *,
    actor: str = "SYSTEM:poller",
    audit_fn: Callable[..., object] | None = None,
) -> str:
    """Stage a detected regulation change into sources table with status PENDING_REVIEW.

    Follows safe staging buffer principle: never directly overwrites active corpus.
    Returns the new document ID.
    """
    if not check.changed or not check.payload or not check.new_sha256:
        raise ValueError("Nguồn chưa thay đổi hoặc không có nội dung mới")

    # Anti-duplicate check: see if this exact sha256 is already stored
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT doc_id FROM sources WHERE sha256 = ?", (check.new_sha256,)
    ).fetchone()
    if existing:
        return str(existing["doc_id"])

    new_doc_id = "DOC-" + check.new_sha256[:12].upper()
    parsed = urlparse(check.url)
    filename = Path(parsed.path).name or "quy-che-moi"

    conn.execute(
        """INSERT INTO sources (
            doc_id, title, source_url, source_kind, sha256, fetched_at,
            status, content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_doc_id,
            check.title or filename,
            check.url,
            "url",
            check.new_sha256,
            now_iso(),
            "PENDING_REVIEW",
            check.new_sha256,
            now_iso(),
        ),
    )
    conn.commit()

    log_poll_audit(
        actor=actor,
        doc_id=new_doc_id,
        reason=f"Phát hiện quy chế mới từ {check.url}, đưa vào PENDING_REVIEW",
        audit_fn=audit_fn,
        action="SOURCE_UPLOADED",
    )
    return new_doc_id


def check_and_rerun_affected_case(
    case_id: str,
    new_corpus_version: str,
    *,
    actor: str = "SYSTEM:poller",
) -> tuple[Any, dict[str, Any]]:
    """Trigger rerun_case for an existing case against the newly updated corpus version."""
    from core.controls import rerun_case

    return rerun_case(case_id, actor=actor, new_corpus_version=new_corpus_version)
