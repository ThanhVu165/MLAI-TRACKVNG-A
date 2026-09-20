from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

ARTICLE_RE = re.compile(r"^Điều\s+(\d+[A-Za-z]?)\s*[.:]?", re.IGNORECASE)
CLAUSE_RE = re.compile(r"^(?:Khoản\s+)?(\d+)\s*[.)]", re.IGNORECASE)
POINT_RE = re.compile(r"^([a-zđ])\s*[)]", re.IGNORECASE)


@dataclass(frozen=True)
class LegalChunk:
    chunk_id: str
    doc_id: str
    article_no: str | None
    clause_no: str | None
    breadcrumb: str
    text: str
    domain: str
    label: str
    conflict_flag: int
    conflict_with: str | None
    ord: int
    token_count: int

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _Unit:
    article: str | None
    clause: str | None
    point: str | None
    lines: list[str]


def _breadcrumb(
    doc_title: str,
    article: str | None,
    clause: str | None,
    point: str | None,
) -> str:
    parts = [doc_title]
    if article:
        parts.append(f"Điều {article}")
    if clause:
        parts.append(f"Khoản {clause}")
    if point:
        parts.append(f"Điểm {point}")
    return " · ".join(parts)


def _legal_units(text: str) -> list[_Unit]:
    units: list[_Unit] = []
    article: str | None = None
    clause: str | None = None
    point: str | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        if lines:
            units.append(_Unit(article, clause, point, lines))
            lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        article_match = ARTICLE_RE.match(line)
        clause_match = CLAUSE_RE.match(line)
        point_match = POINT_RE.match(line)
        if article_match:
            flush()
            article, clause, point = article_match.group(1), None, None
        elif clause_match:
            flush()
            clause, point = clause_match.group(1), None
        elif point_match:
            flush()
            point = point_match.group(1).lower()
        lines.append(line)
    flush()
    return units


def chunk_document(
    text: str,
    *,
    doc_id: str,
    doc_title: str,
    domain: str,
    max_tokens: int = 800,
) -> list[LegalChunk]:
    if max_tokens <= 0:
        raise ValueError("max_tokens phải lớn hơn 0")
    if not text.strip() or not doc_id or not doc_title or not domain:
        raise ValueError("Văn bản, mã, tiêu đề và domain là bắt buộc")

    chunks: list[LegalChunk] = []
    for unit in _legal_units(text):
        # ponytail: whitespace tokens approximate model tokens; use the model tokenizer if context limits bind.
        tokens = "\n".join(unit.lines).split()
        parts = [tokens[index : index + max_tokens] for index in range(0, len(tokens), max_tokens)]
        base_breadcrumb = _breadcrumb(doc_title, unit.article, unit.clause, unit.point)
        for part_index, part in enumerate(parts, start=1):
            ord_no = len(chunks) + 1
            breadcrumb = (
                f"{base_breadcrumb} · Phần {part_index}" if len(parts) > 1 else base_breadcrumb
            )
            body = " ".join(part)
            digest = hashlib.sha256(f"{doc_id}:{ord_no}:{body}".encode()).hexdigest()[:12]
            clause_no = unit.clause
            if unit.point:
                clause_no = f"{clause_no}.{unit.point}" if clause_no else unit.point
            chunks.append(
                LegalChunk(
                    chunk_id=f"chk_{digest}",
                    doc_id=doc_id,
                    article_no=unit.article,
                    clause_no=clause_no,
                    breadcrumb=breadcrumb,
                    text=body,
                    domain=domain,
                    label="human_only",
                    conflict_flag=0,
                    conflict_with=None,
                    ord=ord_no,
                    token_count=len(part),
                )
            )
    return chunks
