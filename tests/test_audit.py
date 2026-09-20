from __future__ import annotations

from pathlib import Path

import pytest

from infra.audit import ACTIONS, events_for_case, log_event, recent_events


def test_log_and_query_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "audit.db"))
    event_id = log_event(
        case_id="c1",
        actor="SYSTEM",
        action="POLICY_DECIDED",
        rule_id="P05",
        reason="Đủ căn cứ tự động",
        sources=["chunk-1"],
        corpus_version="cv_1",
    )

    events = events_for_case("c1")
    assert isinstance(ACTIONS, frozenset)
    assert events[0].event_id == event_id
    assert events[0].sources == ["chunk-1"]
    assert recent_events(1) == events


@pytest.mark.parametrize(
    "action", ["OVERRIDE_DECISION", "PAUSE_AUTOMATION", "HUMAN_DECISION", "CANCEL_SEND"]
)
def test_reason_is_required(action: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "audit.db"))
    with pytest.raises(ValueError, match="bắt buộc có lý do"):
        log_event(case_id="c1", actor="ADMIN:test", action=action)


def test_rejects_unknown_action(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "audit.db"))
    with pytest.raises(ValueError, match="không hợp lệ"):
        log_event(case_id=None, actor="SYSTEM", action="MADE_UP")


@pytest.mark.parametrize(
    ("legacy", "contract"),
    [
        ("CASE_PROCESSED", "CASE_RESOLVED"),
        ("AUTOMATION_PAUSED", "PAUSE_AUTOMATION"),
        ("AUTOMATION_RESUMED", "RESUME_AUTOMATION"),
        ("DECISION_OVERRIDDEN", "OVERRIDE_DECISION"),
        ("CASE_RERUN", "RERUN_CASE"),
    ],
)
def test_runtime_action_aliases_are_stored_as_contract_actions(
    legacy: str, contract: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "audit.db"))
    log_event(
        case_id="c1",
        actor="ADMIN:test" if legacy != "CASE_PROCESSED" else "SYSTEM",
        action=legacy,
        output_ref="Lý do từ runtime",
    )
    event = events_for_case("c1")[0]
    assert event.action == contract
    if contract in {"PAUSE_AUTOMATION", "OVERRIDE_DECISION"}:
        assert event.reason == "Lý do từ runtime"
