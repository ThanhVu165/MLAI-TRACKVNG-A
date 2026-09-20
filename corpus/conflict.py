from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from itertools import combinations

NUMBER_RE = re.compile(r"\d+(?:[./-]\d+)*")
DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
PERCENT_RE = re.compile(r"\d+\s*%")
WORD_RE = re.compile(r"\w+", re.UNICODE)
STOPWORDS = frozenset(
    {"sinh", "viên", "được", "trong", "và", "của", "là", "từ", "đến", "hết", "kỳ"}
)


def scheduled_supersedes(conn: sqlite3.Connection, new_doc_id: str) -> list[str]:
    row = conn.execute(
        "SELECT supersedes_json FROM sources WHERE doc_id = ?", (new_doc_id,)
    ).fetchone()
    if not row or not row[0]:
        return []
    targets = json.loads(row[0])
    return [
        str(doc_id)
        for doc_id in targets
        if conn.execute(
            "SELECT 1 FROM sources WHERE doc_id = ? AND status = 'ACTIVE'", (doc_id,)
        ).fetchone()
    ]


def _topic(text: str) -> str | frozenset[str]:
    folded = text.casefold()
    if "hoàn" in folded and "học phí" in folded:
        return "refund_rate"
    if "hạn" in folded and "rút học phần" in folded:
        return "withdrawal_deadline"
    if "thang" in folded and "điểm rèn luyện" in folded:
        return "conduct_scale"
    return frozenset(word for word in WORD_RE.findall(folded) if word not in STOPWORDS)


def _same_topic(left: str, right: str) -> bool:
    left_topic, right_topic = _topic(left), _topic(right)
    if isinstance(left_topic, str) or isinstance(right_topic, str):
        return left_topic == right_topic
    union = left_topic | right_topic
    return bool(union) and len(left_topic & right_topic) / len(union) >= 0.4


def _claims(text: str) -> set[str]:
    topic = _topic(text)
    if topic == "withdrawal_deadline":
        return set(DATE_RE.findall(text))
    if topic == "refund_rate":
        return {value.replace(" ", "") for value in PERCENT_RE.findall(text)}
    return set(NUMBER_RE.findall(text))


def detect_conflicts(
    conn: sqlite3.Connection,
    *,
    audit: Callable[..., object] | None = None,
) -> list[tuple[str, str]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""SELECT chunks.chunk_id, chunks.doc_id, chunks.text, chunks.domain
           FROM chunks JOIN sources ON sources.doc_id = chunks.doc_id
           WHERE sources.status = 'ACTIVE'""").fetchall()
    conn.execute("""UPDATE chunks SET conflict_flag = 0, conflict_with = NULL
           WHERE doc_id IN (SELECT doc_id FROM sources WHERE status = 'ACTIVE')""")
    conflicts: list[tuple[str, str]] = []
    related: dict[str, set[str]] = {}

    # ponytail: O(n²) fits the 54-chunk Sprint 1 corpus; group by topic if corpus reaches thousands.
    for left, right in combinations(rows, 2):
        if left["doc_id"] == right["doc_id"] or left["domain"] != right["domain"]:
            continue
        left_numbers, right_numbers = _claims(left["text"]), _claims(right["text"])
        if (
            not left_numbers
            or not right_numbers
            or left_numbers == right_numbers
            or not _same_topic(left["text"], right["text"])
        ):
            continue
        left_id, right_id = str(left["chunk_id"]), str(right["chunk_id"])
        conflicts.append((left_id, right_id))
        related.setdefault(left_id, set()).add(right_id)
        related.setdefault(right_id, set()).add(left_id)

    for chunk_id, peers in related.items():
        conn.execute(
            "UPDATE chunks SET conflict_flag = 1, conflict_with = ? WHERE chunk_id = ?",
            (",".join(sorted(peers)), chunk_id),
        )
    conn.commit()

    if conflicts:
        if audit is None:
            try:
                from infra.audit import log_event

                audit = log_event
            except ImportError:
                audit = None
        if audit:
            for left_id, right_id in conflicts:
                audit(
                    case_id=None,
                    actor="SYSTEM",
                    action="SOURCE_METADATA_EDITED",
                    reason=f"Gắn cờ xung đột giữa {left_id} và {right_id}",
                    sources=[left_id, right_id],
                )
    return conflicts
