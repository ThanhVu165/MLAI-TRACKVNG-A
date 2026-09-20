from __future__ import annotations

import importlib

import pytest

from infra import settings


def test_named_thresholds_have_spec_defaults() -> None:
    assert settings.SIMILARITY_THRESHOLD == 0.35
    assert settings.CITATION_RATIO_MIN == 0.6
    assert settings.PENDING_SEND_SECONDS == 60
    assert settings.MIN_WORDS_GUARD == 15
    assert settings.LLM_TIMEOUT_S == 20
    assert settings.LLM_RETRIES == 1
    assert settings.RETRIEVAL_TOP_K == 6
    assert (settings.QUESTION_WORDS_MIN, settings.QUESTION_WORDS_MAX) == (8, 45)
    assert settings.RECHECK_WINDOW_DAYS == 30


def test_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TOP_K", "9")
    assert importlib.reload(settings).RETRIEVAL_TOP_K == 9
    monkeypatch.delenv("RETRIEVAL_TOP_K")
    importlib.reload(settings)
