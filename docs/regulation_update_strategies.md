# Phân Tích Các Chiến Lược Tự Động Cập Nhật Quy Chế Cho Hệ Thống RAG (Học Vụ & CTSV)

Tài liệu này phân tích chi tiết các giải pháp kỹ thuật, đánh giá toàn diện **ưu điểm - nhược điểm**, và cung cấp **bảng so sánh đối chiếu** nhằm giải quyết bài toán: **Làm thế nào để hệ thống RAG luôn tự động cập nhật kịp thời các văn bản quy chế được tải lên website trường đại học để trả lời email sinh viên chính xác, không bị lỗi thời và tránh rủi ro pháp lý.**

---

## 1. Bối Cảnh & Tính Chất Đặc Thù Của Quy Chế Trường Đại Học

Khác với các hệ thống RAG hỏi đáp tài liệu thông thường, văn bản quy chế đào tạo và công tác sinh viên (CTSV) có tính pháp lý và tính ràng buộc rất cao:
1. **Hiệu lực theo thời gian (`effective_from`, `effective_to`):** Văn bản có ngày bắt đầu áp dụng và ngày hết hiệu lực rõ ràng.
2. **Quan hệ kế thừa & thay thế (`superseding`):** Văn bản mới thường sửa đổi, bổ sung hoặc bãi bỏ một phần (chứ không nhất thiết xóa toàn bộ) các quyết định trước đó.
3. **Phân vùng đối tượng áp dụng (`cohorts`):** Cùng một trường nhưng sinh viên khóa K48 có thể áp dụng quy chế năm 2022, trong khi tân sinh viên K50 áp dụng quy chế mới năm 2024.
4. **Điều khoản chuyển tiếp (`transitional_clause`):** Một số quy định có lộ trình áp dụng riêng cho các trường hợp đặc biệt.

Do đó, việc cập nhật quy chế vào RAG **không thể thực hiện bằng cách ghi đè mù quáng (blind overwrite)** mà phải đảm bảo tính toàn vẹn phiên bản (`corpus_version`).

---

## 2. Đánh Giá Toàn Diện 4 Phương Pháp Thu Thập Tự Động Từ Web Trường

```
                     ┌──────────────────────────────────────────────┐
                     │          Website Trường / Portal CTSV         │
                     └──────────────────────┬───────────────────────┘
                                            │
        ┌───────────────────┬───────────────┴───────────────┬───────────────────┐
        ▼                   ▼                               ▼                   ▼
   [Phương pháp 1]     [Phương pháp 2]                 [Phương pháp 3]     [Phương pháp 4]
   Scheduled Polling   RSS / Sitemap XML               Webhook / EDoc      Headless Browser
   + SHA-256 Hash      Monitoring                      Event-Driven        (Playwright/Selenium)
```

---

### Phương Pháp 1: Polling Định Kỳ Kết Hợp Content Hash / ETag / Last-Modified

#### Cơ chế hoạt động:
- Thiết lập tiến trình chạy ngầm định kỳ (Scheduled Cron Job, ví dụ: 30–60 phút/lần).
- Gửi HTTP Request tới chuyên mục *"Văn bản - Quy chế"* hoặc *"Thông báo đào tạo"* của trường.
- Kiểm tra HTTP Header (`Last-Modified`, `ETag`) hoặc tính toán mã băm nội dung (`SHA-256`) của file đính kèm/nội dung trang.
- So sánh với bảng lịch sử nguồn (`sources`). Nếu phát hiện mã hash mới hoặc link mới $\rightarrow$ Kích hoạt quy trình bóc tách và nạp vào RAG.

#### Ưu điểm (Pros):
- **Tự chủ hoàn toàn (100% Independent):** Không yêu cầu can thiệp hay xin quyền truy cập vào backend của trường.
- **Tiêu tốn ít tài nguyên:** Chỉ là các lời gọi HTTP GET/HEAD nhẹ nhàng, không chiếm nhiều CPU/RAM của server RAG.
- **Dễ triển khai & bảo trì:** Viết bằng thư viện chuẩn (như `httpx`, `requests`, `BeautifulSoup`), dễ viết unit test và dễ debug.
- **Phát hiện chính xác sửa đổi nội dung:** Mã băm `SHA-256` đảm bảo dù nhà trường tải lại file cùng tên nhưng sửa một câu chữ bên trong thì hệ thống vẫn nhận diện được.

#### Nhược điểm (Cons):
- **Độ trễ cập nhật (Update Lag):** Không mang tính thời gian thực (real-time). Nếu trường ban hành quy chế khẩn cấp giữa 2 chu kỳ quét, các email gửi đến trong khoảng thời gian này vẫn bị trả lời theo quy chế cũ.
- **Nghịch lý tần suất quét (Polling Frequency Dilemma):** Quét quá thưa thì trễ thông tin; quét quá dày (ví dụ 1 phút/lần) thì dễ bị hệ thống bảo mật của trường (Cloudflare, WAF, Rate Limiter) chặn IP hoặc làm nghẽn server trường.
- **Nhiễu do giao diện động (False Positive Noise):** Trang web trường có thể chứa banner thay đổi, bộ đếm lượt truy cập, thời gian hiển thị động. Nếu hash toàn bộ HTML trang sẽ luôn ra mã mới dù không có văn bản mới.
- **Header `ETag` / `Last-Modified` thiếu tin cậy:** Nhiều máy chủ web trường cấu hình sai, mỗi lần khởi động lại server hoặc xóa cache là header thay đổi dù file tĩnh không đổi.
- **Đứt gãy khi đổi giao diện (Silent Failure):** Quản trị viên web chỉ cần đổi tên class CSS, thẻ HTML hoặc đường dẫn danh mục là crawler không bóc tách được link file mới mà không hề báo lỗi ngoại lệ.

---

### Phương Pháp 2: Giám Sát RSS Feed / Sitemap XML

#### Cơ chế hoạt động:
- Lắng nghe đường dẫn RSS Feed (ví dụ: `school.edu.vn/van-ban/feed`) hoặc tệp `sitemap.xml` sinh ra bởi các CMS (WordPress, Drupal, Joomla).
- Định kỳ đọc file XML để tìm các thẻ `<item>` hoặc `<url>` mới được bổ sung theo mốc thời gian `<pubDate>` / `<lastmod>`.

#### Ưu điểm (Pros):
- **Cấu trúc chuẩn hóa quốc tế (Standardized Format):** Dữ liệu dạng XML có schema rõ ràng, không lo bị gãy do thay đổi giao diện CSS/HTML như cào trang web.
- **Cực kỳ nhẹ và nhanh:** Kích thước tệp RSS/Sitemap rất nhỏ, xử lý phân tích cú pháp chỉ mất vài mili-giây.
- **Thân thiện với máy chủ trường:** Không gây áp lực tải, không bị coi là hành vi quét web độc hại (scraping/crawling).

#### Nhược điểm (Cons):
- **Tính khả dụng thực tế rất thấp ở mảng văn bản:** Phần lớn cổng thông tin trường ĐH tại Việt Nam chỉ bật RSS cho mục Tin tức chung. Các chuyên mục văn bản quy phạm nội bộ thường **không hỗ trợ RSS Feed**.
- **Sitemap bị trễ (Staleness):** Tệp `sitemap.xml` trên web trường thường do plugin tạo theo lịch tuần hoặc khi admin bấm sinh lại thủ công, không phản ánh thời gian thực khi có bài đăng mới.
- **Nội dung bị cắt cụt (Truncated Data):** RSS chỉ chứa tiêu đề và tóm tắt ngắn, hiếm khi đính kèm toàn văn hoặc link trực tiếp đến tệp PDF quyết định. Vẫn phải viết thêm crawler phụ để vào trang chi tiết tải file.
- **Thiếu hoàn toàn metadata học vụ:** Không thể cung cấp các thông tin thiết yếu như: số hiệu công văn, ngày ký, ngày bắt đầu hiệu lực, khóa sinh viên áp dụng.

---

### Phương Pháp 3: Webhook / Event-Driven từ Hệ Thống Quản Lý Văn Bản Nội Bộ (E-Office / EDoc)

#### Cơ chế hoạt động:
- Tích hợp trực tiếp với phần mềm điều hành văn bản của trường (E-Office, phần mềm quản trị Đào tạo/CTSV).
- Mỗi khi văn bản được ký duyệt và phát hành chính thức, hệ thống nguồn chủ động gửi một HTTP POST request (Webhook) kèm toàn bộ payload và tệp đính kèm sang hệ thống RAG.

#### Ưu điểm (Pros):
- **Thời gian thực tuyệt đối (Real-time 0-second Latency):** Nhận văn bản ngay tại thời điểm ban hành, không có độ trễ do chu kỳ quét.
- **Siêu dữ liệu sạch và chính xác 100%:** Nhận trực tiếp metadata chuẩn từ cơ sở dữ liệu trường (Số Quyết định, ngày ký, người ký, phòng ban ban hành, ngày hiệu lực), không cần dùng LLM đoán mò.
- **Không tốn tài nguyên định kỳ:** Hệ thống RAG ở trạng thái nghỉ hoàn toàn, chỉ kích hoạt khi có sự kiện gửi đến.
- **Bảo đảm độ tin cậy và pháp lý:** Nguồn dữ liệu là duy nhất và chính thống, loại bỏ triệt để nguy cơ cào nhầm trang web giả mạo hoặc bản nháp.

#### Nhược điểm (Cons):
- **Rào cản hành chính và thủ tục cực lớn:** Đây là rào cản lớn nhất. Để mở được API/Webhook từ hệ thống quản lý văn bản nội bộ ra một ứng dụng AI đòi hỏi qua nhiều cấp phê duyệt (Ban Giám hiệu, Phòng CNTT, An toàn thông tin), thường mất nhiều tháng hoặc không khả thi trong phạm vi dự án thử nghiệm/hackathon.
- **Hạ tầng phân mảnh (Siloed Departments):** Trường ĐH thường có nhiều hệ thống rời rạc: Phòng Đào tạo dùng một phần mềm, Phòng CTSV dùng trang riêng, Văn phòng BGH dùng phần mềm công văn khác. Tích hợp một nguồn sẽ bỏ sót các nguồn khác.
- **Rủi ro rò rỉ văn bản chưa ban hành:** Nếu cấu hình sự kiện không chặt chẽ, Webhook có thể bắn dữ liệu khi văn bản mới chỉ ở bước "Dự thảo" hoặc "Trình ký", khiến RAG trả lời trước khi chính sách có hiệu lực chính thức.
- **Ràng buộc phụ thuộc đối tác phần mềm:** Hệ thống E-Office thường do nhà thầu thứ ba cung cấp; việc can thiệp thêm tính năng Webhook phát sinh chi phí và thời gian ký kết hợp đồng.

---

### Phương Pháp 4: Headless Browser Scraping (Playwright / Selenium / Puppeteer)

#### Cơ chế hoạt động:
- Khởi chạy một trình duyệt ảo không giao diện (Headless Chromium/Firefox) trên server.
- Tự động thực hiện các thao tác: Mở trang portal, điền thông tin đăng nhập tài khoản nội bộ (nếu yêu cầu), vượt qua kiểm tra JavaScript, bấm vào danh mục tra cứu, chờ DOM render xong và trích xuất dữ liệu/tải PDF.

#### Ưu điểm (Pros):
- **Xử lý được các trang web hiện đại (SPA/SSR):** Vượt qua được các trang xây dựng bằng React, Vue, Angular mà HTTP GET thông thường chỉ nhận về khung HTML rỗng.
- **Vượt qua được rào cản đăng nhập (Authenticated Portals):** Khả thi với các tài liệu quy chế bị khóa sau trang đăng nhập sinh viên/chuyên viên (Single Sign-On - SSO, CAS).
- **Mô phỏng tương tác người dùng linh hoạt:** Có thể click phân trang, mở modal, kích hoạt sự kiện tải file JavaScript phức tạp.

#### Nhược điểm (Cons):
- **Cực kỳ ngốn tài nguyên phần cứng (Resource Intensive):** Mỗi phiên bản Playwright/Chromium chiếm dụng từ 300MB – 1GB RAM và lượng CPU rất lớn. Chạy định kỳ trên server RAG dễ gây ra lỗi tràn bộ nhớ (`Out Of Memory - OOM Crash`).
- **Tốc độ chậm và độ trễ cao (High Latency):** Phải tải đầy đủ asset (ảnh, CSS, script) và chờ render. Một lần quét có thể mất 30–60 giây, chậm hơn hàng chục lần so với HTTP request thông thường.
- **Dễ bị chặn bởi cơ chế chống bot và CAPTCHA:** Các hệ thống bảo vệ hiện đại (Cloudflare, reCAPTCHA, Akamai) rất nhạy với headless browser. Hệ thống sẽ bị khóa IP hoặc đòi nhập mã xác thực.
- **Kém ổn định (Flaky Scraping):** Vào các đợt cao điểm học vụ (đăng ký môn, xem điểm thi), mạng trường bị nghẽn dẫn đến `TimeoutError`, DOM render không kịp, làm bot bị treo hoặc trả về dữ liệu rỗng.
- **Bảo trì phiên đăng nhập phức tạp:** Cookie và Token hết hạn liên tục; nếu trường bật xác thực hai lớp (2FA/OTP) qua email/SMS thì bot hoàn toàn bị bất khả thi nếu không có người can thiệp.

---

## 3. Bảng So Sánh Tổng Hợp 4 Phương Pháp

| Tiêu chí Đánh giá | Phương pháp 1: Polling + Hash | Phương pháp 2: RSS / Sitemap | Phương pháp 3: Webhook E-Office | Phương pháp 4: Headless Browser |
| :--- | :---: | :---: | :---: | :---: |
| **Độ trễ cập nhật (Latency)** | Trung bình (15–60 phút) | Chậm (theo chu kỳ XML) | **Tức thì (0 giây)** | Trung bình (15–60 phút) |
| **Tiêu tốn tài nguyên Server** | Rất thấp (Vài MB RAM) | Cực thấp (Vài KB) | **Thấp nhất (Thụ động)** | **Rất cao (500MB–1GB RAM)** |
| **Tính khả thi triển khai ĐH** | **Rất cao (Tự chủ 100%)** | Thấp (Ít hỗ trợ) | Rất thấp (Rào cản hành chính) | Khá (Cần tài khoản portal) |
| **Độ ổn định vận hành** | Khá (Dễ vỡ nếu đổi DOM) | Tốt (Schema chuẩn) | **Tuyệt đối (API Contract)** | Kém (Dễ timeout, vỡ session) |
| **Độ chính xác của Metadata** | Khá (Cần trích xuất lại) | Kém (Chỉ có title/date) | **Tuyệt đối (Có sẵn trường)** | Khá (Cần trích xuất lại) |
| **Rủi ro bị chặn IP (WAF/Bot)** | Thấp - Trung bình | Rất thấp | **Không có (Nội bộ)** | **Rất cao (CAPTCHA/WAF)** |
| **Xử lý trang có đăng nhập** | Không (Chỉ trang công khai) | Không | Không áp dụng | **Có (Mô phỏng login)** |
| **Chi phí bảo trì mã nguồn** | Trung bình | Thấp | Rất thấp | Cao (Thường xuyên sửa locator) |

---

## 4. Kiến Trúc Đề Xuất Cho Hệ Thống Email Triage RAG: Mô Hình Hybrid 3 Lớp

Từ các phân tích trên, một giải pháp duy nhất không thể vừa đảm bảo tính tự động vừa tuyệt đối an toàn về mặt pháp lý trong môi trường giáo dục. Kiến trúc chuẩn mực được đề xuất là **Mô hình Hybrid 3 Lớp (Three-Tier Ingestion Pipeline)**:

```
[Layer 1: Tự động thu thập] ────► Smart Poller (Phương pháp 1 tinh gọn, chỉ gửi HEAD check Content-Length/ETag)
                                           │
[Layer 2: Hàng chờ phê duyệt] ──► Hàng chờ Staging (SourceStatus.PENDING_REVIEW) + LLM bóc tách metadata
                                           │
[Layer 3: Cứu cánh thủ công] ───► Admin Webhook / Giao diện kéo thả PDF khẩn cấp cho chuyên viên CTSV
                                           │
                                           ▼
                                 [Corpus Versioning]
                                Bump version: cv_v1 ──► cv_v2
```

### Chi tiết các lớp:

1. **Lớp 1 - Smart Poller (Tự động phát hiện nhẹ nhàng):**
   - Áp dụng Phương pháp 1 nhưng tối ưu: Thay vì tải toàn bộ trang, crawler chỉ gửi HTTP `HEAD` request kiểm tra danh sách link PDF thông báo và dung lượng `Content-Length`.
   - Chỉ khi phát hiện tệp mới hoặc dung lượng thay đổi, hệ thống mới tải tệp xuống và kiểm tra mã băm `SHA-256`.
   - Tần suất khuyến nghị: Quét 30 phút/lần trong giờ hành chính (7h00 – 18h00), 2 tiếng/lần ngoài giờ.

2. **Lớp 2 - Hàng chờ Phê duyệt & Đánh nhãn Siêu dữ liệu (Staging Buffer):**
   - Tài liệu mới crawl về **tuyệt đối không nạp thẳng vào Vector DB phục vụ người dùng ngay**.
   - Tự động chuyển trạng thái thành `SourceStatus.PENDING_REVIEW`.
   - LLM hỗ trợ tự động bóc tách cấu trúc: `doc_id`, `effective_from`, `cohorts`, và điều khoản thay thế `supersedes_doc_id`.
   - Chuyên viên CTSV chỉ cần mất 30 giây để nhấn nút *"Xác nhận kích hoạt (Activate)"* trên giao diện quản trị (Agent B). Hành động này kích hoạt nâng phiên bản: `cv_v1` $\rightarrow$ `cv_v2`.

3. **Lớp 3 - Cổng nạp khẩn cấp cho Chuyên viên (Manual Fallback):**
   - Trong thực tế, chuyên viên CTSV thường nhận được quyết định đóng dấu đỏ bằng giấy hoặc email nội bộ trước khi văn bản được tải lên web trường.
   - Cung cấp tính năng tải trực tiếp tệp PDF trên giao diện admin để nạp quy chế ngay lập tức mà không cần chờ crawler.

---

## 5. Cơ Chế Xử Lý Đồng Bộ An Toàn Trong Runtime RAG (Agent A)

Để đảm bảo hệ thống không bao giờ trả lời sai lệch khi quy chế cập nhật:

1. **Phân đoạn có cấu trúc (Structural Chunking):**
   - Cắt nhỏ văn bản theo đơn vị pháp lý: **Điều $\rightarrow$ Khoản $\rightarrow$ Điểm**, không cắt ngẫu nhiên theo số lượng token.
   - Giữ nguyên đường dẫn phân cấp (`breadcrumb`: *QĐ 3150 · Điều 8 · Khoản 2*).
2. **Quản lý trạng thái văn bản cũ (`SUPERSEDED`):**
   - Khi quy chế mới kích hoạt, các chunk thuộc quy chế cũ không bị xóa bỏ mà chuyển trạng thái sang `SUPERSEDED` kèm ngày hết hiệu lực `effective_to`.
   - Sinh viên hỏi về sự việc xảy ra trong quá khứ vẫn tra cứu đúng quy định thời điểm đó; sinh viên hỏi hiện tại sẽ chỉ lấy quy chế `ACTIVE`.
3. **Đóng băng phiên bản ở bước tiếp nhận (Runtime Freeze tại R0):**
   - Khi email sinh viên được tiếp nhận tại bước R0, hệ thống ghim chặt phiên bản hiện tại (ví dụ: `cv_v1`).
   - Kể cả khi web trường cập nhật `cv_v2` trong lúc pipeline đang xử lý, case đó vẫn giữ nguyên tính nhất quán từ đầu đến cuối.
4. **Hồi cứu và phát cảnh báo đính chính (`rerun_case` & `create_correction_email`):**
   - Khi quy chế mới kích hoạt, hệ thống tự động chạy lại các email đã nhận trong 48 giờ qua (`rerun_case`).
   - Nếu kết quả thay đổi (ví dụ: từ `ESCALATE` thành `AUTO_REPLY` hoặc thay đổi nội dung trả lời), hệ thống tự động:
     - Hủy lệnh gửi nếu email còn nằm trong hàng chờ 60 giây (`cancel_send`).
     - Soạn sẵn bản thảo email đính chính (`create_correction_email`) để chuyên viên xem xét gửi lại cho sinh viên.
