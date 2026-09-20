from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

METADATA_PROMPT_V1 = """Bạn chỉ trích xuất metadata từ văn bản quy định bên dưới.
Không suy đoán. Trường nào không có căn cứ phải trả null hoặc danh sách rỗng.
Đặc biệt kiểm tra văn bản bị thay thế, ngày hiệu lực, khóa áp dụng và điều khoản chuyển tiếp.

VĂN BẢN:
{text}
"""

METADATA_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "document_id": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
        "issuer": {"type": ["string", "null"]},
        "published_at": {"type": ["string", "null"]},
        "effective_from": {"type": ["string", "null"]},
        "effective_to": {"type": ["string", "null"]},
        "applies_to": {"type": "array", "items": {"type": "string"}},
        "cohorts": {"type": "array", "items": {"type": "string"}},
        "supersedes": {"type": "array", "items": {"type": "string"}},
        "transitional_clause": {"type": ["boolean", "null"]},
        "domains": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "document_id",
        "title",
        "issuer",
        "published_at",
        "effective_from",
        "effective_to",
        "applies_to",
        "cohorts",
        "supersedes",
        "transitional_clause",
        "domains",
    ],
    "additionalProperties": False,
}


class LLMResultLike(Protocol):
    ok: bool
    data: dict[str, object]
    error: str | None


@dataclass(frozen=True)
class SourceMetadata:
    document_id: str | None
    title: str | None
    issuer: str | None
    published_at: str | None
    effective_from: str | None
    effective_to: str | None
    applies_to: list[str]
    cohorts: list[str]
    supersedes: list[str]
    transitional_clause: bool | None
    domains: list[str]
    status: str
    content_hash: str


SUPPORTED_DOMAINS = frozenset({"conduct_score", "course_withdrawal", "grade_appeal"})


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def suggest_metadata(
    text: str,
    *,
    case_id: str,
    caller: Callable[..., LLMResultLike] | None = None,
) -> SourceMetadata:
    if caller is None:
        from infra.llm import call_json

        caller = call_json

    result = caller(
        METADATA_PROMPT_V1.format(text=text[:3000]),
        schema=METADATA_SCHEMA,
        step="K3_metadata",
        case_id=case_id,
        temperature=0.0,
    )
    if not result.ok:
        raise RuntimeError(result.error or "Không thể trích xuất metadata")

    data = result.data
    transitional = data.get("transitional_clause")
    return SourceMetadata(
        document_id=_optional_string(data.get("document_id")),
        title=_optional_string(data.get("title")),
        issuer=_optional_string(data.get("issuer")),
        published_at=_optional_string(data.get("published_at")),
        effective_from=_optional_string(data.get("effective_from")),
        effective_to=_optional_string(data.get("effective_to")),
        applies_to=_string_list(data.get("applies_to")),
        cohorts=_string_list(data.get("cohorts")),
        supersedes=_string_list(data.get("supersedes")),
        transitional_clause=transitional if isinstance(transitional, bool) else None,
        domains=_string_list(data.get("domains")),
        status="PENDING_REVIEW",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def validate_metadata(
    conn: sqlite3.Connection,
    metadata: SourceMetadata,
    *,
    existing_doc_id: str | None = None,
) -> None:
    if not metadata.document_id or not metadata.title or not metadata.issuer:
        raise ValueError("Mã văn bản, tiêu đề và đơn vị ban hành là bắt buộc")
    if not metadata.effective_from:
        raise ValueError("Ngày bắt đầu hiệu lực là bắt buộc")
    try:
        effective_from = date.fromisoformat(metadata.effective_from)
        effective_to = date.fromisoformat(metadata.effective_to) if metadata.effective_to else None
        if metadata.published_at:
            date.fromisoformat(metadata.published_at)
    except ValueError as exc:
        raise ValueError("Ngày phải có định dạng YYYY-MM-DD") from exc
    if effective_to and effective_from > effective_to:
        raise ValueError("Ngày bắt đầu hiệu lực phải trước hoặc bằng ngày kết thúc")
    if not metadata.domains or not set(metadata.domains) <= SUPPORTED_DOMAINS:
        raise ValueError("Domain không thuộc phạm vi hỗ trợ")
    if metadata.transitional_clause is None:
        raise ValueError("Phải xác nhận có điều khoản chuyển tiếp hay không")
    duplicate = conn.execute(
        "SELECT 1 FROM sources WHERE doc_id = ? AND doc_id != ?",
        (metadata.document_id, existing_doc_id or ""),
    ).fetchone()
    if duplicate:
        raise ValueError("Mã văn bản đã tồn tại")


def save_metadata(
    conn: sqlite3.Connection,
    existing_doc_id: str,
    metadata: SourceMetadata,
    *,
    actor: str,
    audit: Callable[..., object] | None = None,
) -> list[str]:
    validate_metadata(conn, metadata, existing_doc_id=existing_doc_id)
    conn.row_factory = sqlite3.Row
    old_row = conn.execute("SELECT * FROM sources WHERE doc_id = ?", (existing_doc_id,)).fetchone()
    if not old_row:
        raise KeyError(existing_doc_id)

    values: dict[str, object] = {
        "doc_id": metadata.document_id,
        "title": metadata.title,
        "issuer": metadata.issuer,
        "published_at": metadata.published_at,
        "effective_from": metadata.effective_from,
        "effective_to": metadata.effective_to,
        "applies_to_json": json.dumps(metadata.applies_to, ensure_ascii=False),
        "cohorts_json": json.dumps(metadata.cohorts, ensure_ascii=False),
        "supersedes_json": json.dumps(metadata.supersedes, ensure_ascii=False),
        "transitional_clause": 1 if metadata.transitional_clause else 0,
        "domains_json": json.dumps(metadata.domains, ensure_ascii=False),
        "status": "PENDING_REVIEW",
        "content_hash": metadata.content_hash,
    }
    changed = [column for column, value in values.items() if old_row[column] != value]
    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(
        f"UPDATE sources SET {assignments} WHERE doc_id = ?",
        [*values.values(), existing_doc_id],
    )
    conn.execute(
        "DELETE FROM settings WHERE key IN (?, ?)",
        (f"review:{existing_doc_id}", f"review:{metadata.document_id}"),
    )
    conn.commit()

    if changed:
        if audit is None:
            try:
                from infra.audit import log_event

                audit = log_event
            except ImportError:
                audit = None
        if audit:
            audit(
                case_id=None,
                actor=actor,
                action="SOURCE_METADATA_EDITED",
                input_ref=str(metadata.document_id),
                reason="Đã sửa metadata: " + ", ".join(changed),
            )
    return changed
