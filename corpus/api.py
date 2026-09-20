from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import date, datetime

from core.types import ChunkLabel, Domain, EvidenceChunk


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


def get_corpus_version() -> str:
    """Return the stable version of the in-memory Sprint 1 stub corpus."""
    return _CORPUS_VERSION


def search(
    query: str,
    domains: list[Domain],
    top_k: int = 6,
    at: datetime | None = None,
) -> list[EvidenceChunk]:
    """Search active stub chunks with a small deterministic token-overlap score."""
    if top_k <= 0:
        return []

    requested = set(domains) - {Domain.UNKNOWN}
    query_tokens = set(_TOKEN_RE.findall(query.casefold()))
    active_on = at.date() if at else date.today()
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


def get_chunk(chunk_id: str) -> EvidenceChunk | None:
    """Return an active chunk by ID."""
    return _BY_ID.get(chunk_id)


def is_active(chunk_id: str) -> bool:
    """Report whether a chunk belongs to the active stub corpus."""
    return chunk_id in _BY_ID


def supported_domains() -> list[Domain]:
    """Return the three domains supported in Sprint 1."""
    return [Domain.CONDUCT_SCORE, Domain.COURSE_WITHDRAWAL, Domain.GRADE_APPEAL]
