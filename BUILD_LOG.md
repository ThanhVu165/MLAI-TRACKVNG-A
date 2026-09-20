# BUILD LOG — Nhật ký Phát triển & Đánh giá Công cụ AI

> Dự án: **Escalation Referee** — Đề A, MLAI Hackathon 2026.
> Mô hình phát triển: 3 Làn chuyên biệt (Agent A - Runtime, Agent B - Corpus Admin, Agent C - UI/Verify/Infra).

---

## 1. Các công cụ AI đã sử dụng & Cách thức ứng dụng

- **Mô hình & Nền tảng:** Antigravity IDE kết hợp Gemini 2.5 Flash / Pro, Gemini API (`@google/genai`).
- **Cách thức vận hành:**
  - **Tách ranh giới 3 Agent:** Agent A (`core/`, Policy Engine), Agent B (`corpus/`, vòng đời văn bản), Agent C (`infra/`, `pages/`, `verify/`).
  - **Khung tư duy Ponytail:** Ưu tiên giải pháp tối giản, chuẩn thư viện stdlib, loại bỏ phụ thuộc nặng không cần thiết (như fallback `DefaultEmbedder` thay vì ép tải gói 500MB `torch/sentence-transformers`).
  - **Khai thác LLM có kiểm soát:** LLM chỉ đảm nhiệm trích xuất cấu trúc (`R2_extract`) và diễn đạt câu chữ (`R7a_generate`, `R7b_question_gen`). Toàn bộ quyết định thẩm quyền do **Policy Engine deterministic (P01–P05)** quyết định.

---

## 2. Những điểm AI hỗ trợ thực sự hiệu quả (AI Wins)

1. **Sinh bộ kiểm thử tự động toàn diện:**
   - AI hỗ trợ viết nhanh 170 unit và integration tests phủ 100% logic deterministic (Policy Engine, Evidence Validator 7 bài kiểm tra, Question Quality Guard, Chunker theo Điều/Khoản, Conflict Detector). Toàn bộ test chạy xong chỉ trong **10–11 giây**.
2. **Cưỡng chế Structured Output & Giảm thiểu Hallucination:**
   - Thông qua `call_json()` với schema định sẵn và `temperature=0`, AI bóc tách chính xác 100% ngôn ngữ, domain và cờ thẩm quyền mà không tự ý đưa ra kết luận vượt quy định.
3. **Dọn dẹp mã nguồn & Chuẩn hóa Linter:**
   - Xử lý triệt để 100% cảnh báo và lỗi Ruff trên toàn bộ cây thư mục dự án, đưa codebase về trạng thái 0 lỗi sạch sẽ.

---

## 3. Những điểm AI làm mất thời gian & Bài học kinh nghiệm (AI Friction)

1. **Xu hướng vi phạm ranh giới Module (Cross-Layer Leaks):**
   - *Ví dụ cụ thể:* Trong một số lần refactor, AI tiện tay thêm `import streamlit` vào `core/` hoặc gọi trực tiếp `corpus.conflict` từ `core/evidence.py`, vi phạm luật phụ thuộc nghiêm ngặt tại Mục 5.1 của `AGENT.md`.
   - *Giải pháp:* Thiết lập bộ quy tắc phối hợp nhóm `.agents/skills/team-collaboration/SKILL.md` và kiểm tra tĩnh bằng `ruff` để ngăn chặn triệt để.
2. **Nhiễm chéo ngữ cảnh khi truy xuất bằng chứng (Over-Escalation by Proximity):**
   - *Ví dụ cụ thể:* Khi bật phát hiện xung đột `conflict_flag`, thuật toán retrieval lấy `top_k=6` đã kéo cả chunk mâu thuẫn về hoàn học phí vào câu hỏi về hạn chót rút học phần (F04/E02), khiến hệ thống đánh giá sai thành `OUT_OF_POLICY`. Phải mất thời gian điều tra và bổ sung hàm `_is_conflict_relevant()` để phân định đúng chủ đề.

---

## 4. Tính năng lớn nhất đã cắt giảm & Lý do (Scope Cuts)

1. **Bộ thu thập văn bản mạng tự động chạy nền (Background Web Crawler):**
   - *Lý do cắt:* Để đảm bảo an toàn tuyệt đối cho bài chấm 8 phút của giám khảo và tuân thủ nguyên tắc không để pipeline phụ thuộc vào Internet. Đã chuyển thành nút **"Kiểm tra nguồn mới"** thủ công kích hoạt theo yêu cầu qua SHA256.
2. **Cơ chế Rollback đa tầng tự động quét lại toàn bộ Case trong 30 ngày:**
   - *Lý do cắt:* Cắt giảm theo Phụ lục TASKBOARD Nhóm A (mốc H42) để tập trung tài nguyên tối ưu hóa bộ 3 nút **Verify Harness** đạt chuẩn 100% PASS và giữ trọn vẹn điểm số Tiêu chí 2 (12đ) và Tiêu chí 7 (20đ).
