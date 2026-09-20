import pytest

from corpus.chunker import chunk_document

SAMPLES = [
    (
        "QĐ 3150/2026",
        "Điều 8. Đánh giá\n1. Sinh viên tự đánh giá.\na) Thang điểm 100.\nb) Công bố kết quả.",
        [
            "QĐ 3150/2026 · Điều 8",
            "QĐ 3150/2026 · Điều 8 · Khoản 1",
            "QĐ 3150/2026 · Điều 8 · Khoản 1 · Điểm a",
            "QĐ 3150/2026 · Điều 8 · Khoản 1 · Điểm b",
        ],
    ),
    (
        "QĐ 20/2026",
        "Điều 5. Rút học phần\nKhoản 1. Hạn chót là ngày 30/10.\nKhoản 2. Nộp đơn trực tuyến.",
        [
            "QĐ 20/2026 · Điều 5",
            "QĐ 20/2026 · Điều 5 · Khoản 1",
            "QĐ 20/2026 · Điều 5 · Khoản 2",
        ],
    ),
    (
        "HD 08/2026",
        "HƯỚNG DẪN\nĐiều 2. Phúc khảo\n1) Nộp trong 7 ngày.\na) Lệ phí 50.000 đồng.",
        [
            "HD 08/2026",
            "HD 08/2026 · Điều 2",
            "HD 08/2026 · Điều 2 · Khoản 1",
            "HD 08/2026 · Điều 2 · Khoản 1 · Điểm a",
        ],
    ),
]


@pytest.mark.parametrize(("title", "text", "expected_breadcrumbs"), SAMPLES)
def test_chunker_preserves_legal_units_and_breadcrumbs(
    title: str, text: str, expected_breadcrumbs: list[str]
) -> None:
    chunks = chunk_document(
        text,
        doc_id=title.replace(" ", "-"),
        doc_title=title,
        domain="conduct_score",
    )

    assert [chunk.breadcrumb for chunk in chunks] == expected_breadcrumbs
    assert all(chunk.text and chunk.label == "human_only" for chunk in chunks)
    assert [chunk.ord for chunk in chunks] == list(range(1, len(chunks) + 1))
    for marker in [line for line in text.splitlines() if line]:
        assert marker in " ".join(chunk.text for chunk in chunks)


def test_long_legal_unit_splits_without_losing_breadcrumb() -> None:
    body = " ".join(f"từ{i}" for i in range(1601))
    chunks = chunk_document(
        f"Điều 1. Nội dung\n1. {body}",
        doc_id="DOC-LONG",
        doc_title="QĐ dài",
        domain="conduct_score",
        max_tokens=800,
    )

    clause_chunks = [chunk for chunk in chunks if chunk.clause_no == "1"]
    assert len(clause_chunks) == 3
    assert all(chunk.token_count <= 800 for chunk in clause_chunks)
    assert all("QĐ dài · Điều 1 · Khoản 1 · Phần" in chunk.breadcrumb for chunk in clause_chunks)
