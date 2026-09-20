from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from functools import lru_cache

from core.types import ChunkLabel, Domain, EvidenceChunk
from corpus.indexer import HybridIndex, build_index
from corpus.store import current_corpus_version
from infra.db import get_connection as _get_connection


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
    """Return the current database version."""
    conn = _get_connection()
    return current_corpus_version(conn)


def search(
    query: str,
    domains: list[Domain],
    top_k: int = 6,
    at: datetime | None = None,
) -> list[EvidenceChunk]:
    """Search ACTIVE database chunks."""
    if top_k <= 0:
        return []

    conn = _get_connection()
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
