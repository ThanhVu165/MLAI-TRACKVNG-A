from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote
from urllib.request import Request, urlopen

from infra.db import get_connection, now_iso
from infra.settings import LLM_RETRIES, LLM_TIMEOUT_S


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any]
    error: str | None
    latency_ms: int
    prompt_hash: str
    model: str


def _cache_key(prompt_hash: str) -> str:
    return f"llm_cache:{prompt_hash}"


def _cached(prompt_hash: str) -> dict[str, Any] | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (_cache_key(prompt_hash),)
            ).fetchone()
        return cast(dict[str, Any], json.loads(row[0])) if row else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_cache(prompt_hash: str, data: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at, actor) VALUES (?, ?, ?, 'SYSTEM') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (_cache_key(prompt_hash), json.dumps(data, ensure_ascii=False), now_iso()),
        )
        conn.commit()


def _record_latency(case_id: str, step: str, latency_ms: int, ok: bool) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO step_latencies(case_id, step, ms, ok, ts) VALUES (?, ?, ?, ?, ?)",
                (case_id, step, latency_ms, int(ok), now_iso()),
            )
            conn.commit()
    except OSError:
        pass


def _cassette_path(prompt_hash: str) -> Path:
    directory = Path(os.getenv("LLM_CASSETTE_DIR", "tests/cassettes"))
    return directory / f"{prompt_hash}.json"


def _load_cassette(prompt_hash: str) -> dict[str, Any]:
    payload = json.loads(_cassette_path(prompt_hash).read_text(encoding="utf-8"))
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise TypeError("Cassette không chứa JSON object")
    return cast(dict[str, Any], data)


def _save_cassette(prompt_hash: str, model: str, data: dict[str, Any]) -> None:
    path = _cassette_path(prompt_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"model": model, "data": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _request_live(
    prompt: str,
    schema: Mapping[str, object],
    model: str,
    timeout_s: int,
) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model)}:generateContent"
        f"?key={quote(api_key)}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("Gemini không trả JSON object")
    return cast(dict[str, Any], data)


def _matches_schema(data: dict[str, Any], schema: Mapping[str, object]) -> bool:
    required = schema.get("required", [])
    return isinstance(required, list) and all(str(key) in data for key in required)


def call_json(
    prompt: str,
    *,
    schema: Mapping[str, object],
    step: str,
    case_id: str,
    timeout_s: int = LLM_TIMEOUT_S,
    retries: int = LLM_RETRIES,
    temperature: float = 0.0,
) -> LLMResult:
    """Gọi Gemini hoặc replay cassette; luôn trả LLMResult và không ném lỗi."""
    del temperature  # Mọi quyết định dùng nhiệt độ 0 theo contract.
    started = time.perf_counter()
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    mode = os.getenv("LLM_MODE", "replay").lower()
    error: str | None = None

    try:
        data = _cached(prompt_hash)
        if data is None and mode == "replay":
            data = _load_cassette(prompt_hash)
        elif data is None and mode in {"live", "record"}:
            for attempt in range(retries + 1):
                try:
                    data = _request_live(prompt, schema, model, timeout_s)
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt == retries:
                        raise
        elif data is None:
            raise ValueError(f"LLM_MODE không hợp lệ: {mode}")

        if data is None or not _matches_schema(data, schema):
            raise ValueError("Phản hồi LLM không đúng schema")
        _save_cache(prompt_hash, data)
        if mode == "record":
            _save_cassette(prompt_hash, model, data)
        ok = True
    except Exception as exc:  # noqa: BLE001 - contract yêu cầu không ném exception
        data = {}
        error = error or str(exc)
        ok = False

    latency_ms = round((time.perf_counter() - started) * 1000)
    _record_latency(case_id, step, latency_ms, ok)
    return LLMResult(ok, data, error, latency_ms, prompt_hash, model)
