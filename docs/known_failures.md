# Known Failures & Architectural Debt (Nhật ký lỗi & Thiết kế kỹ thuật)

Tài liệu này ghi nhận các giới hạn kiến trúc hiện tại của hệ thống và định hướng đồng bộ khi tích hợp các module hạ tầng (`infra.db`, `infra.llm`, `corpus.api`).

---

## 1. Trạng thái Case: Nguồn sự thật đơn nhất (Single Source of Truth)
- **Vị trí hiện tại:** `_DISPATCH_REGISTRY` trong `core/dispatch.py` (dict trong bộ nhớ RAM) và `_CASES_STORE` trong `core/pipeline.py` (dict trong bộ nhớ RAM).
- **Rủi ro:** Khi chạy nhiều worker process hoặc restart hệ thống, dữ liệu trong RAM không tồn tại qua các phiên làm việc và dễ bị lệch giữa các module.
- **Giải pháp khi có `infra.db`:**
  - Chuyển toàn bộ việc đọc/ghi trạng thái case (`PENDING_SEND`, `SENT`, `AWAITING_HUMAN`, `CANCELLED`,...) về bảng `cases` trong database.
  - Cả `core/dispatch.py`, `core/controls.py`, `core/pipeline.py` và `core/resume.py` đều truy vấn và cập nhật cùng một hàng trong cơ sở dữ liệu.

## 2. Tên action audit cũ từ Runtime [đã xử lý]
- **Hiện tượng:** Runtime gửi năm tên action không nằm trong danh mục đóng, làm `infra.audit` từ chối ghi event.
- **Điều kiện tái hiện:** Xử lý xong case hoặc dùng Pause, Resume, Override, Rerun.
- **Xử lý:** Adapter cục bộ trong `infra.audit` đổi tên cũ sang action hợp contract; danh mục `ACTIONS` không thay đổi sau feature freeze.
