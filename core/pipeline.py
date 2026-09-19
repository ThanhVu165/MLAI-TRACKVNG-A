from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from core.dispatch import schedule_dispatch
from core.evidence import validate_evidence
from core.extract import extract_facts
from core.generate import generate_reply
from core.ground_guard import validate_groundedness
from core.policy_engine import evaluate_policy
from core.prepolicy import evaluate_prepolicy_lock
from core.question_gen import generate_escalation_card
from core.question_guard import ensure_valid_escalation_card
from core.retrieval import retrieve_evidence
from core.sanitize import evaluate_cheap_guards, sanitize_input
from core.types import (
    CaseInput,
    CaseStatus,
    Decision,
    DraftReply,
    EscalationCard,
    EscalationType,
    PipelineResult,
    PolicyDecision,
)

# Bảng mã Crockford Base32 dùng cho ULID
_CROCKFORD_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_ulid(prefix: str = "c") -> str:
    """Sinh định danh thời gian ULID 26 ký tự (chuẩn hóa Base32)."""
    now_ms = int(time.time() * 1000)
    time_chars: list[str] = []
    for _ in range(10):
        time_chars.append(_CROCKFORD_CHARS[now_ms % 32])
        now_ms //= 32
    time_part = "".join(reversed(time_chars))

    rand_bytes = os.urandom(10)
    rand_int = int.from_bytes(rand_bytes, byteorder="big")
    rand_chars: list[str] = []
    for _ in range(16):
        rand_chars.append(_CROCKFORD_CHARS[rand_int % 32])
        rand_int //= 32
    rand_part = "".join(reversed(rand_chars))

    ulid = f"{time_part}{rand_part}"
    return f"{prefix}_{ulid}" if prefix else ulid


def _get_frozen_corpus_version() -> str:
    """Lấy phiên bản corpus hiện tại từ corpus.api và đóng băng cho suốt case."""
    try:
        from corpus.api import get_corpus_version  # type: ignore[import-not-found]
        return get_corpus_version()
    except (ImportError, Exception):  # noqa: BLE001 - Dự phòng khi corpus.api chưa cấu hình
        return "cv_v1_initial"


def _step_r0_intake(inp: CaseInput) -> tuple[bool, str | None]:
    """R0: Intake - Kiểm tra các trường bắt buộc của CaseInput."""
    if not inp.body or not inp.body.strip():
        return False, "Nội dung email (body) không được để trống."
    if not inp.sender or not inp.sender.strip():
        return False, "Địa chỉ người gửi (sender) không được để trống."
    if not inp.subject or not inp.subject.strip():
        return False, "Tiêu đề email (subject) không được để trống."
    return True, None




def _step_r9_lifecycle(decision: PolicyDecision) -> CaseStatus:
    """R9: Xác định trạng thái vòng đời tiếp theo."""
    if decision.decision == Decision.AUTO_REPLY:
        return CaseStatus.PENDING_SEND
    elif decision.decision == Decision.ESCALATE:
        return CaseStatus.AWAITING_HUMAN
    return CaseStatus.INVALID_INPUT


def _step_r14_audit_telemetry(case_id: str, trace_id: str, action: str) -> None:
    """R14: Audit & Telemetry - Ghi nhật ký kiểm toán."""
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]
        log_event(case_id=case_id, actor="SYSTEM", action=action)
    except (ImportError, Exception):  # noqa: BLE001, S110 - Dự phòng khi infra.audit chưa cấu hình
        pass


def process_case(inp: CaseInput, *, actor: str = "SYSTEM") -> PipelineResult:
    """Điểm vào duy nhất tiếp nhận và xử lý email theo quy trình 14 bước R0 -> R14.

    Tuân thủ nguyên tắc Fail-safe: Mọi lỗi bất ngờ đều được bắt và trả về PipelineResult
    ở trạng thái ESCALATE / P04, tuyệt đối không ném ngoại lệ ra ngoài.
    """
    started_at = datetime.now(timezone.utc)
    step_latencies: dict[str, int] = {}
    case_id = generate_ulid("c")
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    corpus_version = _get_frozen_corpus_version()

    try:
        # -------------------------------------------------------------------
        # R0: Intake
        # -------------------------------------------------------------------
        t0 = time.perf_counter()
        r0_valid, r0_error = _step_r0_intake(inp)
        step_latencies["R0_intake"] = max(1, int((time.perf_counter() - t0) * 1000))

        if not r0_valid:
            finished_at = datetime.now(timezone.utc)
            return PipelineResult(
                case_id=case_id,
                trace_id=trace_id,
                status=CaseStatus.INVALID_INPUT,
                decision=PolicyDecision(
                    decision=Decision.INVALID_INPUT,
                    escalation_type=None,
                    rule_id="P00",
                    reason=r0_error or "Đầu vào không hợp lệ.",
                    evidence_ids=[],
                    corpus_version=corpus_version,
                ),
                extraction=None,
                evidence=None,
                draft=None,
                card=None,
                corpus_version=corpus_version,
                step_latencies_ms=step_latencies,
                started_at=started_at,
                finished_at=finished_at,
            )

        # -------------------------------------------------------------------
        # R1: Sanitize & 3 chốt chặn rẻ
        # -------------------------------------------------------------------
        t1 = time.perf_counter()
        sanitized = sanitize_input(inp.body)
        guard_decision, guard_esc_type, guard_reason = evaluate_cheap_guards(
            sanitized.body_clean, sanitized.language
        )
        step_latencies["R1_sanitize"] = max(1, int((time.perf_counter() - t1) * 1000))

        if guard_decision is not None:
            finished_at = datetime.now(timezone.utc)
            st = CaseStatus.INVALID_INPUT if guard_decision == Decision.INVALID_INPUT else CaseStatus.AWAITING_HUMAN
            r_id = "P00" if guard_decision == Decision.INVALID_INPUT else "P02"
            return PipelineResult(
                case_id=case_id,
                trace_id=trace_id,
                status=st,
                decision=PolicyDecision(
                    decision=guard_decision,
                    escalation_type=guard_esc_type,
                    rule_id=r_id,
                    reason=guard_reason or "Chốt chặn R1 từ chối xử lý tự động.",
                    evidence_ids=[],
                    corpus_version=corpus_version,
                ),
                extraction=None,
                evidence=None,
                draft=None,
                card=None,
                corpus_version=corpus_version,
                step_latencies_ms=step_latencies,
                started_at=started_at,
                finished_at=finished_at,
            )

        # -------------------------------------------------------------------
        # R2: Extract
        # -------------------------------------------------------------------
        t2 = time.perf_counter()
        extraction = extract_facts(
            sanitized.body_clean,
            inp.subject,
            case_id,
            language=sanitized.language,
        )
        if sanitized.injection_suspected:
            extraction.injection_suspected = True
        step_latencies["R2_extract"] = max(1, int((time.perf_counter() - t2) * 1000))

        # -------------------------------------------------------------------
        # R3: Pre-policy Lock
        # -------------------------------------------------------------------
        t3 = time.perf_counter()
        lock = evaluate_prepolicy_lock(extraction)
        step_latencies["R3_lock"] = max(1, int((time.perf_counter() - t3) * 1000))

        # -------------------------------------------------------------------
        # R4: Retrieve
        # -------------------------------------------------------------------
        t4 = time.perf_counter()
        chunks, _ = retrieve_evidence(
            extraction,
            case_id=case_id,
            at=inp.received_at,
            query=f"{inp.subject} {sanitized.body_clean}",
        )
        step_latencies["R4_retrieve"] = max(1, int((time.perf_counter() - t4) * 1000))

        # -------------------------------------------------------------------
        # R5: Evidence Validate
        # -------------------------------------------------------------------
        t5 = time.perf_counter()
        evidence_res = validate_evidence(chunks, extraction, case_id=case_id)
        step_latencies["R5_evidence"] = max(1, int((time.perf_counter() - t5) * 1000))

        # -------------------------------------------------------------------
        # R6: Policy Engine
        # -------------------------------------------------------------------
        t6 = time.perf_counter()
        decision = evaluate_policy(
            decision_lock=lock,
            evidence_res=evidence_res,
            extraction=extraction,
            corpus_version=corpus_version,
            case_id=case_id,
        )
        step_latencies["R6_policy"] = max(1, int((time.perf_counter() - t6) * 1000))

        draft: DraftReply | None = None
        card: EscalationCard | None = None

        # -------------------------------------------------------------------
        # R7 & R8: Generate & Guards
        # -------------------------------------------------------------------
        t7 = time.perf_counter()
        if decision.decision == Decision.AUTO_REPLY:
            draft = generate_reply(evidence_res, inp, extraction, case_id=case_id)
            grounded_pass, guard_failures = validate_groundedness(draft, evidence_res, case_id=case_id)
            if not grounded_pass:
                # Mục 8.5 spec: Fail bất kỳ mục nào -> ESCALATE / FACT_UNRESOLVED,
                # reason = "groundedness_failed:<mục>", lưu bản nháp với grounded=false để DSA đối chiếu.
                decision = PolicyDecision(
                    decision=Decision.ESCALATE,
                    escalation_type=EscalationType.FACT_UNRESOLVED,
                    rule_id="P04",
                    reason=f"groundedness_failed: {'; '.join(guard_failures)}",
                    evidence_ids=[c.chunk_id for c in evidence_res.chunks],
                    corpus_version=corpus_version,
                )
                raw_card = generate_escalation_card(
                    extraction,
                    evidence_res,
                    EscalationType.FACT_UNRESOLVED,
                    case_id=case_id,
                    inp=inp,
                )
                card = ensure_valid_escalation_card(
                    raw_card,
                    extraction,
                    evidence_res,
                    EscalationType.FACT_UNRESOLVED,
                    case_id=case_id,
                )
        else:
            raw_card = generate_escalation_card(
                extraction,
                evidence_res,
                decision.escalation_type or EscalationType.FACT_UNRESOLVED,
                case_id=case_id,
                inp=inp,
            )
            card = ensure_valid_escalation_card(
                raw_card,
                extraction,
                evidence_res,
                decision.escalation_type or EscalationType.FACT_UNRESOLVED,
                case_id=case_id,
            )
            if card.partial_draft:
                draft = card.partial_draft

        step_latencies["R7_R8_generate_guard"] = max(1, int((time.perf_counter() - t7) * 1000))

        # -------------------------------------------------------------------
        # R9: Lifecycle status & Pause Automation Check
        # -------------------------------------------------------------------
        t9 = time.perf_counter()
        from core.controls import is_automation_paused
        status = _step_r9_lifecycle(decision)
        if status == CaseStatus.PENDING_SEND and is_automation_paused():
            status = CaseStatus.AWAITING_HUMAN
        step_latencies["R9_lifecycle"] = max(1, int((time.perf_counter() - t9) * 1000))

        # -------------------------------------------------------------------
        # R13: Dispatch
        # -------------------------------------------------------------------
        t13 = time.perf_counter()
        if status == CaseStatus.PENDING_SEND and draft is not None:
            schedule_dispatch(case_id, draft, trace_id=trace_id)
        step_latencies["R13_dispatch"] = max(1, int((time.perf_counter() - t13) * 1000))

        # -------------------------------------------------------------------
        # R14: Audit
        # -------------------------------------------------------------------
        t14 = time.perf_counter()
        _step_r14_audit_telemetry(case_id, trace_id, "CASE_PROCESSED")
        step_latencies["R14_audit"] = max(1, int((time.perf_counter() - t14) * 1000))

        finished_at = datetime.now(timezone.utc)
        return PipelineResult(
            case_id=case_id,
            trace_id=trace_id,
            status=status,
            decision=decision,
            extraction=extraction,
            evidence=evidence_res,
            draft=draft,
            card=card,
            corpus_version=corpus_version,
            step_latencies_ms=step_latencies,
            started_at=started_at,
            finished_at=finished_at,
        )

    except Exception as exc:  # noqa: BLE001 - Bắt buộc bọc mọi lỗi theo nguyên tắc Fail-safe của spec
        finished_at = datetime.now(timezone.utc)
        step_latencies["ERROR_HANDLER"] = 1
        return PipelineResult(
            case_id=case_id,
            trace_id=trace_id,
            status=CaseStatus.ERROR,
            decision=PolicyDecision(
                decision=Decision.ESCALATE,
                escalation_type=EscalationType.FACT_UNRESOLVED,
                rule_id="P04",
                reason=f"Hệ thống không hoàn tất được bước xử lý ({type(exc).__name__}) nên dừng lại thay vì phỏng đoán.",
                evidence_ids=[],
                corpus_version=corpus_version,
            ),
            extraction=None,
            evidence=None,
            draft=None,
            card=None,
            corpus_version=corpus_version,
            step_latencies_ms=step_latencies,
            started_at=started_at,
            finished_at=finished_at,
        )
