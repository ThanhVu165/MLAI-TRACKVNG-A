from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from infra.db import get_connection, now_iso

ACTIONS = frozenset(
    {
        "CASE_RECEIVED",
        "CASE_SANITIZED",
        "FACTS_EXTRACTED",
        "PREPOLICY_LOCKED",
        "EVIDENCE_RETRIEVED",
        "EVIDENCE_VALIDATED",
        "POLICY_DECIDED",
        "DRAFT_GENERATED",
        "GROUNDEDNESS_FAILED",
        "QUESTION_GENERATED",
        "QUESTION_GUARD_FAILED",
        "CASE_QUEUED",
        "CASE_RESUMED",
        "CASE_RESOLVED",
        "CASE_ERROR",
        "SEND_SCHEDULED",
        "SEND_DISPATCHED",
        "CANCEL_SEND",
        "CORRECTION_CREATED",
        "HUMAN_DECISION",
        "HUMAN_APPROVED_SEND",
        "HUMAN_REJECTED_DRAFT",
        "EXPLAIN_REQUESTED",
        "PAUSE_AUTOMATION",
        "RESUME_AUTOMATION",
        "OVERRIDE_DECISION",
        "RERUN_CASE",
        "SOURCE_UPLOADED",
        "SOURCE_METADATA_EDITED",
        "CHUNK_LABELLED",
        "ACTIVATE_SOURCE",
        "REJECT_SOURCE",
        "SUPERSEDE_SOURCE",
        "ROLLBACK_SOURCE",
        "FLAG_NEEDS_RECHECK",
        "SOURCE_RECHECKED",
        "VERIFY_RUN_STARTED",
        "VERIFY_RUN_FINISHED",
    }
)

REASON_REQUIRED = frozenset(
    {"OVERRIDE_DECISION", "PAUSE_AUTOMATION", "HUMAN_DECISION", "CANCEL_SEND"}
)

_ACTION_ALIASES = {
    "CASE_PROCESSED": "CASE_RESOLVED",
    "AUTOMATION_PAUSED": "PAUSE_AUTOMATION",
    "AUTOMATION_RESUMED": "RESUME_AUTOMATION",
    "DECISION_OVERRIDDEN": "OVERRIDE_DECISION",
    "CASE_RERUN": "RERUN_CASE",
}


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    case_id: str | None
    ts: str
    actor: str
    action: str
    rule_id: str | None
    input_ref: str | None
    output_ref: str | None
    reason: str | None
    sources: list[str]
    corpus_version: str | None


def _valid_actor(actor: str) -> bool:
    return actor == "SYSTEM" or actor.startswith(("HUMAN:", "ADMIN:"))


def log_event(
    *,
    case_id: str | None,
    actor: str,
    action: str,
    rule_id: str | None = None,
    input_ref: str | None = None,
    output_ref: str | None = None,
    reason: str | None = None,
    sources: list[str] | None = None,
    corpus_version: str | None = None,
) -> str:
    original_action = action
    action = _ACTION_ALIASES.get(action, action)
    if original_action in _ACTION_ALIASES and action in REASON_REQUIRED and not reason:
        reason = output_ref
    if action not in ACTIONS:
        raise ValueError(f"Audit action không hợp lệ: {action}")
    if not _valid_actor(actor):
        raise ValueError("Actor phải là SYSTEM, HUMAN:<id> hoặc ADMIN:<id>")
    if action in REASON_REQUIRED and not (reason or "").strip():
        raise ValueError(f"{action} bắt buộc có lý do")

    event_id = f"evt_{uuid.uuid4().hex}"
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO audit_events(
                   event_id, case_id, ts, actor, action, rule_id, input_ref,
                   output_ref, reason, sources_json, corpus_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                case_id,
                now_iso(),
                actor,
                action,
                rule_id,
                input_ref,
                output_ref,
                reason,
                json.dumps(sources or [], ensure_ascii=False),
                corpus_version,
            ),
        )
        conn.commit()
    return event_id


def _event(row: sqlite3.Row) -> AuditEvent:
    values = dict(row)
    return AuditEvent(
        event_id=str(values["event_id"]),
        case_id=str(values["case_id"]) if values["case_id"] is not None else None,
        ts=str(values["ts"]),
        actor=str(values["actor"]),
        action=str(values["action"]),
        rule_id=str(values["rule_id"]) if values["rule_id"] is not None else None,
        input_ref=str(values["input_ref"]) if values["input_ref"] is not None else None,
        output_ref=str(values["output_ref"]) if values["output_ref"] is not None else None,
        reason=str(values["reason"]) if values["reason"] is not None else None,
        sources=[str(item) for item in json.loads(str(values["sources_json"] or "[]"))],
        corpus_version=(
            str(values["corpus_version"]) if values["corpus_version"] is not None else None
        ),
    )


def events_for_case(case_id: str) -> list[AuditEvent]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE case_id = ? ORDER BY ts, event_id", (case_id,)
        ).fetchall()
    return [_event(row) for row in rows]


def recent_events(limit: int = 200) -> list[AuditEvent]:
    if limit < 1:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY ts DESC, event_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_event(row) for row in rows]
