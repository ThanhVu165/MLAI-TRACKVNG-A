import sqlite3
import time
from pathlib import Path

import numpy as np

from corpus.indexer import build_index


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


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE sources (
          doc_id TEXT PRIMARY KEY, status TEXT NOT NULL, effective_from TEXT,
          effective_to TEXT, applies_to_json TEXT, cohorts_json TEXT,
          transitional_clause INTEGER DEFAULT 0
        );
        CREATE TABLE chunks (
          chunk_id TEXT PRIMARY KEY, doc_id TEXT, article_no TEXT, clause_no TEXT,
          breadcrumb TEXT NOT NULL, text TEXT NOT NULL, domain TEXT NOT NULL,
          label TEXT NOT NULL, conflict_flag INTEGER DEFAULT 0,
          conflict_with TEXT, ord INTEGER, token_count INTEGER
        );
        INSERT INTO sources VALUES ('ACTIVE-DOC', 'ACTIVE', '2026-01-01', NULL, '[]', '[]', 0);
        INSERT INTO sources VALUES ('OLD-DOC', 'SUPERSEDED', '2025-01-01', NULL, '[]', '[]', 0);
        INSERT INTO chunks VALUES
          ('c-active', 'ACTIVE-DOC', '1', '1', 'QĐ mới · Điều 1',
           'Thang điểm rèn luyện là 100 điểm.', 'conduct_score', 'auto_answerable', 0, NULL, 1, 7),
          ('c-old', 'OLD-DOC', '1', '1', 'QĐ cũ · Điều 1',
           'Thang điểm rèn luyện cũ.', 'conduct_score', 'auto_answerable', 0, NULL, 1, 4),
          ('c-withdraw', 'ACTIVE-DOC', '2', '1', 'QĐ mới · Điều 2',
           'Hạn rút học phần là ngày 30 tháng 10.', 'course_withdrawal', 'auto_answerable', 0, NULL, 2, 9);
        """
    )
    return conn


def test_hybrid_index_only_uses_active_chunks_and_is_fast(tmp_path: Path) -> None:
    index = build_index(_db(), "cv_test", cache_dir=str(tmp_path), embedder=FakeEmbedder())
    assert index is not None

    started = time.perf_counter()
    hits = index.search("thang điểm rèn luyện", ["conduct_score"])
    elapsed = time.perf_counter() - started

    assert hits[0].record["chunk_id"] == "c-active"
    assert all(hit.record["chunk_id"] != "c-old" for hit in hits)
    assert all(0 <= hit.score <= 1 for hit in hits)
    assert elapsed < 0.3
    assert list(tmp_path.glob("cv_test_*.npz"))
