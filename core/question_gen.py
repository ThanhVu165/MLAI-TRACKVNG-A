from __future__ import annotations

import logging
from pathlib import Path

import yaml

from core.types import (
    CaseInput,
    DraftReply,
    EscalationCard,
    EscalationType,
    EvidenceResult,
    Extraction,
)

logger = logging.getLogger(__name__)


def load_fallback_template(
    escalation_type: EscalationType,
    fallback_path: str = "policies/fallback_questions.yaml",
) -> EscalationCard:
    """Tải template dự phòng chuẩn 4 khối từ fallback_questions.yaml."""
    path = Path(fallback_path)
    if not path.is_file():
        # Dự phòng cực hạn nếu file bị thiếu
        return EscalationCard(
            summary="Hồ sơ cần chuyên viên xem xét và ra quyết định.",
            facts=["Yêu cầu được tiếp nhận từ sinh viên."],
            basis=[("Quy chế Nhà trường", "Cần chuyên viên phụ trách đối chiếu quy định.")],
            question="Chuyên viên có đồng ý phê duyệt yêu cầu này không?",
            options=["Đồng ý phê duyệt", "Từ chối yêu cầu"],
            escalation_type=escalation_type,
            partial_draft=None,
        )

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tpls = data.get("fallback_templates", {})
    type_key = escalation_type.value if hasattr(escalation_type, "value") else str(escalation_type)
    t = tpls.get(type_key, {})

    summary = t.get("summary", "Yêu cầu cần chuyên viên xem xét và xử lý.")
    facts = t.get("facts", ["Yêu cầu chưa đủ dữ kiện để xử lý tự động."])
    raw_basis = t.get("basis", [])
    basis = [(b.get("breadcrumb", "Nguồn quy định"), b.get("quote", "")) for b in raw_basis]
    question = t.get("question", "Chuyên viên xử lý trường hợp này như thế nào?")
    options = t.get("options", ["Đồng ý phê duyệt", "Từ chối yêu cầu"])

    return EscalationCard(
        summary=summary,
        facts=facts,
        basis=basis,
        question=question,
        options=options,
        escalation_type=escalation_type,
        partial_draft=None,
    )


def _build_deterministic_card(
    extraction: Extraction,
    evidence_res: EvidenceResult,
    escalation_type: EscalationType,
    inp: CaseInput | None = None,
) -> EscalationCard:
    """Xây dựng EscalationCard 4 khối theo quy tắc chuẩn mực khi chạy offline / stub."""
    # -----------------------------------------------------------------------
    # Khối [2]: Dữ kiện (Fact)
    # -----------------------------------------------------------------------
    facts: list[str] = []
    primary_req = extraction.requests[0] if extraction.requests else None

    if primary_req:
        facts.append(f"Ý định sinh viên: {primary_req.intent}")
        if primary_req.asks_exception:
            facts.append("Yêu cầu: Xin áp dụng ngoại lệ ngoài thời hạn quy định thông thường")
        if primary_req.asks_appeal:
            facts.append("Yêu cầu: Đề nghị chấm lại hoặc khiếu nại kết quả bài thi cá nhân")
        if primary_req.asks_authority_decision:
            facts.append("Yêu cầu: Cần người có thẩm quyền phê duyệt trực tiếp")

    for k, v in extraction.critical_facts.items():
        facts.append(f"Dữ kiện {k}: {v}")

    for mf in extraction.missing_critical_facts:
        facts.append(f"Dữ kiện còn thiếu: {mf}")

    if not facts:
        facts.append("Sinh viên gửi yêu cầu thông tin qua hệ thống tiếp nhận trực tuyến.")

    # -----------------------------------------------------------------------
    # Khối [3]: Căn cứ (Basis)
    # -----------------------------------------------------------------------
    basis: list[tuple[str, str]] = []
    for c in evidence_res.chunks:
        basis.append((c.breadcrumb, c.text[:120].strip() + "..."))

    if not basis:
        if escalation_type == EscalationType.OUT_OF_POLICY:
            basis.append(
                (
                    "Phạm vi phục vụ DSA",
                    "không tìm thấy quy định đang hiệu lực cho nội dung yêu cầu",
                )
            )
        else:
            basis.append(
                ("Quy chế Nhà trường", "Hồ sơ cần đối chiếu với điều khoản áp dụng thực tế.")
            )

    # -----------------------------------------------------------------------
    # Khối [1] & [4]: Tóm tắt và Câu hỏi đóng
    # -----------------------------------------------------------------------
    # Kiểm tra email đa ý định: 1 phần thường quy + 1 phần vượt quyền (Mục 8.2 spec)
    has_info = any(r.is_informational for r in extraction.requests)
    has_auth = any(
        r.asks_exception or r.asks_appeal or r.asks_authority_decision for r in extraction.requests
    )
    is_multi_intent = len(extraction.requests) >= 2 and has_info and has_auth

    partial_draft: DraftReply | None = None
    if is_multi_intent:
        summary = "Phần A đã soạn sẵn, phần B cần anh/chị quyết: sinh viên vừa hỏi thông tin vừa xin ngoại lệ."
        if inp:
            partial_draft = DraftReply(
                subject=f"Re: {inp.subject}",
                body="Chào em,\n\nVề nội dung hỏi thông tin thời hạn, DSA xin thông tin đến em theo quy định.\n\nTrân trọng,\nDSA",
                citations=[c.chunk_id for c in evidence_res.chunks],
                grounded=True,
                guard_failures=[],
            )
    elif escalation_type == EscalationType.AUTHORITY_REQUIRED:
        summary = "Yêu cầu cần chuyên viên xem xét và ra quyết định phê duyệt."
    elif escalation_type == EscalationType.OUT_OF_POLICY:
        summary = "Yêu cầu nằm ngoài phạm vi quy chế thường quy được hỗ trợ tự động."
    else:
        summary = "Yêu cầu chưa đủ dữ kiện thực tế để hệ thống áp dụng quy định."

    # Tạo câu hỏi đóng chứa ít nhất 1 dữ kiện cụ thể từ Khối [2]
    fact_anchor = extraction.critical_facts.get("cohort") or (
        primary_req.intent if primary_req else "hồ sơ này"
    )
    if escalation_type == EscalationType.AUTHORITY_REQUIRED:
        question = f"Chuyên viên có đồng ý phê duyệt yêu cầu đối với {fact_anchor} không?"
        options = ["Đồng ý phê duyệt", "Từ chối yêu cầu", "Chuyển Trưởng phòng xem xét"]
    elif escalation_type == EscalationType.OUT_OF_POLICY:
        question = (
            f"Chuyên viên hướng dẫn sinh viên xử lý nội dung {fact_anchor} theo phương án nào?"
        )
        options = [
            "Chuyển tiếp đơn vị chuyên trách",
            "Hướng dẫn nộp đơn trực tiếp",
            "Từ chối tiếp nhận",
        ]
    else:
        question = f"Chuyên viên yêu cầu bổ sung thông tin gì cho {fact_anchor}?"
        options = [
            "Yêu cầu cung cấp minh chứng cụ thể",
            "Hướng dẫn sinh viên tra cứu lại",
            "Từ chối vì thiếu dữ kiện",
        ]

    return EscalationCard(
        summary=summary,
        facts=facts,
        basis=basis,
        question=question,
        options=options,
        escalation_type=escalation_type,
        partial_draft=partial_draft,
    )


def generate_escalation_card(
    extraction: Extraction,
    evidence_res: EvidenceResult,
    escalation_type: EscalationType,
    case_id: str = "",
    inp: CaseInput | None = None,
) -> EscalationCard:
    """R7b: Sinh thẻ EscalationCard 4 khối chuẩn Mục 8.6 spec (Task A-17)."""
    try:
        from infra.llm import call_json  # type: ignore[import-not-found]

        # Chuẩn bị context cho prompt
        facts_text = "\n".join(f"- {k}: {v}" for k, v in extraction.critical_facts.items())
        basis_text = "\n".join(f"- {c.breadcrumb}: {c.text[:100]}" for c in evidence_res.chunks)

        prompt = (
            f"Bạn là chuyên viên tiếp nhận DSA. Hãy tạo EscalationCard 4 khối cho case chuyển tiếp.\n"
            f"Loại escalation: {escalation_type.value}\n"
            f"Dữ kiện đã có:\n{facts_text}\n"
            f"Căn cứ trích dẫn:\n{basis_text}\n\n"
            f"Yêu cầu định dạng JSON:\n"
            f"1. summary: Tóm tắt 1 câu, <= 30 từ.\n"
            f"2. facts: Danh sách 2-4 dữ kiện đã xác định.\n"
            f"3. basis: Danh sách cặp [breadcrumb, trích dẫn ngắn].\n"
            f"4. question: MỘT câu hỏi đóng kết thúc bằng '?', chứa dữ kiện cụ thể từ facts, 8-45 từ.\n"
            f"5. options: 2-4 phương án lựa chọn sẵn.\n"
        )

        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "facts": {"type": "array", "items": {"type": "string"}},
                "basis": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "facts", "basis", "question", "options"],
        }

        res = call_json(prompt=prompt, schema=schema, step="R7b_question_gen", case_id=case_id)
        if res.ok and res.data:
            summary = res.data.get("summary", "")
            facts = res.data.get("facts", [])
            raw_basis = res.data.get("basis", [])
            basis = [(b[0], b[1]) if len(b) >= 2 else (b[0], "") for b in raw_basis if b]
            question = res.data.get("question", "")
            options = res.data.get("options", [])

            return EscalationCard(
                summary=summary,
                facts=facts,
                basis=basis,
                question=question,
                options=options,
                escalation_type=escalation_type,
                partial_draft=None,
            )
    except ImportError:
        logger.debug("infra.llm chưa cấu hình — sử dụng deterministic escalation card")
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM call sinh EscalationCard thất bại: %s", exc)

    return _build_deterministic_card(extraction, evidence_res, escalation_type, inp=inp)
