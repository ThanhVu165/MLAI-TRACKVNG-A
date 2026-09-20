from datetime import datetime, timezone

from core.types import ChunkLabel, Domain
from corpus.api import get_chunk, get_corpus_version, is_active, search, supported_domains


def test_stub_corpus_contract_and_required_coverage() -> None:
    domains = supported_domains()
    chunks = search("", domains, top_k=20, at=datetime(2026, 9, 20, tzinfo=timezone.utc))

    assert get_corpus_version().startswith("cv_")
    assert domains == [
        Domain.CONDUCT_SCORE,
        Domain.COURSE_WITHDRAWAL,
        Domain.GRADE_APPEAL,
    ]
    assert len(chunks) == 12
    assert {chunk.domain for chunk in chunks} == set(domains)
    assert sum(chunk.label == ChunkLabel.HUMAN_ONLY for chunk in chunks) == 2
    assert sum(chunk.transitional_clause for chunk in chunks) == 1
    assert all(
        is_active(chunk.chunk_id) and get_chunk(chunk.chunk_id) is not None for chunk in chunks
    )


def test_search_filters_domain_and_ranks_matching_text() -> None:
    chunks = search("hạn rút học phần", [Domain.COURSE_WITHDRAWAL], top_k=2)

    assert chunks
    assert all(chunk.domain == Domain.COURSE_WITHDRAWAL for chunk in chunks)
    assert chunks[0].chunk_id == "chunk_cw_01"
    assert search("phúc khảo", [Domain.UNKNOWN])
    assert search("anything", supported_domains(), top_k=0) == []
