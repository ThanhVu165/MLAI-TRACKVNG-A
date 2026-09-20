from pathlib import Path


def test_admin_page_has_required_four_tabs_and_vietnamese_actions() -> None:
    page = Path("pages/3_Quan_tri_quy_dinh.py").read_text(encoding="utf-8")

    for label in ["Nạp tài liệu", "Chờ duyệt", "Đang hiệu lực", "Lịch sử"]:
        assert label in page
    for action in ["Nạp tệp", "Lưu nhãn", "Duyệt", "Kích hoạt tài liệu", "Rollback tài liệu"]:
        assert action in page
