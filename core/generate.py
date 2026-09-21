from __future__ import annotations

import logging
import os
import re

from core.types import (
    CaseInput,
    DraftReply,
    EvidenceChunk,
    EvidenceResult,
    Extraction,
)

logger = logging.getLogger(__name__)

GENERATE_SYSTEM_PROMPT = """Bạn là trợ lý AI của Văn phòng Công tác Sinh viên (DSA).
Nhiệm vụ của bạn là soạn thảo email trả lời tự động cho sinh viên DỰA HOÀN TOÀN VÀO CĂN CỨ QUY ĐỊNH ĐÃ CUNG CẤP.

QUY TẮC BẮT BUỘC:
1. KHÔNG được suy đoán hoặc đưa ra thông tin không có trong tài liệu quy định.
2. MỌI câu khẳng định nội dung, thông tin, mốc thời gian, lệ phí, thủ tục BẮT BUỘC phải kèm theo mã chunk tương ứng trong dấu ngoặc vuông, ví dụ [chunk_id].
3. KHÔNG được cam kết thay mặt DSA, không hứa hẹn phê duyệt ngoại lệ.
4. KHÔNG nhắc tới hoặc khẳng định thông tin hồ sơ cá nhân của sinh viên.
5. Phản hồi đúng ngôn ngữ của sinh viên (tiếng Việt hoặc tiếng Anh).
6. Định dạng đầu ra là JSON hợp lệ:
{
  "subject": "Re: <tiêu đề email>",
  "body": "<nội dung thư trả lời sinh viên kèm trích dẫn [chunk_id]>",
  "citations": ["chunk_id_1", "chunk_id_2"]
}
"""


def _replay_mode() -> bool:
    return os.getenv("LLM_MODE", "replay").casefold() == "replay"


def _failed_reply(inp: CaseInput, error: str) -> DraftReply:
    return DraftReply(
        subject=f"Re: {inp.subject}",
        body="",
        citations=[],
        grounded=False,
        guard_failures=[f"llm_generation_failed:{error}"],
    )


def build_evidence_reply(
    evidence_chunks: list[EvidenceChunk],
    inp: CaseInput,
    language: str = "vi",
) -> DraftReply:
    """Bộ sinh câu trả lời mẫu rule-based chuẩn hóa khi chạy offline hoặc thiếu infra.llm."""
    if not evidence_chunks:
        return DraftReply(
            subject=f"Re: {inp.subject}",
            body="Chào em,\n\nHiện tại hệ thống chưa tìm thấy quy định đang hiệu lực phù hợp với câu hỏi của em.\n\nTrân trọng,\nVăn phòng Công tác Sinh viên (DSA)",
            citations=[],
            grounded=False,
            guard_failures=["no_evidence_available"],
        )

    citations = [c.chunk_id for c in evidence_chunks]
    citation_tags = " ".join(f"[{cid}]" for cid in citations)

    # Tổng hợp nội dung chính từ các chunks, gắn citation vào từng câu
    evidence_summaries: list[str] = []
    for c in evidence_chunks:
        clean_text = c.text.strip()
        raw_sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text) if s.strip()]
        cited_sents: list[str] = []
        for s in raw_sents:
            if s.endswith("."):
                cited_sents.append(f"{s[:-1]} [{c.chunk_id}].")
            else:
                cited_sents.append(f"{s} [{c.chunk_id}]")
        cited_text = " ".join(cited_sents)
        evidence_summaries.append(f"Theo {c.breadcrumb}: {cited_text}")

    joined_content = "\n\n".join(evidence_summaries)

    if language == "en":
        subject = f"Re: {inp.subject}"
        body = (
            "Dear student,\n\n"
            "Thank you for contacting the Department of Student Affairs (DSA). "
            f"Based on the university regulations {citation_tags}, we would like to inform you as follows:\n\n"
            f"{joined_content}\n\n"
            "Sincerely,\n"
            "Department of Student Affairs (DSA)"
        )
    else:
        subject = f"Re: {inp.subject}"
        body = (
            "Chào em,\n\n"
            "Cảm ơn em đã liên hệ Văn phòng Công tác Sinh viên (DSA). "
            f"Căn cứ theo các quy định hiện hành của Nhà trường {citation_tags}, DSA xin thông tin đến em như sau:\n\n"
            f"{joined_content}\n\n"
            "Chúc em học tập tốt.\n\n"
            "Trân trọng,\n"
            "Văn phòng Công tác Sinh viên (DSA)"
        )

    return DraftReply(
        subject=subject,
        body=body,
        citations=citations,
        grounded=True,
        guard_failures=[],
    )


def generate_reply(
    evidence_res: EvidenceResult,
    inp: CaseInput,
    extraction: Extraction,
    case_id: str = "",
) -> DraftReply:
    """R7a: Sinh câu trả lời tự động (Task A-15).

    Chỉ đưa evidence đã lọc vào prompt, tuyệt đối không đưa body gốc thô của sinh viên.
    Yêu cầu gắn chunk_id cho từng câu/khối khẳng định.
    Trả lời đúng ngôn ngữ.
    """
    lang = extraction.language if extraction.language in ("vi", "en") else "vi"

    # Lọc danh sách chunks dùng để trả lời
    answerable_chunks = [c for c in evidence_res.chunks]
    citations = [c.chunk_id for c in answerable_chunks]

    try:
        from infra.llm import call_json  # type: ignore[import-not-found]
    except ImportError as exc:
        if _replay_mode():
            return build_evidence_reply(answerable_chunks, inp, language=lang)
        return _failed_reply(inp, f"Không tải được infra.llm: {exc}")

    try:
        # Chuẩn bị dữ liệu evidence đã lọc (không có body thô của email)
        evidence_text = "\n\n".join(
            f"--- CHUNK ID: {c.chunk_id} ---\nNguồn: {c.breadcrumb}\nNội dung: {c.text}"
            for c in answerable_chunks
        )

        user_prompt = (
            f"Ngôn ngữ: {lang}\n"
            f"Tiêu đề email nhận: {inp.subject}\n"
            f"Căn cứ pháp lý có thẩm quyền:\n{evidence_text}\n\n"
            f"Hãy soạn thảo email trả lời theo đúng các quy tắc bắt buộc."
        )

        schema = {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["subject", "body", "citations"],
        }

        res = call_json(
            prompt=f"{GENERATE_SYSTEM_PROMPT}\n\n{user_prompt}",
            schema=schema,
            step="R7a_generate",
            case_id=case_id,
        )

        if res.ok and res.data:
            subj = res.data.get("subject", f"Re: {inp.subject}")
            body = res.data.get("body", "")
            raw_cits = res.data.get("citations", citations)
            # Chuẩn hóa citations
            valid_cits = [str(c) for c in raw_cits if str(c) in citations] or citations

            return DraftReply(
                subject=subj,
                body=body,
                citations=valid_cits,
                grounded=True,
                guard_failures=[],
            )
        if res.error and _replay_mode() and "No such file or directory" in res.error:
            return build_evidence_reply(answerable_chunks, inp, language=lang)
        return _failed_reply(inp, res.error or "LLM generation failed")

    except Exception as exc:  # noqa: BLE001
        logger.error("LLM call soạn thảo email thất bại: %s", exc)
        return _failed_reply(inp, str(exc))
