from __future__ import annotations

import math
import statistics
from collections import defaultdict

from infra.db import get_connection


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def snapshot() -> dict[str, object]:
    """Tính telemetry trực tiếp từ DB để số liệu luôn truy vết được."""
    with get_connection() as conn:
        decisions = conn.execute(
            "SELECT decision, escalation_type FROM decisions WHERE superseded_by IS NULL"
        ).fetchall()
        reviews = [
            float(row[0])
            for row in conn.execute(
                "SELECT review_seconds FROM human_decisions WHERE review_seconds IS NOT NULL"
            ).fetchall()
        ]
        audit_counts = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT action, COUNT(*) FROM audit_events GROUP BY action"
            ).fetchall()
        }
        latency_by_step: defaultdict[str, list[int]] = defaultdict(list)
        for row in conn.execute("SELECT step, ms FROM step_latencies WHERE ok = 1").fetchall():
            latency_by_step[str(row[0])].append(int(row[1]))
        stored = {
            str(row[0]): float(row[1])
            for row in conn.execute(
                "SELECT key, value FROM settings WHERE key IN "
                "('verify:missed_escalation_rate', 'verify:over_escalation_rate')"
            ).fetchall()
        }

    total = len(decisions)
    auto = sum(row[0] == "AUTO_REPLY" for row in decisions)
    escalation_total = sum(row[0] == "ESCALATE" for row in decisions)
    escalation_types = {
        name: _rate(
            sum(row[0] == "ESCALATE" and row[1] == name for row in decisions),
            escalation_total,
        )
        for name in ("FACT_UNRESOLVED", "OUT_OF_POLICY", "AUTHORITY_REQUIRED")
    }
    generated = audit_counts.get("DRAFT_GENERATED", auto)

    return {
        "auto_rate": _rate(auto, total),
        "escalation_rate_by_type": escalation_types,
        "p50_latency_ms": {
            step: float(statistics.median(values)) for step, values in latency_by_step.items()
        },
        "p95_latency_ms": {
            step: _percentile(values, 0.95) for step, values in latency_by_step.items()
        },
        "median_review_seconds": float(statistics.median(reviews)) if reviews else 0.0,
        "pct_approved_under_5s": _rate(sum(value < 5 for value in reviews), len(reviews)),
        "override_rate": _rate(audit_counts.get("OVERRIDE_DECISION", 0), total),
        "groundedness_fail_rate": _rate(audit_counts.get("GROUNDEDNESS_FAILED", 0), generated),
        "missed_escalation_rate": stored.get("verify:missed_escalation_rate", 0.0),
        "over_escalation_rate": stored.get("verify:over_escalation_rate", 0.0),
    }
