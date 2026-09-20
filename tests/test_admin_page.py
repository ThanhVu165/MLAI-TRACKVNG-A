import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest

from infra.db import MIGRATION_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return conn


def test_admin_page_has_required_four_tabs_and_vietnamese_actions() -> None:
    page = Path("pages/3_Quan_tri_quy_dinh.py").read_text(encoding="utf-8")

    for label in ["Nạp tài liệu", "Chờ duyệt", "Đang hiệu lực", "Lịch sử"]:
        assert label in page
    for action in ["Nạp tệp", "Lưu nhãn", "Duyệt", "Kích hoạt tài liệu", "Rollback tài liệu"]:
        assert action in page


def test_admin_page_renders_seeded_corpus_without_loading_embedding_model() -> None:
    app = AppTest.from_file(Path.cwd() / "pages" / "3_Quan_tri_quy_dinh.py")
    app.session_state["db_connection"] = _db()

    app.run(timeout=10)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Nạp tài liệu",
        "Chờ duyệt",
        "Đang hiệu lực",
        "Lịch sử",
    ]
    assert app.metric[0].label == "Corpus version"
    assert any(
        info.value == "Chưa có tài liệu chờ duyệt. Hãy nạp tài liệu ở tab Nạp tài liệu."
        for info in app.info
    )
