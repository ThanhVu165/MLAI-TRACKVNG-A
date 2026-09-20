from __future__ import annotations

import logging
from datetime import datetime

from core.types import Domain, EvidenceChunk, EvidenceStatus, Extraction

logger = logging.getLogger(__name__)


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

        chunks: list[EvidenceChunk] = search(query=query, domains=target_domains, top_k=6, at=at)

        # Nếu câu hỏi thông tin thường quy (không xin ngoại lệ/thẩm quyền), ưu tiên chunk auto_answerable
        needs_human = any(
            req.asks_exception or req.asks_appeal or req.asks_authority_decision
            for req in extraction.requests
        )
        if not needs_human:
            auto_chunks = [c for c in chunks if c.label == "auto_answerable"]
            if auto_chunks:
                chunks = auto_chunks

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
