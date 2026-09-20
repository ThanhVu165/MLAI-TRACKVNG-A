import inspect
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from core.retrieval import retrieve_evidence
from core.types import ChunkLabel, Domain, EvidenceStatus, Extraction
from corpus import api, indexer
from corpus.api import (
    get_chunk,
    get_corpus_version,
    is_active,
    search,
    supported_domains,
)
from corpus.seed import seed_if_empty
from infra.db import get_connection


class FakeEmbedder:
    def encode(
        self, sentences: str | list[str], *, normalize_embeddings: bool = True
    ) -> np.ndarray:
        values = [sentences] if isinstance(sentences, str) else sentences
        rows = []
        for value in values:
            folded = value.casefold()
            vector = np.array(
                [float("rèn luyện" in folded), float("rút học phần" in folded)], dtype=float
            )
            norm = np.linalg.norm(vector)
            rows.append(vector / norm if norm else np.array([0.5, 0.5]))
        result = np.vstack(rows)
        return result[0] if isinstance(sentences, str) else result


def _db(*, seeded: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE sources (
          doc_id TEXT PRIMARY KEY, status TEXT NOT NULL, content_hash TEXT,
          effective_from TEXT, effective_to TEXT, applies_to_json TEXT,
          cohorts_json TEXT, transitional_clause INTEGER DEFAULT 0
        );
        CREATE TABLE chunks (
          chunk_id TEXT PRIMARY KEY, doc_id TEXT, article_no TEXT, clause_no TEXT,
          breadcrumb TEXT NOT NULL, text TEXT NOT NULL, domain TEXT NOT NULL,
          label TEXT NOT NULL, conflict_flag INTEGER DEFAULT 0,
          conflict_with TEXT, ord INTEGER, token_count INTEGER
        );
        CREATE TABLE settings (
          key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, actor TEXT
        );
        """
    )
    if seeded:
        conn.executescript(
            """
            INSERT INTO sources VALUES
              ('ACTIVE-DOC', 'ACTIVE', 'active-hash', '2026-01-01', NULL,
               '["undergraduate"]', '["K48"]', 0),
              ('OLD-DOC', 'SUPERSEDED', 'old-hash', '2025-01-01', NULL,
               '["undergraduate"]', '["K48"]', 0);
            INSERT INTO chunks VALUES
              ('c-active', 'ACTIVE-DOC', '1', '1', 'QĐ mới · Điều 1',
               'Thang điểm rèn luyện là 100 điểm.', 'conduct_score',
               'auto_answerable', 0, NULL, 1, 7),
              ('c-old', 'OLD-DOC', '1', '1', 'QĐ cũ · Điều 1',
               'Thang điểm rèn luyện cũ.', 'conduct_score',
               'auto_answerable', 0, NULL, 1, 4);
            """
        )
    return conn


def _use_db(monkeypatch: pytest.MonkeyPatch, conn: sqlite3.Connection) -> None:
    api.clear_index_cache()
    monkeypatch.setattr(api, "_get_connection", lambda: conn)
    monkeypatch.setattr(indexer, "_load_embedder", lambda _: FakeEmbedder())


def test_seeded_corpus_contract_and_required_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    conn = get_connection(tmp_path / "corpus.db")
    seed_if_empty(conn)
    _use_db(monkeypatch, conn)
    domains = supported_domains()
    chunks = search("", domains, top_k=100, at=datetime(2026, 9, 20, tzinfo=timezone.utc))

    assert get_corpus_version().startswith("cv_")
    assert domains == [
        Domain.CONDUCT_SCORE,
        Domain.COURSE_WITHDRAWAL,
        Domain.GRADE_APPEAL,
    ]
    assert len(chunks) == 45
    assert {chunk.domain for chunk in chunks} == set(domains)
    assert any(chunk.label == ChunkLabel.HUMAN_ONLY for chunk in chunks)
    assert any(chunk.transitional_clause for chunk in chunks)
    assert all(chunk.doc_id != "RL-2025-2363" for chunk in chunks)
    assert all(
        is_active(chunk.chunk_id) and get_chunk(chunk.chunk_id) is not None for chunk in chunks
    )


def test_search_filters_domain_and_ranks_matching_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_db(monkeypatch, _db())
    chunks = search("thang điểm rèn luyện", [Domain.CONDUCT_SCORE], top_k=2)

    assert chunks
    assert all(chunk.domain == Domain.CONDUCT_SCORE for chunk in chunks)
    assert chunks[0].chunk_id == "c-active"
    assert search("thang điểm rèn luyện", [Domain.UNKNOWN])
    assert search("thang điểm rèn luyện", [Domain.COURSE_WITHDRAWAL]) == []
    assert search("anything", supported_domains(), top_k=0) == []


def test_missing_corpus_module_does_not_return_sample_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "corpus.api", None)
    extraction = Extraction("vi", [], {}, [], False, "{}")
    assert retrieve_evidence(extraction, query="hạn rút học phần") == (
        [],
        EvidenceStatus.NO_AUTHORITATIVE_SOURCE,
    )


def test_database_facade_only_returns_active_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_db(monkeypatch, _db())

    chunks = search(
        "thang điểm rèn luyện",
        [Domain.CONDUCT_SCORE],
        at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )

    assert [chunk.chunk_id for chunk in chunks] == ["c-active"]
    assert get_chunk("c-active") is not None
    assert is_active("c-active")
    assert get_chunk("c-old") is None
    assert not is_active("c-old")
    assert get_corpus_version().startswith("cv_")


def test_contract_is_stable_when_database_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_db(monkeypatch, _db(seeded=False))

    assert list(inspect.signature(search).parameters) == ["query", "domains", "top_k", "at"]
    assert search("quy định", supported_domains()) == []
    assert get_chunk("missing") is None
    assert not is_active("missing")
    assert get_corpus_version().startswith("cv_")
