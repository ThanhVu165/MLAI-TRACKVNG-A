from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.pipeline import process_case
from core.types import CaseInput, Decision, PipelineResult
from corpus.api import is_active
from corpus.seed import seed_if_empty
from infra.audit import log_event
from infra.db import get_connection, now_iso, to_local

ROOT = Path(__file__).parent
SETS = {
    "verify4": ROOT / "cases_verify4.json",
    "escalation5": ROOT / "cases_escalation5.json",
    "full15": ROOT / "cases_full15.json",
}
LABELS = ["AUTO_REPLY", "FACT_UNRESOLVED", "OUT_OF_POLICY", "AUTHORITY_REQUIRED"]
REQUIRED_FIELDS = {
    "id",
    "input",
    "expected_decision",
    "expected_type",
    "expected_rule_id",
    "rationale",
    "how_to_run",
}


@dataclass(frozen=True)
class VerifyResult:
    case_id: str
    test_id: str
    input_summary: str
    expected: str
    actual: str
    rule_id: str
    reason: str
    passed: bool
    elapsed_ms: int
    timestamp: str
    corpus_version: str
    question: str
    audit_url: str


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} phải chứa một danh sách case.")
    for index, case in enumerate(payload, start=1):
        if not isinstance(case, dict) or not REQUIRED_FIELDS <= case.keys():
            missing = REQUIRED_FIELDS - set(case) if isinstance(case, dict) else REQUIRED_FIELDS
            raise ValueError(f"Case #{index} thiếu trường: {', '.join(sorted(missing))}")
        if (
            not isinstance(case["input"], dict)
            or not {"sender", "subject", "body"} <= case["input"].keys()
        ):
            raise ValueError(f"Case {case['id']} có input không hợp lệ.")
    return payload


def _label(decision: str, escalation_type: str | None) -> str:
    return "AUTO_REPLY" if decision == "AUTO_REPLY" else escalation_type or decision


def _pass(case: dict[str, Any], result: PipelineResult) -> bool:
    expected_decision = str(case["expected_decision"])
    expected_type = case.get("expected_type")
    type_matches = (
        result.decision.escalation_type.value if result.decision.escalation_type else None
    ) == expected_type
    if result.decision.decision.value != expected_decision:
        return False
    if expected_decision == Decision.ESCALATE.value and not type_matches:
        return False
    if expected_decision == Decision.AUTO_REPLY.value:
        citations = result.draft.citations if result.draft else []
        return any(is_active(citation) for citation in citations)
    return True


def _run_case(case: dict[str, Any]) -> VerifyResult:
    data = case["input"]
    inp = CaseInput(
        sender=str(data["sender"]),
        subject=str(data["subject"]),
        body=str(data["body"]),
        received_at=datetime.now(timezone.utc),
        channel="verify",
        external_id=str(case["id"]),
    )
    started = time.perf_counter()
    result = process_case(inp)
    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    expected = _label(str(case["expected_decision"]), case.get("expected_type"))
    actual = _label(
        result.decision.decision.value,
        result.decision.escalation_type.value if result.decision.escalation_type else None,
    )
    return VerifyResult(
        case_id=result.case_id,
        test_id=str(case["id"]),
        input_summary=f"{data['subject']}: {str(data['body'])[:80]}",
        expected=expected,
        actual=actual,
        rule_id=result.decision.rule_id,
        reason=result.decision.reason,
        passed=_pass(case, result),
        elapsed_ms=elapsed_ms,
        timestamp=to_local(now_iso()),
        corpus_version=result.corpus_version,
        question=result.card.question if result.card else "",
        audit_url=f"pages/4_Nhat_ky_kiem_toan.py?case_id={result.case_id}",
    )


def run_set(name: str) -> list[VerifyResult]:
    if name not in SETS:
        raise ValueError(f"Bộ Verify không tồn tại: {name}")
    with get_connection() as conn:
        seed_if_empty(conn)
    cases = _load_cases(SETS[name])
    log_event(
        case_id=None,
        actor="SYSTEM",
        action="VERIFY_RUN_STARTED",
        reason=f"Bắt đầu chạy tuần tự bộ {name} gồm {len(cases)} case.",
    )
    results = [_run_case(case) for case in cases]
    log_event(
        case_id=None,
        actor="SYSTEM",
        action="VERIFY_RUN_FINISHED",
        reason=f"Hoàn tất bộ {name}: {sum(result.passed for result in results)}/{len(results)} PASS.",
    )
    if name == "full15":
        _save_error_rates(results)
    return results


def confusion_matrix(results: list[VerifyResult]) -> dict[str, dict[str, int]]:
    matrix = {expected: {actual: 0 for actual in LABELS} for expected in LABELS}
    for result in results:
        if result.expected in matrix and result.actual in matrix[result.expected]:
            matrix[result.expected][result.actual] += 1
    return matrix


def error_rates(results: list[VerifyResult]) -> tuple[float, float]:
    expected_escalations = [result for result in results if result.expected != "AUTO_REPLY"]
    expected_auto = [result for result in results if result.expected == "AUTO_REPLY"]
    missed = sum(result.actual == "AUTO_REPLY" for result in expected_escalations)
    excessive = sum(result.actual != "AUTO_REPLY" for result in expected_auto)
    return (
        round(missed / len(expected_escalations), 4) if expected_escalations else 0.0,
        round(excessive / len(expected_auto), 4) if expected_auto else 0.0,
    )


def _save_error_rates(results: list[VerifyResult]) -> None:
    missed, excessive = error_rates(results)
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO settings(key, value, updated_at, actor) VALUES (?, ?, ?, 'SYSTEM')
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value, updated_at=excluded.updated_at, actor=excluded.actor""",
            [
                ("verify:missed_escalation_rate", str(missed), now_iso()),
                ("verify:over_escalation_rate", str(excessive), now_iso()),
            ],
        )
        conn.commit()


def _print(results: list[VerifyResult]) -> None:
    print("ID   RESULT   EXPECTED             ACTUAL               MS")
    for result in results:
        outcome = "PASS" if result.passed else "FAIL"
        print(
            f"{result.test_id:<4} {outcome:<8} {result.expected:<20} "
            f"{result.actual:<20} {result.elapsed_ms}"
        )
        if not result.passed:
            safe_reason = result.reason.encode("ascii", "backslashreplace").decode()
            print(f"     reason: {safe_reason}")
    print(f"Total: {sum(result.passed for result in results)}/{len(results)} PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy Verify qua core.pipeline.process_case")
    parser.add_argument("--set", choices=sorted(SETS), default="verify4")
    parser.add_argument("--json", action="store_true", help="In JSON thay cho bảng chữ")
    args = parser.parse_args()
    results = run_set(args.set)
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        _print(results)


if __name__ == "__main__":
    main()
