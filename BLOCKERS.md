# BLOCKERS

- `[H+86][Agent C][C-19/C-20]` Hai case thông tin thường quy V01/V02 bị hạ thành
  `OUT_OF_POLICY`: `corpus.api.search(top_k=6)` trả kèm chunk `human_only` hoặc có xung đột,
  còn `core.evidence.validate_evidence()` đánh trượt toàn bộ tập khi có bất kỳ chunk như vậy.
  Verify phải dùng đúng `process_case()` nên làn C không lọc riêng. Cần Agent A/B thống nhất sửa tại
  retrieval chung để cả UI và Verify nhận cùng kết quả.
- `[H+92][Agent C][C-25]` Bộ 15 case đã soạn và chạy, nhưng chưa được đánh `DONE` cho tới
  khi Agent A hoàn tất A-26, xác nhận từng kỳ vọng từ tài liệu thay vì từ hành vi code hiện tại.
- `[H+93][Agent C][C-26]` Chưa thể deploy public: S-06 chưa đạt do C-19/C-20 còn đỏ,
  đồng thời thao tác Community Cloud cần phiên đăng nhập có quyền quản trị GitHub repo. Cấu hình và
  mẫu Secrets đã sẵn sàng, không có khóa thật trong repo.
