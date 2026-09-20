from __future__ import annotations

import inspect

from core.controls import (
    cancel_send,
    override_decision,
    pause_automation,
    rerun_case,
    resume_automation,
)
from core.explain import explain_plainly
from core.resume import resume_after_human
from core.types import DraftReply, PipelineResult


def test_pause_automation_signature() -> None:
    sig = inspect.signature(pause_automation)
    params = list(sig.parameters.keys())
    assert "actor" in params
    assert "reason" in params
    assert sig.return_annotation in (None, type(None), "None")


def test_resume_automation_signature() -> None:
    sig = inspect.signature(resume_automation)
    params = list(sig.parameters.keys())
    assert "actor" in params
    assert sig.return_annotation in (None, type(None), "None")


def test_override_decision_signature() -> None:
    sig = inspect.signature(override_decision)
    params = list(sig.parameters.keys())
    # Tham số bắt buộc theo contract Mục 5.3
    assert params[0] == "case_id"
    assert params[1] == "new_decision"
    assert "actor" in params
    assert "reason" in params
    assert sig.return_annotation in (PipelineResult, "PipelineResult")


def test_rerun_case_signature() -> None:
    sig = inspect.signature(rerun_case)
    params = list(sig.parameters.keys())
    assert params[0] == "case_id"
    assert "actor" in params
    # Return annotation tuple[PipelineResult, dict]
    ret = sig.return_annotation
    assert "PipelineResult" in str(ret) and "dict" in str(ret)


def test_cancel_send_signature() -> None:
    sig = inspect.signature(cancel_send)
    params = list(sig.parameters.keys())
    assert params[0] == "case_id"
    assert "actor" in params
    assert "reason" in params
    assert sig.return_annotation in (None, type(None), "None")


def test_resume_after_human_signature() -> None:
    sig = inspect.signature(resume_after_human)
    params = list(sig.parameters.keys())
    assert params[0] == "case_id"
    assert params[1] == "human_choice"
    assert params[2] == "human_reason"
    assert "actor" in params
    assert sig.return_annotation in (DraftReply, "DraftReply")


def test_explain_plainly_signature() -> None:
    sig = inspect.signature(explain_plainly)
    params = list(sig.parameters.keys())
    assert params[0] == "case_id"
    assert sig.return_annotation in (str, "str")
