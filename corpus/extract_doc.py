from __future__ import annotations

import io
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pdfplumber
from docx import Document

LEGAL_MARKER = re.compile(
    r"^(?:Điều\s+\d+[A-Za-z]?\s*[.:]?|Khoản\s+\d+\s*[.:]?|\d+\s*[.)]|[a-zđ]\s*[)])",
    re.IGNORECASE,
)


def _clean_line(line: str) -> str:
    return re.sub(r"[ \t]+", " ", unicodedata.normalize("NFC", line)).strip()


def remove_repeated_marginals(pages: list[list[str]]) -> list[list[str]]:
    """Remove repeated first/last two lines while leaving numbered body lines intact."""
    if len(pages) < 2:
        return pages
    candidates = Counter(
        line
        for page in pages
        for line in [*page[:2], *page[-2:]]
        if line and not LEGAL_MARKER.match(line)
    )
    threshold = math.floor(len(pages) / 2) + 1
    repeated = {line for line, count in candidates.items() if count >= threshold}
    return [
        [
            line
            for index, line in enumerate(page)
            if line not in repeated or 2 <= index < len(page) - 2
        ]
        for page in pages
    ]


def normalize_pages(page_texts: list[str]) -> str:
    pages = [
        [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
        for text in page_texts
    ]
    lines = [line for page in remove_repeated_marginals(pages) for line in page]
    merged: list[str] = []
    for line in lines:
        if (
            not merged
            or LEGAL_MARKER.match(line)
            or LEGAL_MARKER.match(merged[-1])
            or merged[-1].endswith((".", ":", ";", "?", "!"))
        ):
            merged.append(line)
        else:
            merged[-1] += " " + line
    return unicodedata.normalize("NFC", "\n".join(merged)).strip()


def extract_pdf(payload: bytes) -> str:
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        return normalize_pages([page.extract_text() or "" for page in pdf.pages])


def extract_docx(payload: bytes) -> str:
    document = Document(io.BytesIO(payload))
    return normalize_pages(["\n".join(paragraph.text for paragraph in document.paragraphs)])


def extract_document(payload: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        return extract_pdf(payload)
    if suffix == ".docx":
        return extract_docx(payload)
    if suffix == ".txt":
        return normalize_pages([payload.decode("utf-8")])
    raise ValueError("Chỉ hỗ trợ PDF, DOCX hoặc văn bản thuần")
