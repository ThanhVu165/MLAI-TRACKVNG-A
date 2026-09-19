from __future__ import annotations

from datetime import date

import pytest

from core.policy_engine import (
    SafeExpressionEvaluator,
    evaluate_policy,
    load_policy_rules,
)
from core.types import (
    ChunkLabel,
    Decision,
    Domain,
    EscalationType,
    EvidenceChunk,
    EvidenceResult,
    EvidenceStatus,
    Extraction,
    RequestItem,
)


def _make_evidence_result(status: EvidenceStatus, chunk_ids: list[str] | None = None) -> EvidenceResult:
    chunks = [
        EvidenceChunk(
            chunk_id=cid,
            doc_id="doc_1",
            breadcrumb="QĐ 3150/2026 · Điều 8",
            text="Nội dung...",
            domain=Domain.COURSE_WITHDRAWAL,
            label=ChunkLabel.AUTO_ANSWERABLE,
            score=0.9,
            effective_from=date(2025, 1, 1),
            effective_to=None,
            applies_to=["all"],
            cohorts=["K2023"],
            transitional_clause=False,
            conflict_flag=False,
        )
        for cid in (chunk_ids or ["chunk_01"])
    ]
    return EvidenceResult(status=status, chunks=chunks, failed_checks=[])


def _make_extraction(llm_error: bool = False) -> Extraction:
    req = RequestItem(
        domain=Domain.COURSE_WITHDRAWAL,
        intent="hoi_thoi_han_rut_mon",
        is_informational=True,
        requires_personal_record=False,
        asks_exception=False,
        asks_appeal=False,
        asks_authority_decision=False,
    )
    return Extraction(
        language="vi",
        requests=[req],
        critical_facts={"deadline": "2026-10-15"},
        missing_critical_facts=[],
        injection_suspected=False,
        raw_json="{}",
        llm_error="LLM error occurred" if llm_error else None,
    )


class TestSafeExpressionEvaluator:
    def test_equality_and_booleans(self) -> None:
        ctx = {"decision_lock": "AUTHORITY_REQUIRED", "llm_error": False}
        assert SafeExpressionEvaluator.evaluate("decision_lock == 'AUTHORITY_REQUIRED'", ctx) is True
        assert SafeExpressionEvaluator.evaluate("decision_lock != 'AUTHORITY_REQUIRED'", ctx) is False
        assert SafeExpressionEvaluator.evaluate("not llm_error", ctx) is True

    def test_in_operator(self) -> None:
        ctx = {"evidence_status": "fact_missing"}
        assert (
            SafeExpressionEvaluator.evaluate(
                "evidence_status in ['fact_missing', 'scope_mismatch']",
                ctx,
            )
            is True
        )
        ctx_other = {"evidence_status": "ok"}
        assert (
            SafeExpressionEvaluator.evaluate(
                "evidence_status in ['fact_missing', 'scope_mismatch']",
                ctx_other,
            )
            is False
        )
        assert (
            SafeExpressionEvaluator.evaluate(
                "evidence_status not in ['fact_missing', 'scope_mismatch']",
                ctx_other,
            )
            is True
        )

    def test_disallowed_variables_rejected(self) -> None:
        ctx = {"hacker_var": "evil"}
        with pytest.raises(ValueError, match="không nằm trong danh sách cho phép"):
            SafeExpressionEvaluator.evaluate("hacker_var == 'evil'", ctx)

    def test_malicious_code_execution_blocked(self) -> None:
        ctx: dict[str, object] = {}
        with pytest.raises(ValueError):
            SafeExpressionEvaluator.evaluate("__import__('os').system('dir')", ctx)

        with pytest.raises(ValueError):
            SafeExpressionEvaluator.evaluate("decision_lock.__class__", ctx)

    def test_empty_expression(self) -> None:
        assert SafeExpressionEvaluator.evaluate("", {}) is False
        assert SafeExpressionEvaluator.evaluate("   ", {}) is False


class TestPolicyEngineRules:
    def test_load_policy_rules(self) -> None:
        rules = load_policy_rules("policies/policy.yaml")
        assert len(rules) == 5
        rule_ids = [r["id"] for r in rules]
        assert rule_ids == ["P01", "P02", "P03", "P04", "P05"]

    def test_missing_policy_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_policy_rules("policies/non_existent.yaml")

    def test_p01_authority_lock_triggers_escalate(self) -> None:
        evidence = _make_evidence_result(EvidenceStatus.OK)
        extraction = _make_extraction()

        policy_dec = evaluate_policy(
            decision_lock="AUTHORITY_REQUIRED",
            evidence_res=evidence,
            extraction=extraction,
            corpus_version="v1.0",
        )

        assert policy_dec.rule_id == "P01"
        assert policy_dec.decision == Decision.ESCALATE
        assert policy_dec.escalation_type == EscalationType.AUTHORITY_REQUIRED
        assert "hồ sơ cá nhân" in policy_dec.reason or "phê duyệt" in policy_dec.reason

    def test_p01_priority_over_evidence_or_llm_error(self) -> None:
        """P01 phải đứng đầu tiên theo priority_order, vượt qua cả lỗi LLM hay thiếu evidence."""
        evidence = _make_evidence_result(EvidenceStatus.NO_AUTHORITATIVE_SOURCE)
        extraction = _make_extraction(llm_error=True)

        policy_dec = evaluate_policy(
            decision_lock="AUTHORITY_REQUIRED",
            evidence_res=evidence,
            extraction=extraction,
            corpus_version="v1.0",
            guard_failed=True,
        )

        assert policy_dec.rule_id == "P01"
        assert policy_dec.decision == Decision.ESCALATE
        assert policy_dec.escalation_type == EscalationType.AUTHORITY_REQUIRED

    def test_p02_evidence_unresolved_triggers_out_of_policy(self) -> None:
        statuses = [
            EvidenceStatus.NO_AUTHORITATIVE_SOURCE,
            EvidenceStatus.AUTHORITY_CONTENT,
            EvidenceStatus.CONFLICTING_SOURCES,
            EvidenceStatus.UNSUPPORTED_DOMAIN,
        ]
        extraction = _make_extraction()

        for st in statuses:
            evidence = _make_evidence_result(st)
            policy_dec = evaluate_policy(
                decision_lock=None,
                evidence_res=evidence,
                extraction=extraction,
                corpus_version="v1.0",
            )
            assert policy_dec.rule_id == "P02"
            assert policy_dec.decision == Decision.ESCALATE
            assert policy_dec.escalation_type == EscalationType.OUT_OF_POLICY

    def test_p03_fact_missing_or_scope_mismatch(self) -> None:
        for st in [EvidenceStatus.FACT_MISSING, EvidenceStatus.SCOPE_MISMATCH]:
            evidence = _make_evidence_result(st)
            extraction = _make_extraction()
            policy_dec = evaluate_policy(
                decision_lock=None,
                evidence_res=evidence,
                extraction=extraction,
                corpus_version="v1.0",
            )
            assert policy_dec.rule_id == "P03"
            assert policy_dec.decision == Decision.ESCALATE
            assert policy_dec.escalation_type == EscalationType.FACT_UNRESOLVED

    def test_p04_technical_errors_trigger_escalate(self) -> None:
        evidence = _make_evidence_result(EvidenceStatus.OK)

        # 1. LLM Error
        extraction_err = _make_extraction(llm_error=True)
        dec_llm = evaluate_policy(
            decision_lock=None,
            evidence_res=evidence,
            extraction=extraction_err,
            corpus_version="v1.0",
        )
        assert dec_llm.rule_id == "P04"
        assert dec_llm.decision == Decision.ESCALATE
        assert dec_llm.escalation_type == EscalationType.FACT_UNRESOLVED

        # 2. Timeout
        extraction_ok = _make_extraction(llm_error=False)
        dec_timeout = evaluate_policy(
            decision_lock=None,
            evidence_res=evidence,
            extraction=extraction_ok,
            corpus_version="v1.0",
            timeout=True,
        )
        assert dec_timeout.rule_id == "P04"
        assert dec_timeout.decision == Decision.ESCALATE

        # 3. Guard failed
        dec_guard = evaluate_policy(
            decision_lock=None,
            evidence_res=evidence,
            extraction=extraction_ok,
            corpus_version="v1.0",
            guard_failed=True,
        )
        assert dec_guard.rule_id == "P04"
        assert dec_guard.decision == Decision.ESCALATE

    def test_p05_auto_reply_when_clean_and_sufficient(self) -> None:
        evidence = _make_evidence_result(EvidenceStatus.OK, chunk_ids=["c_rule_01", "c_rule_02"])
        extraction = _make_extraction(llm_error=False)

        policy_dec = evaluate_policy(
            decision_lock=None,
            evidence_res=evidence,
            extraction=extraction,
            corpus_version="v1.0",
        )

        assert policy_dec.rule_id == "P05"
        assert policy_dec.decision == Decision.AUTO_REPLY
        assert policy_dec.escalation_type is None
        assert policy_dec.evidence_ids == ["c_rule_01", "c_rule_02"]
