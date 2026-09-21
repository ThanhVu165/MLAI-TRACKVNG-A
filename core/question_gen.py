from __future__ import annotations

import logging
from pathlib import Path

import yaml

from core.generate import build_evidence_reply
from core.types import (
    CaseInput,
    ChunkLabel,
    DraftReply,
    EscalationCard,
    EscalationType,
    EvidenceResult,
    Extraction,
    RequestItem,
)

logger = logging.getLogger(__name__)

REVIEW_SUGGESTION_LIMIT = 3
REVIEW_QUOTE_CHARS = 180


def _select_review_request(
    extraction: Extraction,
    escalation_type: EscalationType,
) -> RequestItem | None:
    if escalation_type == EscalationType.AUTHORITY_REQUIRED:
        authority_request = next(
            (
                request
                for request in extraction.requests
                if request.asks_exception or request.asks_appeal or request.asks_authority_decision
            ),
            None,
        )
        if authority_request:
            return authority_request
    return extraction.requests[0] if extraction.requests else None


def _build_partial_draft(
    extraction: Extraction,
    evidence_res: EvidenceResult,
    inp: CaseInput | None,
) -> DraftReply | None:
    has_information = any(request.is_informational for request in extraction.requests)
    has_authority = any(
        request.asks_exception or request.asks_appeal or request.asks_authority_decision
        for request in extraction.requests
    )
    if inp is None or not (len(extraction.requests) >= 2 and has_information and has_authority):
        return None
    chunks = [
        chunk
        for chunk in evidence_res.chunks
        if chunk.label == ChunkLabel.AUTO_ANSWERABLE and not chunk.conflict_flag
    ]
    return build_evidence_reply(chunks, inp, extraction.language) if chunks else None


def build_reviewer_suggestions(evidence_res: EvidenceResult) -> list[tuple[str, str]]:
    """Xếp hạng nguồn thật để người xét duyệt đối chiếu, không bịa khi retrieval rỗng."""
    suggestions: list[tuple[str, str]] = []
    seen_breadcrumbs: set[str] = set()
    for chunk in sorted(evidence_res.chunks, key=lambda item: item.score, reverse=True):
        if chunk.breadcrumb in seen_breadcrumbs:
            continue
        seen_breadcrumbs.add(chunk.breadcrumb)
        quote = " ".join(chunk.text.split())
        if len(quote) > REVIEW_QUOTE_CHARS:
            quote = f"{quote[: REVIEW_QUOTE_CHARS - 1].rsplit(' ', 1)[0]}…"
        suggestions.append((chunk.breadcrumb, f"Gợi ý đối chiếu: {quote}"))
        if len(suggestions) == REVIEW_SUGGESTION_LIMIT:
            break

    if suggestions:
        return suggestions
    return [
        (
            "Không tìm thấy tài liệu liên quan đang hiệu lực",
            "Hệ thống chưa có căn cứ để gợi ý câu trả lời; chuyên viên cần tra cứu nguồn chính thức trước khi phản hồi.",
        )
    ]


def build_review_options(
    extraction: Extraction,
    evidence_res: EvidenceResult,
    escalation_type: EscalationType,
) -> list[str]:
    """Gợi ý ba hành động cụ thể dựa trên dữ kiện thiếu và nguồn retrieval."""
    source = build_reviewer_suggestions(evidence_res)[0][0]
    has_source = not source.startswith("Không tìm thấy")
    if escalation_type == EscalationType.AUTHORITY_REQUIRED:
        first = f"Đồng ý sau khi đối chiếu {source}" if has_source else "Đồng ý và ghi rõ căn cứ"
        return [first, "Từ chối và nêu điều kiện chưa đạt", "Chuyển người có thẩm quyền cao hơn"]
    if escalation_type == EscalationType.OUT_OF_POLICY:
        first = (
            f"Đối chiếu {source} và tìm quy định tương đương"
            if has_source
            else "Tra cứu quy định tương đương từ nguồn chính thức"
        )
        return [first, "Chuyển đơn vị chuyên trách", "Phản hồi chưa có căn cứ áp dụng"]

    missing = extraction.missing_critical_facts[0] if extraction.missing_critical_facts else None
    first = f"Yêu cầu bổ sung {missing}" if missing else "Yêu cầu bổ sung dữ kiện bắt buộc"
    second = (
        f"Đối chiếu {source} sau khi đủ dữ kiện"
        if has_source
        else "Tra cứu nguồn chính thức sau khi đủ dữ kiện"
    )
    return [first, second, "Chuyển chuyên viên phụ trách xác minh"]


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
    primary_req = _select_review_request(extraction, escalation_type)

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
    basis = build_reviewer_suggestions(evidence_res)

    # -----------------------------------------------------------------------
    # Khối [1] & [4]: Tóm tắt và Câu hỏi đóng
    # -----------------------------------------------------------------------
    # Kiểm tra email đa ý định: 1 phần thường quy + 1 phần vượt quyền (Mục 8.2 spec)
    partial_draft = _build_partial_draft(extraction, evidence_res, inp)
    is_multi_intent = (
        len(extraction.requests) >= 2
        and any(request.is_informational for request in extraction.requests)
        and any(
            request.asks_exception or request.asks_appeal or request.asks_authority_decision
            for request in extraction.requests
        )
    )
    if partial_draft:
        summary = "Phần A đã soạn sẵn, phần B cần anh/chị quyết: sinh viên vừa hỏi thông tin vừa xin ngoại lệ."
    elif is_multi_intent:
        summary = "Email có nhiều ý; phần thông tin chưa đủ căn cứ, phần còn lại cần anh/chị quyết."
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
    elif escalation_type == EscalationType.OUT_OF_POLICY:
        question = (
            f"Chuyên viên hướng dẫn sinh viên xử lý nội dung {fact_anchor} theo phương án nào?"
        )
    else:
        question = f"Chuyên viên yêu cầu bổ sung thông tin gì cho {fact_anchor}?"
    options = build_review_options(extraction, evidence_res, escalation_type)

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
    guard_feedback: list[str] | None = None,
) -> EscalationCard:
    """R7b: Sinh thẻ EscalationCard 4 khối chuẩn Mục 8.6 spec (Task A-17)."""
    try:
        from infra.llm import call_json  # type: ignore[import-not-found]

        # Chuẩn bị context cho prompt
        facts_text = "\n".join(
            [*(f"- Ý định: {request.intent}" for request in extraction.requests)]
            + [*(f"- {key}: {value}" for key, value in extraction.critical_facts.items())]
            + [*(f"- Còn thiếu: {fact}" for fact in extraction.missing_critical_facts)]
        )
        reviewer_basis = build_reviewer_suggestions(evidence_res)
        basis_text = "\n".join(f"- {breadcrumb}: {quote}" for breadcrumb, quote in reviewer_basis)
        review_request = _select_review_request(extraction, escalation_type)
        review_intent = review_request.intent if review_request else "hồ sơ này"
        feedback_items = "\n- ".join(guard_feedback or [])
        feedback_text = (
            f"Các lỗi của thẻ trước phải sửa:\n- {feedback_items}\n" if feedback_items else ""
        )

        prompt = (
            f"Bạn là chuyên viên tiếp nhận DSA. Hãy tạo EscalationCard 4 khối cho case chuyển tiếp.\n"
            f"Loại escalation: {escalation_type.value}\n"
            f"Trọng tâm cần chuyên viên quyết định: {review_intent}\n"
            f"Dữ kiện đã có:\n{facts_text}\n"
            f"Căn cứ trích dẫn:\n{basis_text}\n\n"
            f"{feedback_text}"
            f"Yêu cầu định dạng JSON:\n"
            f"1. summary: Tóm tắt 1 câu, <= 30 từ.\n"
            f"2. facts: Danh sách 2-4 dữ kiện đã xác định.\n"
            f"3. basis: Tài liệu liên quan để người xét duyệt đối chiếu.\n"
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
            question = res.data.get("question", "")

            if "chuyên viên" not in summary.lower():
                summary = f"Cần chuyên viên xem xét: {summary}" if summary else "Yêu cầu cần chuyên viên xem xét và xử lý."

            return EscalationCard(
                summary=summary,
                facts=facts,
                basis=reviewer_basis,
                question=question,
                options=build_review_options(extraction, evidence_res, escalation_type),
                escalation_type=escalation_type,
                partial_draft=_build_partial_draft(extraction, evidence_res, inp),
            )
    except ImportError:
        logger.debug("infra.llm chưa cấu hình — sử dụng deterministic escalation card")
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM call sinh EscalationCard thất bại: %s", exc)

    return _build_deterministic_card(extraction, evidence_res, escalation_type, inp=inp)
