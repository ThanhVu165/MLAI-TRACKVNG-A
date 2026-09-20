"""Tests for Seed Corpus Ingestion and Smart Poller Integration (Option A+B Hybrid)."""

from __future__ import annotations

import json
import sqlite3

from core.poller import (
    HeadInfo,
    poll_sources_from_db,
    stage_updated_source,
)
from core.types import ChunkLabel, Domain, SourceStatus
from corpus.seed import compute_corpus_version, seed_corpus, seed_corpus_if_empty


def test_seed_corpus_empty_database() -> None:
    """Test seeding into an empty database creates 6 docs, >= 45 chunks, and valid cv."""
    conn = sqlite3.connect(":memory:")
    res = seed_corpus(conn)

    assert res["status"] == "seeded"
    assert res["sources_count"] == 6
    assert res["active_sources"] == 5
    assert res["total_chunks"] >= 45
    assert res["total_chunks"] == 48

    # Check target label ratio ~60% auto / ~40% human
    assert 0.50 <= res["auto_ratio"] <= 0.70
    assert 0.30 <= res["human_ratio"] <= 0.50
    assert res["corpus_version"].startswith("cv_")
    assert len(res["corpus_version"]) == 15  # "cv_" + 12 chars

    # Verify sources table
    conn.row_factory = sqlite3.Row
    sources = {
        row["doc_id"]: dict(row)
        for row in conn.execute("SELECT * FROM sources").fetchall()
    }
    assert len(sources) == 6

    # DOC-01: conduct_score, transitional_clause=1, supersedes DOC-02
    doc1 = sources["DOC-01"]
    assert doc1["status"] == SourceStatus.ACTIVE.value
    assert doc1["transitional_clause"] == 1
    assert doc1["is_synthetic"] == 1
    assert "DOC-02" in json.loads(doc1["supersedes_json"])

    # DOC-02: conduct_score, SUPERSEDED by DOC-01
    doc2 = sources["DOC-02"]
    assert doc2["status"] == SourceStatus.SUPERSEDED.value
    assert doc2["superseded_by"] == "DOC-01"
    assert doc2["is_synthetic"] == 1

    # DOC-03: course_withdrawal, ACTIVE
    doc3 = sources["DOC-03"]
    assert doc3["status"] == SourceStatus.ACTIVE.value
    assert doc3["source_kind"] == "pdf"
    assert doc3["is_synthetic"] == 1

    # DOC-04: grade_appeal, ACTIVE
    doc4 = sources["DOC-04"]
    assert doc4["status"] == SourceStatus.ACTIVE.value
    assert doc4["source_kind"] == "web"
    assert doc4["is_synthetic"] == 1

    # DOC-05: course_withdrawal, ACTIVE
    doc5 = sources["DOC-05"]
    assert doc5["status"] == SourceStatus.ACTIVE.value
    assert doc5["is_synthetic"] == 1

    # DOC-06: all domains, ACTIVE
    doc6 = sources["DOC-06"]
    assert doc6["status"] == SourceStatus.ACTIVE.value
    doc6_domains = json.loads(doc6["domains_json"])
    assert Domain.CONDUCT_SCORE.value in doc6_domains
    assert Domain.COURSE_WITHDRAWAL.value in doc6_domains
    assert Domain.GRADE_APPEAL.value in doc6_domains


def test_seed_chunks_structure_and_labels() -> None:
    """Verify chunking semantics, conflict flags, and 100% human_only for doc 6."""
    conn = sqlite3.connect(":memory:")
    seed_corpus(conn)
    conn.row_factory = sqlite3.Row

    chunks = conn.execute("SELECT * FROM chunks ORDER BY doc_id, ord").fetchall()
    assert len(chunks) == 48

    # DOC-06 chunks must ALL be human_only
    doc6_chunks = [c for c in chunks if c["doc_id"] == "DOC-06"]
    assert len(doc6_chunks) == 8
    assert all(c["label"] == ChunkLabel.HUMAN_ONLY.value for c in doc6_chunks)

    # DOC-05 must have conflict_flag on article 4 (tuition refund rate conflict with DOC-03)
    doc5_chunks = [c for c in chunks if c["doc_id"] == "DOC-05"]
    assert len(doc5_chunks) == 7
    art4 = next(c for c in doc5_chunks if c["article_no"] == "4")
    assert art4["conflict_flag"] == 1
    assert art4["conflict_with"] == "DOC-03"

    # Breadcrumb format: Title > Điều X. Title
    for c in chunks:
        assert "Điều" in c["breadcrumb"]
        assert c["token_count"] > 0
        assert c["text"]


def test_seed_corpus_versions_and_settings() -> None:
    """Verify corpus_versions and settings are properly populated."""
    conn = sqlite3.connect(":memory:")
    res = seed_corpus(conn)

    conn.row_factory = sqlite3.Row
    cv_row = conn.execute("SELECT * FROM corpus_versions").fetchone()
    assert cv_row is not None
    assert cv_row["corpus_version"] == res["corpus_version"]
    active_docs = json.loads(cv_row["active_doc_ids_json"])
    assert len(active_docs) == 5
    assert "DOC-02" not in active_docs  # SUPERSEDED doc is excluded

    setting_row = conn.execute(
        "SELECT value FROM settings WHERE key = 'current_corpus_version'"
    ).fetchone()
    assert setting_row is not None
    assert setting_row["value"] == res["corpus_version"]


def test_seed_corpus_if_empty_idempotent() -> None:
    """Verify seed_corpus_if_empty does not duplicate records when DB has data."""
    conn = sqlite3.connect(":memory:")
    res1 = seed_corpus_if_empty(conn)
    assert res1["status"] == "seeded"

    res2 = seed_corpus_if_empty(conn)
    assert res2["status"] == "already_present"
    assert res2["sources_count"] == 6
    assert res2["corpus_version"] == res1["corpus_version"]

    # Verify count hasn't doubled
    count = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    assert count == 6


def test_seed_corpus_force_reseed() -> None:
    """Verify force=True cleanly resets and reseeds."""
    conn = sqlite3.connect(":memory:")
    seed_corpus(conn)

    # Insert a dummy chunk that shouldn't survive force reseed
    conn.execute(
        "INSERT INTO chunks (chunk_id, doc_id, breadcrumb, text, domain, label) "
        "VALUES ('dummy', 'DOC-01', 'b', 't', 'domain', 'human_only')"
    )
    conn.commit()

    res = seed_corpus(conn, force=True)
    assert res["status"] == "seeded"
    assert res["total_chunks"] == 48

    dummy = conn.execute(
        "SELECT chunk_id FROM chunks WHERE chunk_id = 'dummy'"
    ).fetchone()
    assert dummy is None


def test_compute_corpus_version_deterministic() -> None:
    """Verify compute_corpus_version produces identical hashes for identical data."""
    conn1 = sqlite3.connect(":memory:")
    conn2 = sqlite3.connect(":memory:")

    seed_corpus(conn1)
    seed_corpus(conn2)

    cv1 = compute_corpus_version(conn1)
    cv2 = compute_corpus_version(conn2)
    assert cv1 == cv2
    assert cv1.startswith("cv_")


def test_smart_poller_integration_with_seeded_db() -> None:
    """Verify Smart Poller HEAD checks seamlessly scan seeded sources (Option A+B Hybrid)."""
    conn = sqlite3.connect(":memory:")
    seed_corpus(conn)

    # Simulate HEAD check with ETag cache matching registered sources (0s download)
    def fast_head(url: str) -> HeadInfo:
        return HeadInfo(
            url=url,
            etag="v1-stable",
            last_modified="Thu, 20 Feb 2026 08:00:00 GMT",
            content_length=2048,
            accessible=True,
        )

    all_etags = {f"DOC-0{i}": "v1-stable" for i in range(1, 7)}
    results = poll_sources_from_db(
        conn,
        actor="ADMIN:poller_test",
        head_checker=fast_head,
        etag_cache=all_etags,
    )

    assert len(results) == 6
    assert all(r.changed is False for r in results)
    assert all(r.skipped_download is True for r in results)
    assert all(r.status_message == "Không đổi" for r in results)

    # Now simulate an updated regulation (Option B demo scenario)
    def updated_head(url: str) -> HeadInfo:
        if "rut-hoc-phan" in url:
            return HeadInfo(
                url=url,
                etag="v2-amended",
                last_modified="Fri, 27 Mar 2026 09:00:00 GMT",
                content_length=4096,
                accessible=True,
            )
        return HeadInfo(
            url=url,
            etag="v1-stable",
            last_modified="Thu, 20 Feb 2026 08:00:00 GMT",
            content_length=2048,
            accessible=True,
        )

    new_content = b"QUY CHE RUT HOC PHAN 2026 (SUA DOI BO SUNG DIEU 3)"

    def custom_fetcher(url: str) -> bytes:
        return new_content

    results2 = poll_sources_from_db(
        conn,
        actor="ADMIN:poller_test",
        head_checker=updated_head,
        body_fetcher=custom_fetcher,
        etag_cache=all_etags,
    )

    changed_results = [r for r in results2 if r.changed]
    assert len(changed_results) == 1
    assert changed_results[0].doc_id == "DOC-03"
    assert changed_results[0].status_message == "Đã đổi"

    # Stage the detected change into PENDING_REVIEW
    staged_id = stage_updated_source(
        conn, changed_results[0], actor="ADMIN:poller_test"
    )
    assert staged_id.startswith("DOC-")

    # Verify PENDING_REVIEW record in DB
    staged_row = conn.execute(
        "SELECT doc_id, status, sha256 FROM sources WHERE status = 'PENDING_REVIEW'"
    ).fetchone()
    assert staged_row is not None
    assert staged_row[0] == staged_id
    assert staged_row[1] == SourceStatus.PENDING_REVIEW.value
