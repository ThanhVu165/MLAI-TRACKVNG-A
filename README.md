# Escalation Referee

Ứng dụng hỗ trợ văn phòng Công tác Sinh viên xử lý email theo quy định, tự trả lời
các trường hợp đủ căn cứ và chuyển chuyên viên khi thiếu dữ kiện hoặc cần thẩm quyền.

## Chạy nhanh

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
copy .env.example .env
.venv/Scripts/streamlit run streamlit_app.py
```

Linux/macOS dùng `source .venv/bin/activate` và `streamlit run streamlit_app.py`.

## Kiểm tra

```bash
make check
```

Ứng dụng chỉ mô phỏng quy trình và không gửi email thật. Dữ liệu seed đều là dữ liệu
giả lập, không chứa thông tin cá nhân thật.
