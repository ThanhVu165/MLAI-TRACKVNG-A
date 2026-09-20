# RUNBOOK — Hướng dẫn cài đặt và vận hành Escalation Referee

> Tài liệu này liệt kê toàn bộ các lệnh thực tế từ khi clone kho mã nguồn sạch cho đến khi toàn bộ hệ thống khởi chạy và kiểm thử thành công.

---

## 1. Yêu cầu môi trường

- **Hệ điều hành:** Linux, macOS hoặc Windows (PowerShell / Command Prompt).
- **Python:** Phiên bản `3.11` (hỗ trợ tương thích `3.11+` đến `3.14`).
- **Git:** Để quản lý mã nguồn và lịch sử commit.

---

## 2. Các bước cài đặt từ đầu (Clean Setup)

### Bước 1: Clone kho lưu trữ
```bash
git clone https://github.com/ThanhVu165/MLAI-TRACKVNG-A.git
cd MLAI-TRACKVNG-A
```

### Bước 2: Tạo và kích hoạt môi trường ảo (Virtual Environment)
- **Trên Linux/macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- **Trên Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```

### Bước 3: Cài đặt các gói phụ thuộc
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Bước 4: Thiết lập biến môi trường
Tạo file `.env` từ file mẫu `.env.example`:
- **Linux/macOS:**
  ```bash
  cp .env.example .env
  ```
- **Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```

*Nội dung tối thiểu của `.env`:*
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
LLM_MODE=replay
DEFAULT_MODEL=gemini-2.5-flash
```
> **Lưu ý:** Chế độ `LLM_MODE=replay` (mặc định cho CI/offline) sử dụng cassette trong `tests/cassettes/` mà không tốn quota hay yêu cầu kết nối mạng. Khi chạy với AI Gemini trực tiếp, chuyển sang `LLM_MODE=live`.

### Bước 5: Khởi tạo Cơ sở dữ liệu và nạp Corpus mẫu
Hệ thống tự động chạy migration SQLite WAL mode và seed 6 tài liệu chuẩn khi khởi động. Bạn cũng có thể kích hoạt thủ công bằng lệnh sau:
```bash
python -c "from infra.db import get_connection; from corpus.seed import seed_if_empty; conn = get_connection(); seed_if_empty(conn)"
```

---

## 3. Khởi chạy Ứng dụng Giao diện (Streamlit UI)

Chạy lệnh Streamlit để mở giao diện quản trị và điều phối:
```bash
python -m streamlit run streamlit_app.py
```
Ứng dụng sẽ tự động mở tại địa chỉ: `http://localhost:8501`.

Các trang chính trong hệ thống:
1. `Trang chủ`: Tiếp nhận dán email tức thì, sơ đồ Slide 2, banner mô phỏng.
2. `1. Xử lý email`: Hộp thư mô phỏng 12 email, pipeline R0–R13, đồng hồ đếm ngược 60 giây và nút hủy gửi.
3. `2. Hàng chờ duyệt`: Thẻ escalation 4 khối, câu hỏi chuyển tiếp đóng có sẵn phương án chọn, duyệt và gửi.
4. `3. Quản trị quy định`: Quản lý vòng đời tài liệu, gán nhãn thẩm quyền chunk, kiểm tra xung đột văn bản.
5. `4. Nhật ký kiểm toán`: Audit log chi tiết truy vết mọi chuyển đổi trạng thái (+07:00).
6. `5. Verify`: 3 nút kiểm thử harness chuẩn xác (Verify 4, Escalation 5, Full 15), xuất JSON, ma trận nhầm lẫn.
7. `6. Đo lường`: Telemetry 8 chỉ số hiệu năng và rủi ro thời gian thực.

---

## 4. Chạy Bộ Kiểm chuẩn & Cổng Nghiệm thu (Quality Gate)

### Chạy Linting (Ruff):
```bash
python -m ruff check .
```

### Chạy toàn bộ Unit & Integration Test (Pytest):
```bash
python -m pytest tests/
```

### Chạy các bộ kiểm thử Verify Harness từ dòng lệnh:
1. **Bộ Verify chuẩn 4 cases (Tiêu chí 2 - 12đ):**
   ```bash
   python -m verify.harness --set verify4
   ```
2. **Bộ Escalation Check 5 cases (Tiêu chí 7 - bài 90 giây):**
   ```bash
   python -m verify.harness --set escalation5
   ```
3. **Bộ Đầy đủ 15 cases (Dữ liệu nền Sprint 2):**
   ```bash
   python -m verify.harness --set full15
   ```

---

## 5. Xử lý sự cố thường gặp (Troubleshooting)

### 1. Lỗi `ModuleNotFoundError` khi chạy script riêng lẻ
- **Nguyên nhân:** Python không nhận diện thư mục gốc của project trong `sys.path`.
- **Khắc phục:** Luôn chạy lệnh dưới dạng module `python -m <module_name>` (ví dụ: `python -m verify.harness --set verify4`) hoặc thêm thư mục hiện tại vào `PYTHONPATH`.

### 2. Lỗi `database is locked` trên SQLite
- **Nguyên nhân:** Hai tiến trình ghi SQLite đồng thời khi chưa bật chế độ WAL.
- **Khắc phục:** `infra/db.py` đã mặc định bật `PRAGMA journal_mode=WAL;` và `PRAGMA busy_timeout=5000;`. Đảm bảo các hàm gọi truy vấn đều dùng context manager `with get_connection() as conn:`.

### 3. Lỗi UnicodeEncodeError trên terminal Windows tiếng Việt
- **Nguyên nhân:** Terminal Windows sử dụng bảng mã mặc định `cp1252` thay vì `utf-8`.
- **Khắc phục:** Thiết lập biến môi trường trước khi chạy trên PowerShell:
  ```powershell
  $env:PYTHONIOENCODING = "utf-8"
  ```

### 4. Không gọi được Gemini API khi chạy Live
- **Nguyên nhân:** Chưa cấu hình `GEMINI_API_KEY` trong file `.env` hoặc mạng bị ngắt.
- **Khắc phục:** Hệ thống được thiết kế fail-safe: khi API lỗi hoặc mất kết nối mạng, tác tử sẽ tự động chuyển tiếp case sang `ESCALATE / FACT_UNRESOLVED` (luật P04) và ghi nhận audit `CASE_ERROR`, tuyệt đối không fail-open hay làm sập hệ thống. Để chạy độc lập không cần mạng, giữ `LLM_MODE=replay`.
