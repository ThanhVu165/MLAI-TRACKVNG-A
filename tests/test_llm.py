from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infra import llm
from infra.db import fetch_all

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("LLM_CASSETTE_DIR", str(tmp_path / "cassettes"))
    monkeypatch.setenv("LLM_MODE", mode)


def test_replay_reads_cassette_and_records_latency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path, "replay")
    prompt = "fixture prompt"
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    cassette = tmp_path / "cassettes" / f"{digest}.json"
    cassette.parent.mkdir()
    cassette.write_text(json.dumps({"data": {"answer": "ok"}}), encoding="utf-8")

    result = llm.call_json(prompt, schema=SCHEMA, step="R2", case_id="c1")

    assert result.ok and result.data == {"answer": "ok"}
    rows = fetch_all("SELECT case_id, step, ok FROM step_latencies", db_path=tmp_path / "app.db")
    assert tuple(rows[0]) == ("c1", "R2", 1)


def test_live_retries_once_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path, "live")
    calls = 0

    def fail(*args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise TimeoutError("mất kết nối")

    monkeypatch.setattr(llm, "_request_live", fail)
    result = llm.call_json("new prompt", schema=SCHEMA, step="R2", case_id="c2")

    assert not result.ok and "mất kết nối" in (result.error or "")
    assert calls == 2
