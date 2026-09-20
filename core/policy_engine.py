from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import yaml

from core.types import (
    Decision,
    EscalationType,
    EvidenceResult,
    Extraction,
    PolicyDecision,
)

logger = logging.getLogger(__name__)

# Danh sách biến ngữ cảnh được phép sử dụng trong biểu thức YAML
ALLOWED_VARIABLES = frozenset(
    {
        "decision_lock",
        "evidence_status",
        "llm_error",
        "parse_error",
        "timeout",
        "guard_failed",
    }
)


class SafeExpressionEvaluator:
    """Bộ giải biểu thức logic AST an toàn cho policy.yaml.

    Tuyệt đối cấm eval() trần.
    Chỉ cho phép các toán tử so sánh (==, !=, in, not in), logic (and, or, not)
    và các biến nằm trong ALLOWED_VARIABLES.
    """

    @classmethod
    def evaluate(cls, expression: str, context: dict[str, Any]) -> bool:
        if not expression or not expression.strip():
            return False

        try:
            tree = ast.parse(expression.strip(), mode="eval")
            return bool(cls._eval_node(tree.body, context))
        except Exception as exc:
            raise ValueError(f"Không thể thẩm định biểu thức policy '{expression}': {exc}") from exc

    @classmethod
    def _eval_node(cls, node: ast.AST, context: dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.Name):
            if node.id not in ALLOWED_VARIABLES:
                raise ValueError(f"Biến '{node.id}' không nằm trong danh sách cho phép của policy.")
            return context.get(node.id, False)

        elif isinstance(node, (ast.List, ast.Tuple)):
            return [cls._eval_node(elt, context) for elt in node.elts]

        elif isinstance(node, ast.Set):
            return {cls._eval_node(elt, context) for elt in node.elts}

        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not cls._eval_node(node.operand, context)
            raise ValueError(f"Toán tử một ngôi không được hỗ trợ: {type(node.op)}")

        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(cls._eval_node(val, context) for val in node.values)
            elif isinstance(node.op, ast.Or):
                return any(cls._eval_node(val, context) for val in node.values)
            raise ValueError(f"Toán tử logic không được hỗ trợ: {type(node.op)}")

        elif isinstance(node, ast.Compare):
            left_val = cls._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right_val = cls._eval_node(comparator, context)
                if isinstance(op, ast.Eq):
                    if left_val != right_val:
                        return False
                elif isinstance(op, ast.NotEq):
                    if left_val == right_val:
                        return False
                elif isinstance(op, ast.In):
                    if left_val not in right_val:
                        return False
                elif isinstance(op, ast.NotIn):
                    if left_val in right_val:
                        return False
                else:
                    raise TypeError(f"Toán tử so sánh không được hỗ trợ: {type(op)}")
                left_val = right_val
            return True

        else:
            raise TypeError(f"Cú pháp AST không được cho phép trong policy: {type(node).__name__}")


def load_policy_rules(policy_path: str = "policies/policy.yaml") -> list[dict[str, Any]]:
    """Đọc danh sách các quy tắc ưu tiên từ policy.yaml."""
    path = Path(policy_path)
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file policy: {policy_path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("priority_order", [])


def evaluate_policy(
    decision_lock: str | None,
    evidence_res: EvidenceResult,
    extraction: Extraction,
    corpus_version: str,
    *,
    policy_path: str = "policies/policy.yaml",
    guard_failed: bool = False,
    parse_error: bool = False,
    timeout: bool = False,
    case_id: str = "",
) -> PolicyDecision:
    """R6: Policy Engine (Deterministic) - Task A-13.

    Đọc policy.yaml, đánh giá biểu thức `when` bằng SafeExpressionEvaluator.
    Duyệt tuần tự theo priority_order và dừng ở luật đầu tiên khớp.
    Nếu không khớp luật nào (bug) -> ép về P04 fail-safe.
    """
    context: dict[str, Any] = {
        "decision_lock": decision_lock or "",
        "evidence_status": evidence_res.status.value,
        "llm_error": bool(extraction.llm_error),
        "parse_error": parse_error,
        "timeout": timeout,
        "guard_failed": guard_failed,
    }

    evidence_ids = [c.chunk_id for c in evidence_res.chunks]
    rules = load_policy_rules(policy_path)

    for rule in rules:
        rule_id = rule.get("id", "UNKNOWN")
        is_else = bool(rule.get("else", False))
        when_expr = rule.get("when", "")

        matched = False
        if is_else:
            matched = True
        elif when_expr:
            matched = SafeExpressionEvaluator.evaluate(when_expr, context)

        if matched:
            raw_decision = rule.get("decision", "ESCALATE")
            decision = Decision(raw_decision)

            raw_type = rule.get("type")
            escalation_type = EscalationType(raw_type) if raw_type else None

            reason = rule.get("reason_vi", "")

            _log_policy_audit(case_id, rule_id, decision.value)

            return PolicyDecision(
                decision=decision,
                escalation_type=escalation_type,
                rule_id=rule_id,
                reason=reason,
                evidence_ids=evidence_ids,
                corpus_version=corpus_version,
            )

    # Fail-safe nếu không khớp luật nào trong YAML
    return PolicyDecision(
        decision=Decision.ESCALATE,
        escalation_type=EscalationType.FACT_UNRESOLVED,
        rule_id="P04",
        reason="Hệ thống không hoàn tất được bước xử lý nên dừng lại thay vì phỏng đoán.",
        evidence_ids=evidence_ids,
        corpus_version=corpus_version,
    )


def _log_policy_audit(case_id: str, rule_id: str, decision: str) -> None:
    """Ghi nhận audit event POLICY_DECIDED nếu infra khả dụng."""
    if not case_id:
        return
    try:
        from infra.audit import log_event  # type: ignore[import-not-found]

        log_event(
            case_id=case_id,
            actor="SYSTEM",
            action="POLICY_DECIDED",
            rule_id=rule_id,
            output_ref=decision,
        )
    except ImportError:
        logger.debug("infra.audit chưa sẵn sàng — bỏ qua ghi audit trong môi trường phát triển")
    except Exception:
        logger.exception("Ghi audit POLICY_DECIDED thất bại")
