# STATUS.md — Nhịp tim 3 Agent (Heartbeat)

> Mỗi agent ghi một dòng mỗi 4 giờ — `[H+xx][Agent X] đang làm <task-id> · xong <task-id> · chặn bởi <gì>`.

---

- `[H+01][Agent A] xong S-01 (core/types.py contract freeze), xong A-01 (core/pipeline skeleton), xong S-03 stub bàn giao (process_case rule P05) · không bị chặn`
- `[H+04][Agent A] xong A-14 (YAML policies), xong A-03..A-07 (R1 Sanitize, che PII, prompt injection, cheap guards), xong A-08..A-09 (R2 Extract & fail-safe), xong A-10 (R3 Pre-policy Lock), xong A-02 (R0 Intake & ULID) · sẵn sàng cho Block B2 (A-11..A-13) · không bị chặn`
- `[H+16][Agent A] xong A-11 (R4 Retrieval Adapter & corpus search), xong A-12 (R5 Evidence Validator 7 checks), xong A-13 (R6 Policy Engine Safe AST Evaluator & rules P01..P05), xong A-21 (Ghép pipeline thực tế R4->R6, đo latency, fail-safe P04) · test suite 40/40 passed (0.25s) · ruff & mypy clean 100% · sẵn sàng cho Block B3 (A-15..A-20) · không bị chặn`
- `[H+28][Agent A] xong A-15 (R7a Auto-reply generate), xong A-16 (R8a Groundedness Guard 4 checks), xong A-17 (R7b EscalationCard 4 khối), xong A-18 (R8b Question Quality Guard & blocklist), xong A-19 (R9a/R13 Dispatch countdown 60s, cancel send & correction email), xong A-20 (R11 Resume sau quyết định của người) · test suite 66/66 passed (0.31s) · ruff & mypy clean 100% · sẵn sàng cho Block B4 (A-22..A-24) · không bị chặn`
- `[H+48][Agent A] HOÀN THÀNH 100% CÔNG VIỆC CỦA AGENT A (Block B0 - B4: A-01 -> A-25) · Xong A-22 (core/controls.py: Pause, Resume, Override có lý do, Re-run case diff), xong A-23 (core/explain.py: Giải thích cho người không chuyên <= 120 từ, không dùng từ kỹ thuật cấm), xong A-24 (Email đa ý định & partial_draft), xong A-25 (tests/test_guards.py: hai test sống còn chống over-escalation và chống fail-open) · xong harness 3 kênh & 25 ca benchmark (tests/test_harness.py) · xong audit coverage & benchmark latency p95 (tests/test_audit_coverage.py) · Toàn bộ test suite 106/106 passed (0.61s) · ruff check & mypy clean 100% không lỗi · Pipeline sẵn sàng cho Agent B và Agent C tích hợp đầy đủ · không bị chặn`
- `[H+49][Agent B] xong B-01 và phần B của S-03 (corpus/api.py: 12 chunk giả, 3 domain, 2 human_only, 1 transitional_clause) · test suite 108/108 passed · Ruff và Black sạch · B-02 bị chặn bởi S-02/infra chưa được bàn giao`
- `[H+50][Agent B] xong B-02 (CRUD sources/chunks/corpus_versions, corpus_version đổi khi tập ACTIVE đổi) · kiểm thử SQLite in-memory xanh · tiếp tục B-03`
- `[H+51][Agent B] xong B-03 (nạp PDF/DOCX, URL một lần, text; chống trùng SHA-256; audit SOURCE_UPLOADED) · tiếp tục B-04`
- `[H+52][Agent B] xong B-04 (trích xuất PDF/DOCX/text, bỏ header/footer lặp, giữ Điều/Khoản/Điểm, NFC) · tiếp tục B-05`
- `[H+53][Agent B] xong B-05 (METADATA_PROMPT_V1 + JSON schema, chỉ dùng 3000 ký tự đầu, không bịa trường thiếu) · tiếp tục B-06`
- `[H+54][Agent B] xong B-06 (form sửa metadata, kiểm tra ngày/domain/mã duy nhất/điều khoản chuyển tiếp, audit diff) · tiếp tục B-07`
- `[H+55][Agent B] xong B-07 (chunk theo Điều/Khoản/Điểm, breadcrumb đầy đủ, tách phần >800 token, mặc định human_only) · tiếp tục B-12/B-15 rồi B-08`
- `[H+56][Agent B] xong B-12 (BM25 + sentence-transformers, cache embedding trên đĩa, chỉ index chunk ACTIVE, điểm [0,1]) · tiếp tục B-15`
- `[H+57][Agent B] xong B-15 (6 văn bản giả lập, 54 chunk, 59% auto_answerable/41% human_only, tự seed khi DB trống) · tiếp tục B-08`
- `[H+58][Agent B] xong B-08 (xếp lịch supersede; phát hiện đúng xung đột hoàn học phí 70%/60%, không gắn nhầm hạn rút 30/10/2026) · tiếp tục B-09`
- `[H+59][Agent B] xong B-09 (mọi chunk mới human_only; admin đổi từng nhãn có audit; LLM chỉ đề xuất, không tự áp dụng) · tiếp tục B-10`
- `[H+60][Agent B] xong B-10 (hàng chờ, metadata/chunk labels, HTML diff bản cũ, duyệt/từ chối/yêu cầu sửa bắt buộc lý do) · tiếp tục B-11`
- `[H+61][Agent B] xong B-11 (activate bởi ADMIN thật, supersede theo lịch, tăng corpus_version, quét conflict và gọi reindex) · tiếp tục B-13/B-14`
- `[H+62][Agent B] xong B-13 (SUPERSEDED giữ nguyên DB/audit, loại khỏi tập ACTIVE và gọi reindex) · tiếp tục B-14`
- `[H+63][Agent B] xong B-14 (quét case 30 ngày, FLAG_NEEDS_RECHECK, rollback có lý do/audit/reindex) · tiếp tục B-16`
- `[H+64][Agent B] xong B-16 (admin kiểm tra URL thủ công, SHA-256 báo đổi/không đổi dưới 10s, tạo bản PENDING_REVIEW, audit SOURCE_RECHECKED) · tiếp tục B-17`
- `[H+65][Agent B] xong B-17 (trang quản trị 4 tab chạy trên corpus seed, có trạng thái rỗng, không tải embedding khi chỉ xem, AppTest thật) · test suite 136/136 passed · tiếp tục B-18`
- `[H+66][Agent B] bắt đầu B-18 (kiểm tra contract corpus.api với DB rỗng, chỉ trả chunk ACTIVE, rà soát toàn bộ test/lint/type của làn B)`
- `[H+67][Agent B] xong B-18 và hoàn thành làn B (corpus.api dùng hybrid index trên SQLite khi infra sẵn sàng, không trả chunk SUPERSEDED, DB rỗng fail-safe; sửa rollback hạ bản thay thế và buộc duyệt lại sau mọi chỉnh sửa) · 6 tài liệu/54 chunk/59% auto_answerable · 139/139 test passed · Black, Ruff, mypy sạch`
- `[H+68][Agent C] xong C-01 (README, dependencies ghim phiên bản, make check, ignore secrets/cache, cấu hình Streamlit) · 139/139 test passed · tiếp tục C-02`
- `[H+69][Agent C] xong C-02 (SQLite tự migration, WAL + busy timeout, helper truy vấn, UTC Z và +07:00) · kiểm thử ghi đồng thời xanh · tiếp tục C-03`
- `[H+70][Agent C] xong C-03 (đủ 10 ngưỡng có tên, comment và override từ biến môi trường) · test cấu hình xanh · tiếp tục C-04`
- `[H+71][Agent C] xong C-04 (Gemini JSON qua REST, live/replay/record, cache SQLite, timeout + retry một lần, latency và prompt hash, không ném lỗi) · test wrapper xanh · tiếp tục C-05`
- `[H+72][Agent C] xong C-05 (ACTIONS đóng, actor chuẩn hóa, bắt buộc lý do cho 4 hành động nhạy cảm, truy vấn audit theo case/gần đây) · test audit xanh · tiếp tục C-06`
- `[H+73][Agent C] xong C-06 (telemetry tính trực tiếp từ DB: quyết định, escalation, latency, review, override, groundedness và Verify) · test đếm tay xanh · tiếp tục C-07`
- `[H+74][Agent C] xong C-07 (homepage một hướng dẫn, xử lý email trực tiếp, banner mô phỏng và điều hướng 6 màn hình) · kiểm tra cú pháp xanh · tiếp tục C-08`
- `[H+75][Agent C] xong C-08 (một SVG dùng chung cho homepage và Slide 2, đánh dấu hai điểm con người quyết định) · tiếp tục C-09`
- `[H+76][Agent C] xong C-09 (paste và hộp thư mô phỏng cùng gọi process_case, có chỉ báo R1–R13 và thời gian xử lý) · tiếp tục C-10`
- `[H+77][Agent C] xong C-10 (huy hiệu quyết định, rule/reason, bản nháp, breadcrumb mở rộng, corpus version và liên kết audit) · tiếp tục C-11`
- `[H+78][Agent C] xong C-11 (deadline đọc từ DB, Hủy gửi/Chuyển cho người, khóa sau SENT và tạo email đính chính) · 6 test dispatch/resume passed · tiếp tục C-12`
- `[H+79][Agent C] xong C-12 (thẻ 4 khối, tên loại chuyển tiếp tiếng Việt, phương án chọn và partial draft) · tiếp tục C-13`
- `[H+80][Agent C] xong C-13 (hàng chờ theo thời gian, lý do bắt buộc, shown_at/decided_at/review_seconds và audit nguyên văn) · tiếp tục C-14`
- `[H+81][Agent C] xong C-14 (xem trước, cảnh báo guard, Duyệt và gửi/Sửa nội dung/Trả lại; không có đường tự gửi escalation) · tiếp tục C-15`
- `[H+82][Agent C] xong C-15 (nút giải thích dễ hiểu trên trang xử lý, hàng chờ và audit; ghi EXPLAIN_REQUESTED) · tiếp tục C-16`
- `[H+83][Agent C] xong C-16 (audit mới nhất trước, lọc case/actor/action/ngày, chi tiết 4 câu hỏi và deep link theo case) · tiếp tục C-17`
- `[H+84][Agent C] xong C-17 (Pause/Resume, Override bắt buộc lý do, Rerun có diff; thanh bên luôn hiện và ghi actor ADMIN) · tiếp tục C-18`
- `[H+85][Agent C] xong C-18 (CLI tuần tự gọi process_case channel=verify, kiểm tra decision/type/citation ACTIVE, audit đầu-cuối, đo thời gian) · CLI exit 0 và test ma trận xanh; baseline hiện 1/4 PASS do replay chưa có cassette · tiếp tục C-19`
- `[H+86][Agent C] C-19 WIP: nút Verify 4 và replay cassette đã chạy dưới 60s, hiện 2/4 PASS · chặn bởi retrieval trả chunk human_only/conflict cho case thường quy khiến Evidence Validator hạ AUTO thành OUT_OF_POLICY; không tạo đường Verify riêng · chuyển C-20/C-22 song song`
- `[H+87][Agent C] C-20 WIP: nút 5 case, cột câu hỏi và cassette đã chạy tuần tự, hiện 1/5 PASS · cùng blocker retrieval/evidence của C-19; tiếp tục C-21/C-22`
- `[H+88][Agent C] C-21 WIP: Run All 15 chạy tuần tự, ma trận 4 lớp và hai tỷ lệ đã test khớp đếm tay; thực tế 8/15 PASS · chặn bởi C-19/C-20 retrieval/evidence · tiếp tục C-22`
- `[H+89][Agent C] xong C-22 (bảng đủ trường bắt buộc, timestamp +07:00, deep link audit từng case và tải JSON) · tiếp tục C-23`
- `[H+90][Agent C] xong C-23 (trang đo lường tách hiệu quả/rủi ro, hiện công thức cạnh số và cảnh báo dữ liệu nội bộ giả lập) · tiếp tục C-24`
- `[H+91][Agent C] xong C-24 (12 email giả lập: 5 thường quy, đủ 3 loại escalation, đa ý định, English, ngoài domain, injection; toàn bộ is_synthetic) · tiếp tục C-25`
- `[H+92][Agent C] C-25 WIP: đủ verify4/escalation5/full15, mỗi case có 7 trường và rationale theo tài liệu seed; generator tạo replay cassette · chờ Agent A duyệt A-26 và blocker retrieval của C-19`
- `[H+93][Agent C] C-26 WIP: cấu hình Community Cloud, dependency pin và mẫu Secrets đã sẵn sàng · chưa deploy vì S-06 chưa đạt khi Verify còn đỏ và chưa có phiên Streamlit Cloud đã đăng nhập`
- `[H+94][Agent C] fix C-05/C-17: adapter 5 tên audit cũ từ Runtime sang danh mục action đóng, không đổi contract sau feature freeze · 11 test audit passed · C-19/C-20 vẫn chặn bởi retrieval/evidence`


