# Known Failures & Architectural Debt (Nhật ký sự cố & Giới hạn thiết kế)

> Tài liệu này được duy trì liên tục qua các khối B1 → B7 theo yêu cầu Task S-09.
> Mỗi mục ghi nhận: **Hiện tượng · Điều kiện tái hiện · Nguyên nhân kỹ thuật · Hướng xử lý / Tình trạng**.
> Phục vụ làm nguyên liệu thực tế cho Slide 5 (Giới hạn và rủi ro) của buổi chấm 8 phút.

---

## 1. Trạng thái Case: Lưu trữ bộ nhớ RAM tạm thời [Đã sửa]
- **Hiện tượng:** `_DISPATCH_REGISTRY` trong `core/dispatch.py` và `_CASES_STORE` trong `core/pipeline.py` dùng dict bộ nhớ trong RAM. Khi restart app hoặc chạy worker đa luồng, state bị mất.
- **Điều kiện tái hiện:** Bấm F5 hoặc reload trang Streamlit giữa chừng sau khi tiếp nhận case.
- **Nguyên nhân kỹ thuật:** Khung scaffolding ban đầu tách biệt trước khi có lớp `infra.db`.
- **Hướng xử lý:** Tích hợp `store_case()` và `infra.db`, chuyển trạng thái toàn bộ case (`PENDING_SEND`, `AWAITING_HUMAN`, `SENT`, `CANCELLED`) vào bảng SQLite `cases`.

## 2. Lệch danh mục hành động Audit (Action Names) từ Runtime [Đã sửa]
- **Hiện tượng:** Runtime gửi một số tên action cũ không thuộc danh mục đóng trong `PROJECT_SPEC.md` Mục 7 (`ACTION_LOG_EVENT` thay vì `CASE_RECEIVED`, v.v.), khiến `infra.audit` từ chối ghi event.
- **Điều kiện tái hiện:** Xử lý case qua pipeline R0–R13 hoặc thực hiện can thiệp quản trị Pause, Override.
- **Nguyên nhân kỹ thuật:** Thay đổi chữ ký trong quá trình phát triển độc lập giữa Agent A và Agent C.
- **Hướng xử lý:** Thêm bộ chuyển đổi cục bộ (Local Adapter) trong `infra.audit.log_event` để chuẩn hóa tự động về danh mục đóng hợp lệ mà không cần vi phạm quy tắc đóng băng contract sau H54.

## 3. Nhiễm chéo Conflict Flag giữa các chủ đề trong cùng Domain [Đã sửa]
- **Hiện tượng:** Case hỏi về hạn chót rút học phần (E02/F04) bị chuyển tiếp sang `OUT_OF_POLICY` dù quy định về hạn chót hoàn toàn thống nhất.
- **Điều kiện tái hiện:** Khi hàm `detect_conflicts()` gắn cờ `conflict_flag = 1` cho các chunk về tỷ lệ hoàn học phí giữa `WD-2026-20` và `TU-2026-01`, `top_k=6` retrieval kéo cả 6 chunk của domain `course_withdrawal`, dẫn đến chunk hoàn học phí làm fail Check 5 của câu hỏi hạn chót.
- **Nguyên nhân kỹ thuật:** Check 5 trong `core/evidence.py` ban đầu kiểm tra `any(c.conflict_flag for c in chunks)` mà không đối chiếu chủ đề (topic) của chunk với chủ đề thực tế của email.
- **Hướng xử lý:** Cập nhật Check 5 với hàm `_is_conflict_relevant()`: cờ mâu thuẫn về hoàn học phí chỉ kích hoạt khi câu hỏi thực sự liên quan đến hoàn tiền / học phí (như F15); câu hỏi về hạn chót (E02/F04) không bị ảnh hưởng, giữ vững nguyên tắc thiết kế Mục 9.2 của spec.

## 4. Tải trọng thư viện Embedding gây nghẽn Cold-Start [Đã sửa]
- **Hiện tượng:** Import gói `sentence-transformers` và `torch` (nặng hơn 500MB) gây chậm 15–20 giây khi khởi động và có nguy cơ tràn bộ nhớ (OOM) trên môi trường free-tier Streamlit Cloud.
- **Điều kiện tái hiện:** Khởi động ứng dụng lần đầu trên máy tính có RAM hạn chế hoặc container đám mây.
- **Nguyên nhân kỹ thuật:** Phụ thuộc thư viện học sâu nặng cho bài toán tra cứu văn bản quy chuẩn quy mô vừa (54 chunk).
- **Hướng xử lý:** Triển khai giải pháp Ponytail: Tích hợp `DefaultEmbedder` tinh gọn dựa trên TF-IDF vectorizer / numpy chuẩn của thư viện stdlib, cho phép khởi động ứng dụng trong dưới 2 giây và chạy mượt mà ngay cả khi không cài đặt `sentence-transformers`.

## 5. Nhầm lẫn giữa Hỏi thông tin thủ tục và Yêu cầu kháng nghị cá nhân [Đã sửa]
- **Hiện tượng:** Email hỏi "Lệ phí phúc khảo là bao nhiêu" (E03) bị extractor trích xuất nhầm `asks_appeal=true` do chứa từ khóa "phúc khảo", dẫn tới Pre-policy Lock khóa case về `AUTHORITY_REQUIRED`.
- **Điều kiện tái hiện:** Gửi câu hỏi thông tin thuần túy liên quan đến quy trình hoặc lệ phí phúc khảo.
- **Nguyên nhân kỹ thuật:** Prompt trích xuất trích xuất nhầm câu hỏi thông tin (`is_informational`) thành khiếu nại cá nhân.
- **Hướng xử lý:** Bổ sung chỉ dẫn tường minh trong `EXTRACT_PROMPT_V1` và guard deterministic: chỉ gán `asks_appeal=true` khi sinh viên yêu cầu xem xét lại điểm của chính mình; hỏi lệ phí/thời hạn là câu hỏi thường quy và trả về `AUTO_REPLY`.

## 6. Lệch kỳ vọng F15 giữa Draft Harness và Đặc tả Quy định [Đã sửa]
- **Hiện tượng:** Case F15 ("Rút môn và hoàn học phí") được harness kỳ vọng trả về `FACT_UNRESOLVED / P03`, nhưng theo logic phân loại chính sách Mục 8.3 spec thì mâu thuẫn quy định phải thuộc `OUT_OF_POLICY / P02`.
- **Điều kiện tái hiện:** Chạy bộ kiểm thử `full15` khi đã kích hoạt phát hiện mâu thuẫn văn bản.
- **Nguyên nhân kỹ thuật:** Tệp `cases_full15.json` được soạn nhầm loại escalation ở giai đoạn dựng khung ban đầu trước khi duyệt A-26.
- **Hướng xử lý:** Hoàn thành nghiệm thu task A-26: đối chiếu căn cứ spec Mục 8.3 và Mục 9.2, cập nhật kỳ vọng của F15 thành `OUT_OF_POLICY` với `rule_id = P02` và ghi rõ căn cứ quy định mâu thuẫn giữa `WD-2026-20` và `TU-2026-01`.

## 7. Xử lý Email đa ý định hỗn hợp nhiều Domain [Giới hạn hiện tại - Hướng xử lý Sprint 2]
- **Hiện tượng:** Với email chứa từ 3 ý định trở lên thuộc các domain khác nhau (ví dụ vừa hỏi ký túc xá, vừa hỏi điểm rèn luyện, vừa xin miễn học phí), hệ thống chỉ trích xuất được 2 nhánh chính và gộp chung thành một thẻ escalation tổng thể.
- **Điều kiện tái hiện:** Email sinh viên viết dài, liệt kê danh sách câu hỏi trải dài trên nhiều phòng ban khác nhau.
- **Nguyên nhân kỹ thuật:** Schema `RequestItem` hiện tại ưu tiên tối đa 2 request chính để bảo đảm độ trễ xử lý < 15 giây và tối ưu cho giao diện duyệt nhanh của chuyên viên CTSV.
- **Hướng xử lý:** Sprint 2 sẽ bổ sung bộ tách luồng Intent-Decomposition độc lập, phân rã email thành nhiều sub-ticket riêng biệt cho từng phòng ban.

## 8. Đối sánh mâu thuẫn văn bản dựa trên Heuristic số liệu [Giới hạn hiện tại - Hướng xử lý Sprint 2]
- **Hiện tượng:** `corpus/conflict.py` phát hiện xung đột dựa trên trích xuất mốc thời gian (ngày tháng) và con số (tỷ lệ phần trăm). Các mâu thuẫn ngữ nghĩa phức tạp không chứa số (ví dụ điều kiện xếp loại hành vi) chưa tự động gắn cờ.
- **Điều kiện tái hiện:** Hai văn bản cùng quy định một hành vi nhưng dùng từ ngữ đối lập mà không có số liệu đi kèm.
- **Nguyên nhân kỹ thuật:** Phương pháp heuristic nhẹ nhàng, nhanh chóng và an toàn cho 54 chunk ở Sprint 1.
- **Hướng xử lý:** Sprint 2 sẽ xây dựng Knowledge Graph biểu diễn quan hệ pháp lý (Điều/Khoản) để suy luận xung đột logic ở mức ngữ nghĩa sâu.
