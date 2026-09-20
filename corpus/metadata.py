from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
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
