from __future__ import annotations

import logging
from datetime import date, datetime

from core.types import ChunkLabel, Domain, EvidenceChunk, EvidenceStatus, Extraction

logger = logging.getLogger(__name__)

# Ngưỡng similarity tối thiểu cho retrieval
SIMILARITY_THRESHOLD = 0.35

# Tập chunk mẫu hỗ trợ khi corpus/api.py chưa có cơ sở dữ liệu thật (Stub)
STUB_CHUNKS: list[EvidenceChunk] = [
    # 1. Domain COURSE_WITHDRAWAL - auto_answerable
    EvidenceChunk(
        chunk_id="chunk_cw_01",
        doc_id="RL-2026-3150",
        breadcrumb="QĐ 3150/2026 · Điều 8 · Khoản 2",
        text="Thời hạn rút học phần được giải quyết trong 8 tuần đầu của học kỳ chính. "
        "Sinh viên nộp đơn online qua cổng thông tin và được hoàn 50% học phí nếu rút trước tuần thứ 4.",
        domain=Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.92,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49", "K50"],
        transitional_clause=False,
        conflict_flag=False,
    ),
    # 2. Domain COURSE_WITHDRAWAL - human_only
    EvidenceChunk(
        chunk_id="chunk_cw_02",
        doc_id="RL-2026-3150",
        breadcrumb="QĐ 3150/2026 · Điều 8 · Khoản 5",
        text="Việc rút học phần sau thời hạn quy định do trường hợp bất khả kháng (tai nạn, bệnh hiểm nghèo) "
        "phải do Trưởng phòng Công tác Sinh viên phê duyệt kèm bệnh án.",
        domain=Domain.COURSE_WITHDRAWAL,
        label=ChunkLabel.HUMAN_ONLY,
        score=0.85,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49", "K50"],
        transitional_clause=False,
        conflict_flag=False,
    ),
    # 3. Domain GRADE_APPEAL - auto_answerable
    EvidenceChunk(
        chunk_id="chunk_ga_01",
        doc_id="HD-2026-102",
        breadcrumb="HD 102/2026 · Mục 3 · Lệ phí",
        text="Lệ phí nộp đơn phúc khảo bài thi kết thúc học phần là 50.000 VNĐ một môn học. "
        "Thời hạn nộp đơn là 7 ngày làm việc kể từ ngày công bố điểm thi chính thức.",
        domain=Domain.GRADE_APPEAL,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.89,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49", "K50"],
        transitional_clause=False,
        conflict_flag=False,
    ),
    # 4. Domain CONDUCT_SCORE - transitional_clause
    EvidenceChunk(
        chunk_id="chunk_cs_01",
        doc_id="QĐ-2026-2363",
        breadcrumb="QĐ 2363/2026 · Điều 14 · Khoản 1",
        text="Sinh viên khóa K48 áp dụng khung điểm rèn luyện cũ (thang 100). "
        "Sinh viên từ khóa K49 trở đi áp dụng quy chế đánh giá rèn luyện theo chuẩn mới (thang 4 mức).",
        domain=Domain.CONDUCT_SCORE,
        label=ChunkLabel.AUTO_ANSWERABLE,
        score=0.88,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        applies_to=["undergraduate"],
        cohorts=["K48", "K49", "K50"],
        transitional_clause=True,
        conflict_flag=False,
    ),
]


def build_search_query(subject: str, body_clean: str, intents: list[str]) -> str:
    """Dựng chuỗi truy vấn từ subject, body_clean và danh sách intent."""
    intent_str = " ".join(intents)
    query_parts = [subject.strip(), intent_str.strip(), body_clean[:200].strip()]
    return " ".join(p for p in query_parts if p).strip()


def retrieve_evidence(
    extraction: Extraction,
    case_id: str = "",
    at: datetime | None = None,
    query: str = "",
) -> tuple[list[EvidenceChunk], EvidenceStatus]:
    """R4: Retrieval Adapter (Task A-11).

    Gọi qua corpus.api.search(query, domains, top_k=6, at=received_at).
    Chỉ giao tiếp qua `corpus.api`, tuyệt đối không import module nội bộ khác của `corpus/`.
    Bọc lỗi corpus thành EvidenceStatus.NO_AUTHORITATIVE_SOURCE.
    """
    target_domains: list[Domain] = [
        req.domain for req in extraction.requests if req.domain != Domain.UNKNOWN
    ]
    if not target_domains:
        target_domains = [Domain.UNKNOWN]

    intents = [req.intent for req in extraction.requests]
    if not query:
        query = build_search_query("", extraction.raw_json, intents)

    try:
        from corpus.api import search  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("corpus.api chưa kết nối — sử dụng stub retrieval")
        needs_human = any(
            req.asks_exception or req.asks_appeal or req.asks_authority_decision
            for req in extraction.requests
        )
        q_lower = query.lower()
        if any(w in q_lower for w in ["bất khả kháng", "sau hạn", "ngoại lệ", "bệnh", "tai nạn"]):
            needs_human = True

        # Lọc chunk mẫu theo domain và quyền tự động trả lời
        matched_chunks: list[EvidenceChunk] = []
        for ch in STUB_CHUNKS:
            if ch.domain in target_domains or Domain.UNKNOWN in target_domains:
                if ch.label == ChunkLabel.HUMAN_ONLY and not needs_human:
                    continue
                matched_chunks.append(ch)

        _log_retrieval_audit(case_id, [c.chunk_id for c in matched_chunks])

        if not matched_chunks:
            return [], EvidenceStatus.NO_AUTHORITATIVE_SOURCE
        return matched_chunks, EvidenceStatus.OK

    try:
        chunks: list[EvidenceChunk] = search(query=query, domains=target_domains, top_k=6, at=at)

        # Ghi audit nếu infra khả dụng
        _log_retrieval_audit(case_id, [c.chunk_id for c in chunks])

        if not chunks:
            return [], EvidenceStatus.NO_AUTHORITATIVE_SOURCE
        return chunks, EvidenceStatus.OK
    except Exception as exc:  # noqa: BLE001
        logger.error("Corpus search thất bại thật sự: %s", exc)
        return [], EvidenceStatus.NO_AUTHORITATIVE_SOURCE


def _log_retrieval_audit(case_id: str, chunk_ids: list[str]) -> None:
    """Ghi nhận audit event EVIDENCE_RETRIEVED nếu infra khả dụng."""
    if not case_id:
        return
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(
            case_id=case_id,
            actor="SYSTEM",
            action="EVIDENCE_RETRIEVED",
            sources=chunk_ids,
        )
    except ImportError:
        logger.debug("infra.audit chưa cấu hình — bỏ qua")
    except Exception:
        logger.exception("Ghi audit EVIDENCE_RETRIEVED thất bại")
