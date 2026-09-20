from __future__ import annotations

from pathlib import Path

import pytest

from infra.audit import log_event
from infra.db import get_connection
from infra.telemetry import snapshot


def test_snapshot_computes_metrics_from_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "metrics.db"))
    with get_connection() as conn:
        for case_id in ("c1", "c2"):
            conn.execute(
                "INSERT INTO cases(case_id, trace_id, channel, created_at, status, corpus_version) "
                "VALUES (?, ?, 'verify', '2026-09-20T00:00:00Z', 'DONE', 'cv_1')",
                (case_id, f"tr-{case_id}"),
            )
        conn.execute(
            "INSERT INTO decisions(decision_id, case_id, decision, rule_id, reason, "
            "corpus_version, created_at) VALUES "
            "('d1', 'c1', 'AUTO_REPLY', 'P05', 'đủ căn cứ', 'cv_1', '2026-09-20T00:00:00Z'), "
            "('d2', 'c2', 'ESCALATE', 'P01', 'cần duyệt', 'cv_1', '2026-09-20T00:00:00Z')"
        )
        conn.execute("UPDATE decisions SET escalation_type='AUTHORITY_REQUIRED' WHERE case_id='c2'")
        conn.execute(
            "INSERT INTO human_decisions(id, case_id, actor, choice, reason, review_seconds) "
            "VALUES ('h1', 'c2', 'HUMAN:test', 'approve', 'đã đọc', 4)"
        )
        conn.executemany(
            "INSERT INTO step_latencies(case_id, step, ms, ok, ts) VALUES (?, 'R2', ?, 1, ?)",
            [("c1", 10, "2026-09-20T00:00:00Z"), ("c2", 30, "2026-09-20T00:00:01Z")],
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('verify:missed_escalation_rate', '0.1')"
        )
        conn.commit()
    log_event(
        case_id="c2",
        actor="ADMIN:test",
        action="OVERRIDE_DECISION",
        reason="sửa nhãn",
    )

    metrics = snapshot()

    assert metrics["auto_rate"] == 0.5
    assert metrics["median_review_seconds"] == 4.0
    assert metrics["pct_approved_under_5s"] == 1.0
    assert metrics["override_rate"] == 0.5
    assert metrics["p50_latency_ms"] == {"R2": 20.0}
    assert metrics["p95_latency_ms"] == {"R2": 30.0}
    assert metrics["missed_escalation_rate"] == 0.1
