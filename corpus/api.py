from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import cast

from core.types import ChunkLabel, Domain, EvidenceChunk
from corpus.indexer import HybridIndex, build_index
from corpus.store import current_corpus_version


def _chunk(
    chunk_id: str,
    doc_id: str,
    breadcrumb: str,
    text: str,
    domain: Domain,
    *,
    label: ChunkLabel = ChunkLabel.AUTO_ANSWERABLE,
    transitional_clause: bool = False,
) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        breadcrumb=breadcrumb,
        text=text,
        domain=domain,
        label=label,
        score=0.0,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49", "K50"],
        transitional_clause=transitional_clause,
        conflict_flag=False,
    )


_CHUNKS = (
    _chunk(
        "chunk_cs_01",
        "RL-2026-3150",
        "QĐ 3150/2026 · Điều 4 · Khoản 1",
        "Điểm rèn luyện được đánh giá theo thang 100 điểm và xếp loại theo tổng điểm.",
        Domain.CONDUCT_SCORE,
        transitional_clause=True,
    ),
    _chunk(
        "stub_conduct_02",
        "RL-2026-3150",
        "QĐ 3150/2026 · Điều 6 · Khoản 2",
        "Sinh viên tự đánh giá điểm rèn luyện trên cổng thông tin trong 14 ngày kể từ khi mở đợt.",
        Domain.CONDUCT_SCORE,
    ),
    _chunk(
        "stub_conduct_03",
        "RL-2026-3150",
        "QĐ 3150/2026 · Điều 8 · Khoản 1",
        "Kết quả điểm rèn luyện được công bố trên cổng thông tin sinh viên sau khi khoa phê duyệt.",
        Domain.CONDUCT_SCORE,
    ),
    _chunk(
        "stub_conduct_04",
        "RL-2026-3150",
        "QĐ 3150/2026 · Điều 9 · Khoản 1",
        "Điểm rèn luyện từ 90 điểm trở lên được xếp loại xuất sắc.",
        Domain.CONDUCT_SCORE,
    ),
    _chunk(
        "chunk_cw_01",
        "WD-2026-20",
        "QĐ 20/2026 · Điều 5 · Khoản 1",
        "Sinh viên được rút học phần chậm nhất đến hết ngày 30 tháng 10 năm 2026.",
        Domain.COURSE_WITHDRAWAL,
    ),
    _chunk(
        "stub_withdrawal_02",
        "WD-2026-20",
        "QĐ 20/2026 · Điều 5 · Khoản 2",
        "Đơn rút học phần được nộp trực tuyến trên cổng thông tin sinh viên.",
        Domain.COURSE_WITHDRAWAL,
    ),
    _chunk(
        "stub_withdrawal_03",
        "WD-2026-20",
        "QĐ 20/2026 · Điều 6 · Khoản 1",
        "Học phí được hoàn 70 phần trăm nếu sinh viên rút học phần trong tuần thứ tư đến tuần thứ sáu.",
        Domain.COURSE_WITHDRAWAL,
    ),
    _chunk(
        "chunk_cw_02",
        "AUTH-2026-01",
        "QĐ 01/2026 · Điều 4 · Khoản 1",
        "Các ngoại lệ do hoàn cảnh bất khả kháng phải được Trưởng phòng Công tác Sinh viên phê duyệt.",
        Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.HUMAN_ONLY,
    ),
    _chunk(
        "chunk_ga_01",
        "GA-2026-08",
        "HD 08/2026 · Điều 2 · Khoản 1",
        "Sinh viên nộp đơn phúc khảo trong 7 ngày làm việc kể từ ngày công bố điểm thi.",
        Domain.GRADE_APPEAL,
    ),
    _chunk(
        "stub_appeal_02",
        "GA-2026-08",
        "HD 08/2026 · Điều 2 · Khoản 2",
        "Lệ phí phúc khảo là 50.000 đồng cho mỗi học phần và được nộp cùng đơn.",
        Domain.GRADE_APPEAL,
    ),
    _chunk(
        "stub_appeal_03",
        "GA-2026-08",
        "HD 08/2026 · Điều 3 · Khoản 1",
        "Kết quả phúc khảo được thông báo qua email sinh viên trong 15 ngày làm việc.",
        Domain.GRADE_APPEAL,
    ),
    _chunk(
        "stub_appeal_04",
        "AUTH-2026-01",
        "QĐ 01/2026 · Điều 5 · Khoản 1",
        "Hội đồng phúc khảo quyết định việc thay đổi điểm sau khi đối chiếu bài thi và biên bản chấm.",
        Domain.GRADE_APPEAL,
        label=ChunkLabel.HUMAN_ONLY,
    ),
)

_BY_ID = {chunk.chunk_id: chunk for chunk in _CHUNKS}
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CORPUS_VERSION = (
    "cv_"
    + hashlib.sha256(
        "".join(f"{chunk.doc_id}:{chunk.text}" for chunk in _CHUNKS).encode()
    ).hexdigest()[:12]
)


def _get_connection() -> sqlite3.Connection | None:
    try:
        from infra.db import get_connection
    except (ImportError, AttributeError):
        return None
    return cast(sqlite3.Connection, get_connection())


@lru_cache(maxsize=2)
def _index(conn: sqlite3.Connection, version: str) -> HybridIndex | None:
    return build_index(conn, version, cache_dir="embedding_cache")


def clear_index_cache() -> None:
    """Drop cached indexes after a corpus lifecycle change."""
    _index.cache_clear()


def _json_list(value: object) -> list[str]:
    parsed = json.loads(str(value or "[]"))
    if not isinstance(parsed, list):
        raise TypeError("Metadata phạm vi của chunk phải là danh sách")
    return [str(item) for item in parsed]


def _evidence(record: dict[str, object], score: float) -> EvidenceChunk:
    effective_from = record.get("effective_from")
    if not effective_from:
        raise ValueError(f"Chunk {record.get('chunk_id')} thiếu ngày hiệu lực")
    effective_to = record.get("effective_to")
    return EvidenceChunk(
        chunk_id=str(record["chunk_id"]),
        doc_id=str(record["doc_id"]),
        breadcrumb=str(record["breadcrumb"]),
        text=str(record["text"]),
        domain=Domain(str(record["domain"])),
        label=ChunkLabel(str(record["label"])),
        score=score,
        effective_from=date.fromisoformat(str(effective_from)),
        effective_to=date.fromisoformat(str(effective_to)) if effective_to else None,
        applies_to=_json_list(record.get("applies_to_json")),
        cohorts=_json_list(record.get("cohorts_json")),
        transitional_clause=bool(record.get("transitional_clause")),
        conflict_flag=bool(record.get("conflict_flag")),
    )


def get_corpus_version() -> str:
    """Return the current database version, or the bootstrap stub version."""
    conn = _get_connection()
    return current_corpus_version(conn) if conn is not None else _CORPUS_VERSION


def _search_stub(
    query: str,
    domains: list[Domain],
    top_k: int,
    at: datetime | None,
) -> list[EvidenceChunk]:
    requested = set(domains) - {Domain.UNKNOWN}
    query_tokens = set(_TOKEN_RE.findall(query.casefold()))
    active_on = at.date() if at else datetime.now(timezone.utc).date()
    matches: list[tuple[int, EvidenceChunk]] = []

    for chunk in _CHUNKS:
        if requested and chunk.domain not in requested:
            continue
        if active_on < chunk.effective_from or (
            chunk.effective_to is not None and active_on > chunk.effective_to
        ):
            continue

        haystack = set(_TOKEN_RE.findall(f"{chunk.breadcrumb} {chunk.text}".casefold()))
        overlap = len(query_tokens & haystack)
        score = min(1.0, 0.35 + overlap / max(1, len(query_tokens)))
        matches.append((overlap, replace(chunk, score=score)))

    if not query_tokens:
        return [chunk for _, chunk in matches[:top_k]]
    best_overlap = max((overlap for overlap, _ in matches), default=0)
    if best_overlap == 0:
        return []
    return sorted(
        (chunk for overlap, chunk in matches if overlap == best_overlap),
        key=lambda chunk: chunk.chunk_id,
    )[:top_k]


def search(
    query: str,
    domains: list[Domain],
    top_k: int = 6,
    at: datetime | None = None,
) -> list[EvidenceChunk]:
    """Search ACTIVE database chunks, falling back to the bootstrap stub."""
    if top_k <= 0:
        return []

    conn = _get_connection()
    if conn is None:
        return _search_stub(query, domains, top_k, at)

    index = _index(conn, current_corpus_version(conn))
    if index is None:
        return []
    requested = {domain.value for domain in domains if domain != Domain.UNKNOWN}
    if query.strip():
        candidates = [
            (hit.record, hit.score)
            for hit in index.search(query, sorted(requested), top_k=len(index.records))
        ]
    else:
        candidates = [
            (record, 0.0)
            for record in index.records
            if not requested or str(record["domain"]) in requested
        ]

    active_on = at.date() if at else datetime.now(timezone.utc).date()
    matches: list[EvidenceChunk] = []
    for record, score in candidates:
        chunk = _evidence(record, score)
        if active_on < chunk.effective_from or (
            chunk.effective_to is not None and active_on > chunk.effective_to
        ):
            continue
        matches.append(chunk)
        if len(matches) == top_k:
            break
    return matches


def get_chunk(chunk_id: str) -> EvidenceChunk | None:
    """Return an active chunk by ID."""
    conn = _get_connection()
    if conn is None:
        return _BY_ID.get(chunk_id)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT chunks.*, sources.effective_from, sources.effective_to,
                  sources.applies_to_json, sources.cohorts_json,
                  sources.transitional_clause
           FROM chunks JOIN sources ON sources.doc_id = chunks.doc_id
           WHERE chunks.chunk_id = ? AND sources.status = 'ACTIVE'""",
        (chunk_id,),
    ).fetchone()
    return _evidence(dict(row), 0.0) if row else None


def is_active(chunk_id: str) -> bool:
    """Report whether a chunk belongs to the active corpus."""
    return get_chunk(chunk_id) is not None


def supported_domains() -> list[Domain]:
    """Return the three domains supported in Sprint 1."""
    return [Domain.CONDUCT_SCORE, Domain.COURSE_WITHDRAWAL, Domain.GRADE_APPEAL]
