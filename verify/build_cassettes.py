from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.extract import EXTRACT_PROMPT_V1, _heuristic_extract
from core.sanitize import sanitize_input

ROOT = Path(__file__).parents[1]
CASE_FILES = (
    ROOT / "verify" / "cases_verify4.json",
    ROOT / "verify" / "cases_escalation5.json",
    ROOT / "verify" / "cases_full15.json",
)
CASSETTE_DIR = ROOT / "tests" / "cassettes"


def build() -> int:
    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in CASE_FILES:
        for case in json.loads(path.read_text(encoding="utf-8")):
            item = case["input"]
            sanitized = sanitize_input(str(item["body"]))
            extraction = _heuristic_extract(
                sanitized.body_clean, str(item["subject"]), sanitized.language
            )
            prompt = (
                f"{EXTRACT_PROMPT_V1}\n\nEmail Tiêu đề: {item['subject']}\n"
                f"Nội dung:\n{sanitized.body_clean}"
            )
            digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            data = json.loads(extraction.raw_json)
            data["injection_suspected"] = sanitized.injection_suspected
            target = CASSETTE_DIR / f"{digest}.json"
            target.write_text(
                json.dumps({"model": "deterministic-replay", "data": data}, ensure_ascii=False),
                encoding="utf-8",
            )
            written += 1
    return written


if __name__ == "__main__":
    print(f"Wrote {build()} replay cassettes")
