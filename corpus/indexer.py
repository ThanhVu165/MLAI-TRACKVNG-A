from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from rank_bm25 import BM25Okapi

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    def encode(
        self, sentences: str | list[str], *, normalize_embeddings: bool = True
    ) -> np.ndarray: ...


@dataclass(frozen=True)
class SearchHit:
    record: dict[str, object]
    score: float


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.casefold())


def _normalize(scores: np.ndarray) -> np.ndarray:
    if not len(scores):
        return scores
    minimum, maximum = float(scores.min()), float(scores.max())
    if maximum == minimum:
        return np.ones_like(scores) if maximum > 0 else np.zeros_like(scores)
    return (scores - minimum) / (maximum - minimum)


def _active_records(conn: sqlite3.Connection) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT chunks.*, sources.effective_from, sources.effective_to,
                  sources.applies_to_json, sources.cohorts_json,
                  sources.transitional_clause
           FROM chunks JOIN sources ON sources.doc_id = chunks.doc_id
           WHERE sources.status = 'ACTIVE'
           ORDER BY chunks.doc_id, chunks.ord, chunks.chunk_id"""
    ).fetchall()
    return [dict(row) for row in rows]


def _load_embedder(model_name: str) -> Embedder:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _cached_embeddings(
    records: Sequence[dict[str, object]],
    embedder: Embedder,
    *,
    cache_dir: Path | None,
    corpus_version: str,
) -> np.ndarray:
    texts = [f"{record['breadcrumb']} {record['text']}" for record in records]
    digest = hashlib.sha256("\n".join(texts).encode()).hexdigest()[:12]
    cache_path = cache_dir / f"{corpus_version}_{digest}.npz" if cache_dir else None
    if cache_path and cache_path.exists():
        return np.load(cache_path)["embeddings"]
    embeddings = np.asarray(embedder.encode(texts, normalize_embeddings=True), dtype=float)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_path, embeddings=embeddings)
    return embeddings


class HybridIndex:
    def __init__(
        self,
        records: list[dict[str, object]],
        embeddings: np.ndarray,
        embedder: Embedder,
    ) -> None:
        self.records = records
        self.embeddings = embeddings
        self.embedder = embedder
        self._bm25 = BM25Okapi([tokenize(str(record["text"])) for record in records])

    def search(self, query: str, domains: list[str], top_k: int = 6) -> list[SearchHit]:
        if not query.strip() or top_k <= 0 or not self.records:
            return []
        bm25_scores = _normalize(np.asarray(self._bm25.get_scores(tokenize(query)), dtype=float))
        query_vector = np.asarray(
            self.embedder.encode(query, normalize_embeddings=True), dtype=float
        ).reshape(-1)
        vector_scores = _normalize(self.embeddings @ query_vector)
        combined = (bm25_scores + vector_scores) / 2
        allowed = set(domains)
        indices = sorted(range(len(self.records)), key=lambda index: -combined[index])
        return [
            SearchHit(self.records[index], float(combined[index]))
            for index in indices
            if not allowed or str(self.records[index]["domain"]) in allowed
        ][:top_k]


def build_index(
    conn: sqlite3.Connection,
    corpus_version: str,
    *,
    cache_dir: str | Path | None = None,
    embedder: Embedder | None = None,
    model_name: str = DEFAULT_MODEL,
) -> HybridIndex | None:
    records = _active_records(conn)
    if not records:
        return None
    actual_embedder = embedder or _load_embedder(model_name)
    embeddings = _cached_embeddings(
        records,
        actual_embedder,
        cache_dir=Path(cache_dir) if cache_dir else None,
        corpus_version=corpus_version,
    )
    return HybridIndex(records, embeddings, actual_embedder)
