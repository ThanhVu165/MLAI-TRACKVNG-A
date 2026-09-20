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


