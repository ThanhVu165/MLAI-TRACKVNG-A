from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from corpus.metadata import LLMResultLike

LABELS = frozenset({"auto_answerable", "human_only"})
COVERAGE_PROMPT_V1 = """Đề xuất nhãn cho từng điều khoản.
auto_answerable chỉ dành cho thông tin thủ tục có thể trả lời nguyên văn.
human_only dành cho ngoại lệ, phê duyệt, hồ sơ cá nhân hoặc quyết định thẩm quyền.
Đây chỉ là đề xuất; quản trị viên sẽ quyết định.

CHUNKS:
{chunks}
"""
COVERAGE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "label": {"enum": sorted(LABELS)},
                    "reason": {"type": "string"},
                },
                "required": ["chunk_id", "label", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


def list_coverage(conn: sqlite3.Connection, doc_id: str) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT chunk_id, breadcrumb, text, label FROM chunks WHERE doc_id = ? ORDER BY ord",
        (doc_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def label_chunk(
    conn: sqlite3.Connection,
    chunk_id: str,
    label: str,
    *,
    actor: str,
    audit: Callable[..., object] | None = None,
) -> bool:
    if label not in LABELS:
        raise ValueError("Nhãn chunk không hợp lệ")
    row = conn.execute(
        "SELECT doc_id, label FROM chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()
    if not row:
        raise KeyError(chunk_id)
    doc_id, old_label = str(row[0]), str(row[1])
    if old_label == label:
        return False
    conn.execute("UPDATE chunks SET label = ? WHERE chunk_id = ?", (label, chunk_id))
    conn.execute("DELETE FROM settings WHERE key = ?", (f"review:{doc_id}",))
    conn.commit()
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
            action="CHUNK_LABELLED",
            input_ref=chunk_id,
            output_ref=label,
            reason=f"Đổi nhãn từ {old_label} sang {label}",
            sources=[chunk_id],
        )
    return True


def suggest_labels(
    chunks: list[dict[str, object]],
    *,
    case_id: str,
    caller: Callable[..., LLMResultLike] | None = None,
) -> dict[str, tuple[str, str]]:
    if caller is None:
        from infra.llm import call_json

        caller = call_json
    payload = [
        {
            "chunk_id": chunk["chunk_id"],
            "breadcrumb": chunk["breadcrumb"],
            "text": str(chunk["text"])[:500],
        }
        for chunk in chunks
    ]
    result = caller(
        COVERAGE_PROMPT_V1.format(chunks=json.dumps(payload, ensure_ascii=False)),
        schema=COVERAGE_SCHEMA,
        step="K6_coverage",
        case_id=case_id,
        temperature=0.0,
    )
    if not result.ok:
        raise RuntimeError(result.error or "Không thể đề xuất nhãn")
    valid_ids = {str(chunk["chunk_id"]) for chunk in chunks}
    suggestions: dict[str, tuple[str, str]] = {}
    raw_suggestions = result.data.get("suggestions")
    if not isinstance(raw_suggestions, list):
        return suggestions
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        chunk_id, label = item.get("chunk_id"), item.get("label")
        if chunk_id in valid_ids and label in LABELS:
            suggestions[str(chunk_id)] = (str(label), str(item.get("reason", "")))
    return suggestions
