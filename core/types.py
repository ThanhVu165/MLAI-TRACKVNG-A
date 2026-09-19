from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

# ---------------------------------------------------------------------------
# 5.1 Enum
# ---------------------------------------------------------------------------


class Decision(StrEnum):
    AUTO_REPLY = "AUTO_REPLY"
    ESCALATE = "ESCALATE"
    INVALID_INPUT = "INVALID_INPUT"


class EscalationType(StrEnum):
    FACT_UNRESOLVED = "FACT_UNRESOLVED"  # chưa xác định được thông tin thực tế
    OUT_OF_POLICY = "OUT_OF_POLICY"  # nằm ngoài phạm vi quy định
    AUTHORITY_REQUIRED = "AUTHORITY_REQUIRED"  # vượt thẩm quyền, cần người phê duyệt


class EvidenceStatus(StrEnum):
    OK = "ok"
    NO_AUTHORITATIVE_SOURCE = "no_authoritative_source"
    AUTHORITY_CONTENT = "authority_content"
    CONFLICTING_SOURCES = "conflicting_sources"
    SCOPE_MISMATCH = "scope_mismatch"
    FACT_MISSING = "fact_missing"
    UNSUPPORTED_DOMAIN = "unsupported_domain"


class CaseStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    INVALID_INPUT = "INVALID_INPUT"
    PENDING_SEND = "PENDING_SEND"
    SENT = "SENT"
    CANCELLED = "CANCELLED"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    HUMAN_DECIDED = "HUMAN_DECIDED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RESOLVED = "RESOLVED"
    NEEDS_RECHECK = "NEEDS_RECHECK"
    ERROR = "ERROR"


class Domain(StrEnum):
    CONDUCT_SCORE = "conduct_score"
    COURSE_WITHDRAWAL = "course_withdrawal"
    GRADE_APPEAL = "grade_appeal"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class ChunkLabel(StrEnum):
    AUTO_ANSWERABLE = "auto_answerable"
    HUMAN_ONLY = "human_only"


# ---------------------------------------------------------------------------
# 5.2 Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseInput:
    sender: str
    subject: str
    body: str
    received_at: datetime  # tz-aware, Asia/Ho_Chi_Minh
    channel: Literal["paste", "inbox", "verify"]
    external_id: str | None = None


@dataclass
class RequestItem:
    domain: Domain
    intent: str
    is_informational: bool
    requires_personal_record: bool
    asks_exception: bool
    asks_appeal: bool
    asks_authority_decision: bool


@dataclass
class Extraction:
    language: Literal["vi", "en", "other"]
    requests: list[RequestItem]
    critical_facts: dict[str, str]
    missing_critical_facts: list[str]
    injection_suspected: bool
    raw_json: str
    llm_error: str | None = None


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    doc_id: str
    breadcrumb: str  # "QĐ 3150/2026 · Điều 8 · Khoản 2"
    text: str
    domain: Domain
    label: ChunkLabel
    score: float
    effective_from: date
    effective_to: date | None
    applies_to: list[str]
    cohorts: list[str]
    transitional_clause: bool
    conflict_flag: bool


@dataclass
class EvidenceResult:
    status: EvidenceStatus
    chunks: list[EvidenceChunk]
    failed_checks: list[str]


@dataclass
class PolicyDecision:
    decision: Decision
    escalation_type: EscalationType | None
    rule_id: str  # "P01".."P05"
    reason: str  # tiếng Việt, một câu, cho người đọc
    evidence_ids: list[str]
    corpus_version: str


@dataclass
class DraftReply:
    subject: str
    body: str
    citations: list[str]  # chunk_id
    grounded: bool
    guard_failures: list[str]


@dataclass
class EscalationCard:
    summary: str  # khối [1] ≤ 30 từ
    facts: list[str]  # khối [2]
    basis: list[tuple[str, str]]  # khối [3] (breadcrumb, trích dẫn)
    question: str  # khối [4] một câu hỏi đóng
    options: list[str]  # phương án trả lời sẵn
    escalation_type: EscalationType
    partial_draft: DraftReply | None  # phần thường quy của email đa ý định


@dataclass
class PipelineResult:
    case_id: str
    trace_id: str
    status: CaseStatus
    decision: PolicyDecision
    extraction: Extraction | None
    evidence: EvidenceResult | None
    draft: DraftReply | None
    card: EscalationCard | None
    corpus_version: str
    step_latencies_ms: dict[str, int]
    started_at: datetime
    finished_at: datetime
