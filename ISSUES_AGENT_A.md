# ISSUES — Agent A (`core/`)

> Gộp từ 2 vòng audit độc lập (đọc code + chạy test + tái hiện lỗi). Mọi phát hiện dưới đây đã được **đối chiếu trực tiếp với code thật trong repo**, kèm file:dòng cụ thể — không có mục nào là suy đoán.
> Trạng thái tại thời điểm audit: `main`/`dev` cùng trỏ 1 commit `6db9e4c`, 106/106 test pass, ruff sạch, black báo 24 file cần format.
> **Việc B (corpus) đang làm song song — sửa xong nhóm 🔴 trước khi B giao `corpus/api.py` thật, nếu không lỗi sẽ ẩn đến tận lúc demo.**

---

## Tại sao 106/106 test pass không có nghĩa là an toàn

Hai lỗ hổng làm bộ test hiện tại **không phát hiện được chính các lỗi nó được sinh ra để bắt**:

1. `tests/test_guards.py` mock timeout ở **tầng `core.pipeline.extract_facts`** (`patch("core.pipeline.extract_facts", side_effect=TimeoutError(...))`), tức chặn *trước khi* vào code thật trong `extract.py`. Nhánh `except (ImportError, Exception)` thật bên trong `extract.py` (dòng 268) **chưa bao giờ được test chạy qua**.
2. `tests/test_audit_coverage.py` dùng `fake_log_event(*args, **kwargs)` — nhận **mọi** tham số, mọi từ khóa, không kiểm tra chữ ký. Nó xác nhận "có gọi log_event" chứ không xác nhận "gọi đúng chữ ký `infra.audit.log_event` thật". Khi Agent C giao hàm thật (chữ ký đóng băng ở Mục 5.3 spec), các lệnh gọi sai tham số sẽ **vỡ ngay** — nhưng vỡ trong im lặng vì bị `except: pass` nuốt (xem mục 3 bên dưới).

→ Trước khi đóng bất kỳ mục nào ở nhóm 🔴, hãy viết test mock **đúng tại điểm gọi thật** (bên trong hàm, không phải ở `pipeline.py`), và cho mock `log_event` có chữ ký chặt y hệt contract để bắt lỗi tham số ngay lập tức.

---

## 🔴 Nhóm 1 — Chặn tích hợp, phải xong trước khi ráp với `corpus.api` / `infra.*` thật

### 1. Lỗi hệ thống thật bị đổi thành trả lời tự động, không phải escalate

**File:** `core/extract.py:242-268`, `core/retrieval.py:117-127`

```python
except (ImportError, Exception):  # noqa: BLE001 - Dự phòng khi infra.llm chưa cấu hình
    return _heuristic_extract(clean_text, subject, language)
```
```python
except (ImportError, Exception) as exc:  # noqa: BLE001 - Dự phòng khi corpus chưa có DB
    ...
    matched_chunks = [... STUB_CHUNKS ...]
    return matched_chunks, EvidenceStatus.OK
```

**Vấn đề:** `except (ImportError, Exception)` gộp chung hai tình huống hoàn toàn khác nhau — (a) `infra.llm`/`corpus.api` *chưa tồn tại* (hợp lệ, cần fallback) và (b) hàm đó *tồn tại nhưng ném lỗi thật* (bug thật, mạng lỗi, DB sập). Cả hai đều rơi vào cùng một nhánh fallback, và fallback đó **trả về `EvidenceStatus.OK` / một extraction hợp lệ** thay vì escalate. Một lỗi thật ở R2 hoặc R4 hiện tại có thể trôi thẳng tới `AUTO_REPLY`.

Đây là vi phạm trực tiếp nguyên tắc bất khả xâm phạm #2 trong PROJECT_SPEC: *"Fail-safe, không bao giờ fail-open."*

**Cách sửa:** Tách hai nhánh rõ ràng.
```python
try:
    from infra.llm import call_json
except ImportError:
    return _heuristic_extract(...)  # môi trường stub — chấp nhận được

try:
    res = call_json(...)
except Exception as exc:
    logger.error("LLM call thất bại thật sự: %s", exc)
    return Extraction(..., llm_error=str(exc))  # → P04 escalate, KHÔNG heuristic
```
Áp dụng cùng pattern cho `retrieval.py`.

**Cách xác minh đã sửa:** Viết test mock lỗi **ngay bên trong `extract.py`** (patch `infra.llm.call_json` để ném `RuntimeError` sau khi import thành công), không patch ở `pipeline.py`. Test phải đỏ trước khi sửa, xanh sau khi sửa.

---

### 2. Pause và Override không chặn được thư đã lên lịch gửi

**File:** `core/dispatch.py` (hàm `dispatch_case`), `core/controls.py` (toàn bộ)

**Vấn đề — hai nguồn sự thật tách rời:**
- `dispatch_case()` chỉ kiểm tra `record.status == PENDING_SEND` và hết giờ đếm ngược chưa. **Không có dòng nào gọi `is_automation_paused()`.**
- `override_decision()` nhận vào một `PipelineResult`, trả về **bản sao đã sửa** qua `dataclasses.replace()` — nó không hề đụng vào `_DISPATCH_REGISTRY`. Đã xác nhận: `grep "_DISPATCH_REGISTRY" core/controls.py` → không có kết quả.

**Hậu quả:** Bấm Tạm dừng, hoặc ghi đè quyết định sang `ESCALATE`, **không ngăn được** case gốc trong `_DISPATCH_REGISTRY` tự chuyển sang `SENT` khi hết 60 giây. Đây chính là nút "can thiệp dừng" — 4 điểm không được cắt trong toàn bộ kế hoạch.

**Cách sửa:**
1. `dispatch_case()` phải kiểm tra `if is_automation_paused(): return False, "Hệ thống đang tạm dừng, không tự động gửi."` trước khi gửi.
2. `override_decision()` khi `new_decision != AUTO_REPLY` phải gọi `dispatch.cancel_send(case_id, actor, reason)` hoặc `escalate_from_pending()` để đồng bộ registry, không chỉ trả về object mới.
3. Về lâu dài (ghi vào `docs/known_failures.md` nếu chưa kịp làm ngay): trạng thái case nên có **một nguồn sự thật duy nhất** — hiện tại `_DISPATCH_REGISTRY` (dict trong RAM) và `PipelineResult` (trả về từ hàm) là hai bản sao độc lập, dễ lệch nhau. Khi `infra.db` có, cả hai nên đọc/ghi cùng một hàng trong bảng `cases`.

**Cách xác minh đã sửa:** Test: `schedule_dispatch()` → `pause_automation()` → gọi `dispatch_case(force=True)` → phải trả `False`, không chuyển `SENT`. Test thứ hai: `schedule_dispatch()` → `override_decision(..., Decision.ESCALATE, ...)` → `dispatch_case(force=True)` → phải trả `False`.

---

### 3. Groundedness Guard bỏ qua đúng loại số dễ bị bịa nhất

**File:** `core/ground_guard.py:106-108`

```python
for num in body_numbers:
    if num in ("1", "2") and len(num) == 1:
        continue
    if num not in evidence_numbers:
        ...
```

**Vấn đề:** Mọi số "1" hoặc "2" đứng một mình bị **bỏ qua hoàn toàn** khỏi kiểm tra đối chiếu evidence — kể cả khi nó là con số cốt lõi của câu trả lời. Ví dụ đã tái hiện: draft nói *"thời hạn là 1 tuần"* trong khi evidence ghi *"8 tuần"* → **guard vẫn PASS**, vì "1" nằm trong danh sách miễn kiểm tra.

Đây là lỗ hổng ngay trong cơ chế bảo vệ nguyên tắc *"tuyệt đối không đưa ra kết quả khẳng định trên dữ liệu đã bị gắn cờ nghi vấn"* — một trong năm nguyên tắc bất khả xâm phạm của spec.

**Cách sửa:** Bỏ hẳn ngoại lệ này, hoặc thu hẹp nó chỉ áp dụng khi số đó là một phần của cụm thứ tự không mang thông tin định lượng (ví dụ "Điều 1", "bước 2") — việc này regex `RE_ARTICLE` đã xử lý riêng rồi nên không cần ngoại lệ số nữa. Đơn giản nhất: xóa hẳn 2 dòng `if num in ("1", "2")...continue`.

**Cách xác minh đã sửa:** Test với draft chứa *"1 tuần"* khi evidence chỉ có *"8 tuần"* → phải fail với `groundedness_failed:hallucinated_number_1`.

---

### 4. Bốn hàm bàn giao không khớp chữ ký contract (Mục 5.3 spec)

**File:** `core/controls.py`, `core/resume.py`, `core/explain.py`

| Hàm | Contract yêu cầu | Thực tế trong code |
|---|---|---|
| `pause_automation` | `(actor: str, reason: str) -> None` | `(actor: str = "ADMIN:system") -> bool` — **thiếu `reason`, sai kiểu trả về** |
| `override_decision` | `(case_id: str, new_decision, actor, reason) -> PipelineResult` | `(result: PipelineResult, new_decision, reason, *, actor=...) -> PipelineResult` — **nhận object thay vì case_id** |
| `rerun_case` | `(case_id: str, actor: str) -> tuple[PipelineResult, dict]` | `(original_result: PipelineResult, inp: CaseInput, *, actor=...) -> dict` — **khác cả input lẫn output** |
| `resume_after_human` | tên hàm cố định trong contract | Tên thật: **`resume_after_decision`** |
| `explain_plainly` | `(case_id: str) -> str` | Tên thật: **`explain_decision(result: PipelineResult, actor=...) -> str`** — **sai tên, sai tham số** |

**Vấn đề:** Agent C khi code UI (`pages/2_Hang_cho_duyet.py`, `pages/4_Nhat_ky_kiem_toan.py`, thanh điều khiển toàn cục) sẽ viết code theo **đúng contract trong PROJECT_SPEC** — họ không có lý do gì để đoán tên hàm hay chữ ký thật khác đi. Khi ráp, mọi lệnh gọi từ phía C sẽ vỡ ngay tại H28.

**Cách sửa:** Đổi tên + chữ ký 5 hàm này khớp *chính xác* Mục 5.3. Nếu cần giữ thêm tham số phụ (như `new_escalation_type`), đặt sau các tham số bắt buộc và có giá trị mặc định, không đổi thứ tự/tên tham số bắt buộc. `override_decision` và `rerun_case` cần tự tra `case_id` (từ đâu — DB khi có, hoặc registry tạm) thay vì bắt người gọi truyền cả object.

**Cách xác minh đã sửa:** Viết `tests/test_contract_signatures.py` dùng `inspect.signature()` so khớp với chữ ký ở Mục 5.3 — test này tự động chặn drift trong tương lai, không cần đọc code bằng mắt mỗi lần.

---

### 5. Audit hành động quản trị hiện ghi được 0 sự kiện khi contract thật vào

**File:** `core/controls.py:144`, `core/explain.py:99`

```python
# controls.py
log_event(
    case_id="GLOBAL_CONTROL",
    actor=actor,
    action=action,
    output_ref=detail,
    created_at=datetime.now(timezone.utc),
)  # created_at KHÔNG có trong contract

# explain.py
log_event(
    case_id=case_id,
    actor=actor,
    action="EXPLAIN_REQUESTED",
    detail="...",
    timestamp=datetime.now(timezone.utc).isoformat(),
)  # detail, timestamp KHÔNG có trong contract
```

**Vấn đề:** Contract `log_event()` (Mục 5.3) chỉ nhận `case_id, actor, action, rule_id, input_ref, output_ref, reason, sources, corpus_version`. Không có `created_at`, `detail`, hay `timestamp`. Khi Agent C implement đúng contract (đúng như họ phải làm), mọi lệnh gọi trên sẽ ném `TypeError: unexpected keyword argument`.

Vì cả hai đều nằm trong `except (ImportError, Exception): pass`, lỗi này **biến mất hoàn toàn, không log, không cảnh báo**. Kết quả thực tế: Pause, Resume, Override, Explain — bốn hành động quản trị nằm trong danh sách "không được cắt" — sẽ **ghi 0 audit event** ngay sau khi tích hợp thật, và không ai biết cho tới khi giám khảo bấm vào chọn "một hành động bất kỳ" ở Mục 6:30–7:30 của buổi chấm.

**Cách sửa:**
1. Xóa `created_at`, `detail`, `timestamp` khỏi các lệnh gọi — dùng đúng `output_ref`/`reason` như contract.
2. Đổi `case_id="GLOBAL_CONTROL"` thành `case_id` thật của case bị tác động (để tab audit lọc theo case còn tìm ra được), hoặc `None` nếu hành động thật sự không gắn với case cụ thể.
3. **Xóa toàn bộ pattern `except (ImportError, Exception): pass`** (13 chỗ trong `core/`, xem mục 6). Thay bằng tách `ImportError` (fallback hợp lệ, log ở mức `debug`) và `Exception` khác (log ở mức `error`, không nuốt).

**Cách xác minh đã sửa:** Mock `log_event` với chữ ký **chặt đúng contract** (dùng `inspect.signature` để raise nếu có kwarg lạ) → gọi cả 4 hành động quản trị → phải nhận đủ 4 event, không exception nào bị nuốt.

---

## 🟡 Nhóm 2 — Sai lệch hành vi, nên sửa trước khi coi core/ là "an toàn để tích hợp"

### 6. Pattern `except (ImportError, Exception): pass` lặp lại 13 lần trên toàn bộ `core/`

Không chỉ 2 chỗ ở mục 5 — pattern này còn ở `dispatch.py`, `evidence.py`, `question_gen.py`, `resume.py`, `pipeline.py`, `retrieval.py`, `ground_guard.py`. AGENT.md của chính đội cấm rõ: *"Cấm `except Exception: pass`."* Cần dọn toàn bộ, không riêng 2 điểm nghiêm trọng nhất.

**Cách sửa nhanh:** Tìm-thay toàn cục
```python
except (ImportError, Exception):  # noqa: BLE001, S110
    pass
```
thành
```python
except ImportError:
    logger.debug("infra.audit chưa sẵn sàng — bỏ qua ghi audit trong môi trường phát triển")
except Exception:
    logger.exception("Ghi audit thất bại — đây là lỗi thật, cần xem lại")
```

### 7. Email đa ý định: nhánh phúc khảo bị khóa bởi từ khóa thủ tục/lệ phí

**File:** `core/extract.py:112`

```python
if not is_procedure_or_fee_query and any(k in combined for k in ["phúc khảo", ...]):
    asks_appeal = any(k in combined for k in [...])
```

`is_procedure_or_fee_query` bật `True` khi có bất kỳ từ nào trong nhóm "lệ phí, bao nhiêu, thời hạn, quy trình...". Vì điều kiện `not is_procedure_or_fee_query` đứng trước, một email **vừa hỏi lệ phí vừa xin phúc khảo bài thi cá nhân** sẽ không bao giờ bật được `asks_appeal=True` — dù bên trong `combined` có cả "chấm lại bài" hay "phúc khảo bài thi". Ngoài ra hàm hiện chỉ tạo **một `RequestItem` duy nhất** cho mỗi email, nên không có chỗ để biểu diễn "một phần thường quy + một phần cần thẩm quyền" như A-24 yêu cầu.

**Lưu ý quan trọng:** đây là hàm heuristic dự phòng (`_heuristic_extract`), dùng khi `infra.llm` chưa có — tức là **100% test hiện tại đang chạy qua chính nhánh này**, không phải qua prompt LLM thật. Định nghĩa "quy tắc vàng" trong `EXTRACT_PROMPT_V1` (dùng cho LLM thật) đã đúng — vấn đề chỉ nằm ở bản heuristic.

**Cách sửa:** Heuristic nên tách theo câu/mệnh đề thay vì theo toàn bộ email gộp chung (`combined`), sinh **nhiều `RequestItem`** khi phát hiện nhiều domain/ý định khác nhau trong cùng email — đúng tinh thần A-24. Nếu không kịp làm phiên bản tách câu đầy đủ trong Sprint 1, tối thiểu: bỏ điều kiện `not is_procedure_or_fee_query`, để hai cờ được đánh giá độc lập.

### 8. Case tự thiết kế "E02" của Agent A trùng đúng chủ đề đã được chỉ định là xung đột

**File:** `tests/test_guards.py:35-38`

Case gắn nhãn `# E02: Hỏi học phí hoàn lại khi rút môn` hỏi về **tỷ lệ hoàn học phí** — đây chính xác là chủ đề PROJECT_SPEC (Mục 9.2, sau bản vá) chỉ định đặt `conflict_flag` giữa tài liệu #3 và #5. E02 thật phải là **hạn chót rút học phần**, một chủ đề khác, để không bị `conflicting_sources → ESCALATE`.

Test này đang PASS chỉ vì `corpus.api` chưa tồn tại nên rơi vào nhánh fallback nội bộ (không biết gì về `conflict_flag`). Khi B-15 (seed corpus thật) được B giao và nối vào, đây có thể trở thành đúng bug đã được vá tuần trước, tái xuất hiện qua cửa sau.

**Cách sửa:** Đổi nội dung case trong `test_guards.py` sang đúng chủ đề "hạn chót rút học phần", giữ nguyên chủ đề "hoàn học phí" cho một test case khác (nếu muốn) nhưng gắn nhãn đúng là case **không** được coi là AUTO chắc chắn cho tới khi biết corpus thật xử lý conflict thế nào.

### 9. Blocklist YAML không được đọc — im lặng dùng danh sách rút gọn hard-code

**File:** `core/question_guard.py:38`, `policies/blocklist.yaml`

YAML dùng khóa `blocked_phrases:` (11 cụm), code đọc `data.get("blocklist", DEFAULT_BLOCKLIST)` — sai tên khóa, nên luôn rơi về `DEFAULT_BLOCKLIST` cứng trong code (7 cụm). Bốn cụm bổ sung trong YAML (gồm "hỗ trợ xem xét") **không bao giờ có tác dụng**. Guard vẫn hoạt động (nhờ default list) nên đây là P2, không phải P1 — nhưng vô hiệu hóa đúng phần cấu hình mà đội tưởng là đã mở rộng.

**Cách sửa:** Đổi `data.get("blocklist", ...)` thành `data.get("blocked_phrases", ...)`.

---

## 🟢 Nhóm 3 — Vệ sinh & tuân thủ quy trình (không chặn tích hợp, nhưng ảnh hưởng Giai đoạn 0)

### 10. Một commit duy nhất cho toàn bộ Block B0–B4

`main`, `dev`, `agent-a/...` đều trỏ chung 1 commit (`6db9e4c`, 55 file, 8660 dòng). STATUS.md tự báo cáo tiến độ theo mốc `H+01` đến `H+48` nhưng git không có commit nào tương ứng từng mốc — không thể phân biệt với squash trong mắt giám khảo, dù không phải squash kỹ thuật. AGENT.md của chính đội yêu cầu *"Commit ít nhất mỗi 45 phút."*

**Cách sửa:** Từ giờ, mỗi task `[DONE]` mới = một commit riêng. Không dồn cụm nữa. Không cần rewrite lại lịch sử cũ (không squash/force-push tiếp).

### 11. `AGENT.md` và `PROJECT_SPEC.md` tồn tại 2 bản y hệt (`root/` và `regulation/`)

Xác nhận `diff` cho kết quả giống hệt tuyệt đối. `TASKBOARD.md` thì đã lệch (bản root có đánh dấu `[DONE]`, bản `regulation/` thì không) — nguy cơ hai bản tiếp tục trôi xa nhau.

**Cách sửa:** Giữ đúng một bản ở root, xóa `regulation/`, hoặc ngược lại nhưng chỉ chọn một. Nếu cần một bản "đóng băng tham chiếu", đặt tên rõ ràng khác (`regulation/SNAPSHOT_H0.md`) và ghi chú rõ đây là bản chỉ đọc, không cập nhật.

### 12. Black báo 24/32 file cần format lại; requirements.txt/README/Makefile chưa tồn tại

`black --check` liệt kê đúng 24 file trong `core/` và `tests/`. Chạy `black --line-length 100 .` một lần là xong, không tốn thời gian tranh luận.

Việc chưa có `requirements.txt`/`README.md`/`Makefile` là phần việc của Agent C (C-01), không phải lỗi của Agent A — nhưng đáng nói ở đây vì nó có nghĩa là **core/ hiện tại không có cách nào chạy thật ngoài `pytest`**. Không phải việc để sửa trong nhóm này, chỉ cần Agent A biết: mọi thứ đang test qua stub, chưa ai chạy `streamlit run` được.

---

## Checklist theo dõi

- [x] 1. Tách `ImportError` khỏi lỗi thật trong `extract.py` + `retrieval.py`
- [x] 2. `dispatch_case()` kiểm tra `is_automation_paused()`; `override_decision()` đồng bộ với `_DISPATCH_REGISTRY`
- [x] 3. Xóa ngoại lệ số "1"/"2" trong `ground_guard.py`
- [x] 4. Sửa chữ ký 5 hàm (`pause_automation`, `override_decision`, `rerun_case`, `resume_after_human`, `explain_plainly`) khớp Mục 5.3 spec + thêm `test_contract_signatures.py`
- [x] 5. Xóa `created_at`/`detail`/`timestamp` khỏi lệnh gọi `log_event`; sửa `case_id="GLOBAL_CONTROL"`
- [x] 6. Dọn toàn bộ 13 chỗ `except (ImportError, Exception): pass`
- [x] 7. Heuristic đa ý định: bỏ khóa `not is_procedure_or_fee_query`
- [x] 8. Đổi chủ đề case "E02" trong `test_guards.py` sang hạn chót rút học phần
- [x] 9. Sửa khóa đọc `blocklist.yaml` thành `blocked_phrases`
- [x] 10. Từ nay: mỗi task = một commit riêng
- [x] 11. Xóa file trùng ở `regulation/` hoặc đổi tên rõ ràng là snapshot
- [x] 12. Chạy `black --line-length 100 .` (đã format chuẩn ruff/black 100 ký tự)

Sau khi xong nhóm 🔴 (1–5), chạy lại toàn bộ test suite (116/116 passed) + ruff sạch 100%.
