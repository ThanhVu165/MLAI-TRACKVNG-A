# Phân tích giải pháp nạp & duyệt quy chế — Bối cảnh demo 8 phút

## Bối cảnh ràng buộc

| Ràng buộc | Giá trị |
|---|---|
| **Tổng thời gian demo** | 8 phút (480 giây) |
| **Thời gian xử lý 1 case** | SLA < 25 giây (thực tế ~0.5s stub, ~3-8s với LLM thật) |
| **Số case cần chạy demo** | 4 (Verify) + 5 (Escalation) + tương tác live ≈ 10-15 case |
| **Thời gian còn lại cho admin** | ~2-3 phút (sau khi chạy case demo) |
| **Dạng quy chế** | PDF (file tải về) + Web (HTML trên trang trường) |
| **Kích thước quy chế** | Thường 5-50 trang, ~20KB-2MB mỗi file |
| **Số tài liệu seed** | 6 tài liệu (theo Mục 9.2 spec) |

---

## Hai câu hỏi cốt lõi

### Câu hỏi 1: AI duyệt quy chế mới có kịp trong 8 phút không?

**Trả lời ngắn: KHÔNG nên dùng AI duyệt tự động trong demo.**

Phân tích thời gian:

```
AI duyệt 1 tài liệu:
  - Download/fetch:        1-3 giây
  - Extract text (PDF):    1-2 giây
  - LLM phân tích metadata: 3-8 giây (Gemini structured output)
  - LLM gán nhãn chunk:    3-8 giây × N chunk (N ≈ 8-15)
  - Tổng:                  ~30-120 giây/tài liệu
```

Với 6 tài liệu seed, AI duyệt tốn **3-12 phút** → **vượt quá toàn bộ thời gian demo**.

Thêm vào đó, spec nói rõ tại B-09: *"mặc định mọi chunk mới là `human_only` — con người phải chủ động mở quyền"*. Tức là AI duyệt tự động **vi phạm nguyên tắc thiết kế** của hệ thống.

### Câu hỏi 2: Download PDF vs Web khác nhau thế nào?

| Nguồn | Cách lấy | Cách trích text | Khó khăn |
|---|---|---|---|
| **PDF** | `urllib` download file → bytes | `pdfplumber` hoặc `PyPDF2` | Header/footer lặp, encoding, scan-only PDF |
| **Web (HTML)** | `urllib` fetch HTML → bytes | `BeautifulSoup` strip tags | Layout phức tạp, JS render, login wall |
| **DOCX** | `urllib` download file → bytes | `python-docx` | Ít gặp ở trường VN |

---

## 4 Giải pháp

### Giải pháp A: Pre-seed cố định (Khuyến nghị cho Demo)

```
Thời điểm: TRƯỚC khi demo (build time)
Luồng:     Soạn sẵn 6 tài liệu → chunk → gán nhãn → đóng gói vào DB
Runtime:   Không fetch, không download, không AI duyệt
```

**Cách hoạt động:**
1. **Trước demo**: Soạn 6 tài liệu quy chế dạng text thuần (đã trích xuất sẵn từ PDF/web)
2. Chunk + gán nhãn + gán metadata → lưu vào `data/seed_docs/`
3. Script `corpus/seed.py` nạp vào SQLite khi DB trống
4. **Trong demo**: Corpus có sẵn ngay, không tốn giây nào

**Xử lý PDF/Web:**
- PDF: Dùng `pdfplumber` **offline trước demo**, lưu text đã extract vào `data/seed_docs/doc_01.txt`
- Web: Dùng `requests` + `BeautifulSoup` **offline trước demo**, lưu text vào `data/seed_docs/doc_02.txt`
- Cả hai đều chỉ chạy **1 lần trước demo**, không chạy runtime

```python
# corpus/seed.py — chạy 1 lần khi DB trống
SEED_DOCS = [
    {"doc_id": "DOC-01", "title": "QĐ Đào tạo", "file": "data/seed_docs/doc_01.txt", "source_kind": "pdf"},
    {"doc_id": "DOC-02", "title": "QC Rèn luyện", "file": "data/seed_docs/doc_02.txt", "source_kind": "web"},
    ...
]
```

| Ưu điểm | Nhược điểm |
|---|---|
| ✅ 0 giây tải trong demo | ❌ Không thể hiện "cập nhật quy chế" live |
| ✅ Ổn định 100%, không phụ thuộc mạng | ❌ Dữ liệu tĩnh, giám khảo có thể hỏi |
| ✅ Đúng spec B-15 (seed corpus) | ❌ Cần soạn trước ngoài demo |
| ✅ Không cần cài thêm library | |

---

### Giải pháp B: Pre-download + Offline Hash (Khuyến nghị cho tính năng cập nhật)

```
Thời điểm: TRƯỚC demo (download) + TRONG demo (chỉ kiểm tra hash)
Luồng:     Download sẵn → lưu cache → runtime chỉ HEAD check
```

**Cách hoạt động:**
1. **Trước demo**: Chạy script download tất cả PDF/web → lưu vào `data/cache/`
2. Tính SHA-256 cho mỗi file → lưu vào DB `sources.sha256`
3. **Trong demo**: Smart Poller chỉ gửi HEAD request (< 0.5 giây), so ETag/Last-Modified
4. Nếu giám khảo hỏi "quy chế mới thì sao?" → bấm nút kiểm tra → hiện "Không đổi" (vì đã cache)
5. **Demo cập nhật**: Thay file trong cache bằng file mới → bấm kiểm tra → hiện "Đã đổi" → PENDING_REVIEW

**Xử lý PDF/Web:**

```python
# scripts/pre_download.py — chạy 1 lần trước demo
import pdfplumber
from bs4 import BeautifulSoup

SOURCES = [
    {"url": "https://school.edu.vn/qd-dao-tao.pdf", "kind": "pdf"},
    {"url": "https://school.edu.vn/qc-ren-luyen",   "kind": "web"},
]

def download_and_extract(source):
    data = urlopen(source["url"]).read()
    
    if source["kind"] == "pdf":
        # PDF → pdfplumber extract text
        with pdfplumber.open(BytesIO(data)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    
    elif source["kind"] == "web":
        # HTML → BeautifulSoup strip tags
        soup = BeautifulSoup(data, "html.parser")
        # Loại bỏ script, style, nav
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    
    return text, hashlib.sha256(data).hexdigest()
```

| Ưu điểm | Nhược điểm |
|---|---|
| ✅ Demo nhanh (HEAD check < 0.5s) | ❌ Cần mạng cho HEAD check |
| ✅ Thể hiện được tính năng "phát hiện thay đổi" | ❌ Cần cài `pdfplumber`, `beautifulsoup4` |
| ✅ Hash đảm bảo chính xác | ❌ Phải pre-download trước demo |
| ✅ Tích hợp với Smart Poller đã có | |

---

### Giải pháp C: Lazy-fetch On-demand (Cho trường hợp thật)

```
Thời điểm: TRONG demo khi admin bấm "Nạp tài liệu"
Luồng:     Admin dán URL → hệ thống fetch + extract + chunk → PENDING_REVIEW
```

**Cách hoạt động:**
1. Admin mở trang "Quản trị quy định" → dán URL quy chế
2. Hệ thống tự detect loại file (PDF/HTML) từ Content-Type header
3. Download → extract text → chunk → gán nhãn mặc định `human_only` → PENDING_REVIEW
4. Admin duyệt metadata + nhãn → kích hoạt

**Xử lý PDF/Web:**

```python
def detect_and_extract(url: str, data: bytes, content_type: str) -> str:
    """Auto-detect format từ Content-Type và extract text."""
    
    if "application/pdf" in content_type or url.endswith(".pdf"):
        return extract_pdf(data)
    
    elif "text/html" in content_type:
        return extract_html(data)
    
    elif "application/vnd.openxmlformats" in content_type or url.endswith(".docx"):
        return extract_docx(data)
    
    else:
        # Plain text fallback
        return data.decode("utf-8", errors="replace")
```

**Thời gian ước tính:**

```
Download PDF 1MB:      1-3 giây
Extract text:          1-2 giây
Chunk (deterministic): 0.1-0.5 giây
Tổng:                  2-5 giây/tài liệu
```

| Ưu điểm | Nhược điểm |
|---|---|
| ✅ Demo live ấn tượng | ❌ Tốn 2-5 giây/tài liệu (30 giây cho 6 tài liệu) |
| ✅ Cho thấy hệ thống hoạt động thật | ❌ Phụ thuộc mạng — rủi ro demo fail |
| ✅ Xử lý cả PDF lẫn web | ❌ PDF scan-only không extract được text |
| ✅ Tự detect format | ❌ Cần cài dependencies |

---

### Giải pháp D: AI duyệt tự động (KHÔNG khuyến nghị cho Demo)

```
Thời điểm: TRONG demo
Luồng:     Download → AI extract metadata → AI gán nhãn → Auto-approve
```

**Thời gian ước tính:**

```
Download:              1-3 giây
Extract text:          1-2 giây
LLM metadata:          3-8 giây
LLM gán nhãn/chunk:    3-8 giây × 10 chunk = 30-80 giây
LLM duyệt nội dung:   5-10 giây
Tổng:                  40-103 giây/tài liệu
                       = 4-10 PHÚT cho 6 tài liệu
```

| Ưu điểm | Nhược điểm |
|---|---|
| ✅ Hoàn toàn tự động | ❌ **Vượt thời gian demo (4-10 phút cho 6 tài liệu)** |
| ✅ Thông minh nhất | ❌ **Vi phạm nguyên tắc "con người cấp quyền"** |
| | ❌ LLM rate limit khi demo |
| | ❌ Hallucination risk khi phân loại chunk |
| | ❌ Chi phí API cao |

---

## Bảng so sánh tổng hợp

| Tiêu chí | A: Pre-seed | B: Pre-download | C: Lazy-fetch | D: AI duyệt |
|---|---|---|---|---|
| **Thời gian demo** | 0 giây | 0.5 giây/check | 2-5 giây/doc | 40-103 giây/doc |
| **Phù hợp 8 phút** | ✅✅✅ | ✅✅✅ | ✅✅ | ❌ |
| **Cần mạng** | ❌ | Chỉ HEAD | ✅ Download | ✅ Download + API |
| **Xử lý PDF** | Offline | Offline | Runtime | Runtime + LLM |
| **Xử lý Web** | Offline | Offline | Runtime | Runtime + LLM |
| **Demo ấn tượng** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Ổn định** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| **Đúng spec** | ✅ B-15 | ✅ B-16 | ✅ B-03 | ❌ Vi phạm B-09 |
| **Dependencies** | Không cần | `pdfplumber`, `bs4` | `pdfplumber`, `bs4` | + Gemini API |
| **Rủi ro demo fail** | Không | Thấp | Trung bình | Cao |

---

## Khuyến nghị: Kết hợp A + B (Hybrid)

> [!IMPORTANT]
> **Dùng A làm nền, B làm tính năng demo.**

### Luồng thực tế trong 8 phút demo:

```
Phút 0-1:   Mở app, corpus seed đã có sẵn (Giải pháp A)
Phút 1-3:   Chạy 4 case Verify → PASS
Phút 3-5:   Chạy 5 case Escalation → hiện thẻ, quyết định
Phút 5-6:   Demo can thiệp: Pause, Override, Cancel Send
Phút 6-7:   Demo cập nhật quy chế (Giải pháp B):
            → Bấm "Kiểm tra nguồn" → HEAD check 0.5s → "Không đổi"
            → Hoặc: Nạp file PDF mới → PENDING_REVIEW → Duyệt → Kích hoạt
Phút 7-8:   Chạy lại 1 case → diff cho thấy quyết định đã thay đổi
```

### Cách xử lý PDF + Web cụ thể:

```python
# Trước demo: scripts/prepare_seed.py
# ─── PDF ────
# 1. Download PDF từ trang trường
# 2. pdfplumber extract text
# 3. Lưu text thuần vào data/seed_docs/

# ─── Web ────
# 1. requests.get() trang quy chế
# 2. BeautifulSoup loại script/nav/footer
# 3. Lưu text thuần vào data/seed_docs/

# Cả hai đều đã thành text thuần → chunker xử lý giống nhau
```

### Khi giám khảo hỏi "nếu quy chế web cập nhật thì sao?":

> *"Hệ thống có Smart Poller kiểm tra ETag/Last-Modified của URL đã đăng ký. Khi phát hiện thay đổi, tài liệu mới được đưa vào hàng chờ duyệt (PENDING_REVIEW) — con người vẫn là người quyết định kích hoạt. Sau khi kích hoạt, các case liên quan được tự động đánh dấu NEEDS_RECHECK."*

Đây là **câu trả lời đã có sẵn trong code** ([poller.py](file:///c:/Users/nhatm/Downloads/Hackathon/project/MLAI-TRACKVNG-A/core/poller.py)).

---

## Quyết định triển khai: Phương án A+B (Hybrid)

> [!TIP]
> **Đã phê duyệt và tiến hành triển khai Phương án A+B:**
> - **Nhánh thực hiện**: `agent-a/A-28-hybrid-ingestion` (tách từ `agent-a/A-27-smart-poller`)
> - **Phần A (Nền tảng vững chắc - 0s latency)**:
>   - Soạn sẵn 6 tài liệu seed chuẩn hành chính tại `data/seed_docs/` (`doc_01.txt` đến `doc_06.txt`).
>   - Script nạp tự động `corpus/seed.py`: Tự nạp khi SQLite DB trống; băm SHA-256, tự động chia ≥ 45 chunk; gán nhãn ~60% `auto_answerable` / ~40% `human_only`; tính `corpus_version` chuẩn xác.
> - **Phần B (Tính năng động - Smart Poller HEAD check < 0.5s)**:
>   - Sử dụng `core/poller.py` đã hoàn thiện.
>   - Gửi HTTP HEAD check qua ETag / Last-Modified / Content-Length cho các URL nguồn đã đăng ký.
>   - Khi phát hiện thay đổi hoặc nạp tài liệu mới: Đưa vào `PENDING_REVIEW` (chống trùng lặp), kích hoạt bởi quản trị viên, tự động quét và đánh dấu `NEEDS_RECHECK` cho các case liên quan.

