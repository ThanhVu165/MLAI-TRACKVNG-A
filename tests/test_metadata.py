from dataclasses import dataclass

import pytest

from corpus.metadata import SourceMetadata, suggest_metadata


@dataclass
class FakeResult:
    ok: bool
    data: dict[str, object]
    error: str | None = None


def test_metadata_prompt_uses_first_3000_chars_and_preserves_unknowns() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def caller(prompt: str, **kwargs: object) -> FakeResult:
        calls.append((prompt, kwargs))
        return FakeResult(
            True,
            {
                "document_id": "RL-2026-3150",
                "title": "Quy định rèn luyện",
                "issuer": None,
                "published_at": None,
                "effective_from": "2026-07-07",
                "effective_to": None,
                "applies_to": ["undergraduate"],
                "cohorts": ["K48"],
                "supersedes": ["RL-2025-2363"],
                "transitional_clause": True,
                "domains": ["conduct_score"],
            },
        )

    metadata = suggest_metadata("x" * 3001 + "SECRET", case_id="DOC-1", caller=caller)

    assert isinstance(metadata, SourceMetadata)
    assert metadata.issuer is None
    assert metadata.transitional_clause is True
    assert metadata.status == "PENDING_REVIEW"
    assert "SECRET" not in calls[0][0]
    assert calls[0][1]["step"] == "K3_metadata"


def test_metadata_fails_closed_when_llm_fails() -> None:
    def caller(_prompt: str, **_kwargs: object) -> FakeResult:
        return FakeResult(False, {}, "timeout")

    with pytest.raises(RuntimeError, match="timeout"):
        suggest_metadata("Điều 1", case_id="DOC-1", caller=caller)
