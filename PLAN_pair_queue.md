# Plan — Pair Queue UI (Save → Queue → Bulk Run)

## Goal

User upload **image + optional video + prompt** thành 1 "pair", pair lưu lại chưa chạy. UI hiển thị
queue, có thể:

- Bấm **Run** trên 1 pair cụ thể.
- Bấm **Run All** để chạy tuần tự/headless toàn bộ queue.
- Theo dõi trạng thái realtime (queued / running / done / failed).
- Xem lại các pair đã chạy (kèm output video) ở panel bên phải.

Layout: **left bar** = queue & controls, **right bar** = content (chi tiết / output gallery).
shadcn-style components, top navbar.

---

## Kiến trúc

```
┌────────────────────────────────────────────────────────────┐
│  Navbar  (logo · status · "Run All" · "Add Pair")          │
├──────────────┬─────────────────────────────────────────────┤
│              │                                             │
│  LEFT        │  RIGHT                                      │
│  ─────────   │  ─────────                                  │
│  • Queue     │  Tab strip: [Selected]  [Done gallery]      │
│    cards     │                                             │
│    (image +  │  Tab "Selected":                             │
│    video +   │    - preview lớn (image + video + prompt)   │
│    prompt +  │    - log panel                              │
│    Run btn)  │    - output video + Download                 │
│              │                                             │
│  Stats:      │  Tab "Done":                                │
│  queued: 5   │    - grid thumbnail các pair đã done        │
│  done: 12    │                                             │
│  failed: 1   │                                             │
│              │                                             │
└──────────────┴─────────────────────────────────────────────┘
```

JSON lưu trong `data/`:

```
data/
├── pairs.json           # danh sách pair + status + output path
└── uploads/
    ├── img-001.jpeg
    └── vid-001.mp4
```

`pairs.json` schema:

```json
[
  {
    "id": "p_abc123",
    "image": "uploads/img-001.jpeg",
    "video": "uploads/vid-001.mp4",
    "video_start": 0,
    "prompt": "A woman dancing",
    "use_default_prompt": false,
    "status": "queued",
    "created_at": "2026-10-01T19:00:00",
    "started_at": null,
    "finished_at": null,
    "exit_code": null,
    "output": null,
    "log": []
  }
]
```

`log` lưu 200 dòng cuối để mở lại UI vẫn xem được log cũ; phần log đầy đủ stream qua SSE.

---

## Thay đổi theo file

### 1. `app/store.py` (mới)

Module quản lý pair state. API:

- `list_pairs() -> list[dict]`
- `add_pair(image_path, video_path, prompt, use_default, video_start) -> dict`
- `update_pair(pair_id, **fields) -> dict`
- `delete_pair(pair_id) -> None`
- `append_log(pair_id, line, max_lines=200) -> None`
- `save()` / `load()` — atomic write (write tmp → rename) để không hỏng khi Flask restart.

Thread-safe bằng `threading.RLock`. Persist ngay sau mỗi mutation (trừ log append, debounce 1s).

### 2. `app/runner.py` (mới)

Module chạy pipeline 1 pair độc lập. **Không** gọi `app.cli.main()` trực tiếp (vì `cli.main()` thiết kế
cho CLI, in ra stdout). Thay vào đó copy logic từ `cli.session()` + `cli.prepare()` + `cli.run_job()`
vào 1 hàm `run_pair(pair: dict, *, headless: bool, log_cb: Callable[[str], None]) -> int`:

- Tạo Chrome context riêng bằng `playwright.async_api.async_playwright()`:
  - Nếu `pair["mode"] == "attach"`: dùng `connect_running_chrome()` (giống CLI hiện tại).
  - Nếu `pair["mode"] == "account"`: dùng `launch_profile(pw, account, channel=channel, headless=True)`
    → cần thêm option `headless` vào `launch_profile()`.
- Mỗi pair = 1 context/tab riêng → fail độc lập.
- `log_cb` push từng dòng vào `_jobs[pair_id]["log"]` (queue per-pair).
- Trả về `exit_code` (0 = done, khác = fail) + `output_path`.

### 3. `app/browser.py` (sửa)

Thêm parameter `headless: bool = False` vào `launch_profile()`:

```python
async def launch_profile(pw, name: str, channel: str = "chrome", headless: bool = False):
    ...
    browser = await pw.chromium.launch(
        channel=channel,
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"] if headless else [],
    )
```

Headless chỉ áp dụng khi chạy qua runner (bulk) — mode `attach` luôn có UI vì kết nối Chrome
thật.

### 4. `app/web.py` (sửa)

Thêm endpoints:

| Method | Path | Chức năng |
|---|---|---|
| GET | `/api/pairs` | list tất cả pair |
| POST | `/api/pairs` | tạo pair mới (form: image_id, video_id?, prompt, use_default, video_start) |
| DELETE | `/api/pairs/<id>` | xoá pair (đang running → 409) |
| PATCH | `/api/pairs/<id>` | sửa prompt/video_start trước khi chạy |
| POST | `/api/pairs/<id>/run` | chạy 1 pair, trả job_id |
| POST | `/api/pairs/run-all` | chạy tuần tự các pair queued, trả batch_id |
| GET | `/api/stream/<job_id>` (đã có, mở rộng) | SSE: log + status + output path |

**Quy trình Run All (background headless):**

1. UI gọi `POST /api/pairs/run-all`.
2. Server spawn 1 daemon thread `batch_runner(batch_id)`.
3. Thread lặp qua `store.list_pairs(status="queued")`, với mỗi pair:
   - Set status → `running`.
   - Gọi `runner.run_pair(pair, headless=True)` → push log realtime.
   - Set status → `done` / `failed`, lưu `output` path.
   - Sleep 2s giữa các pair (tránh rate limit).
4. Thread tồn tại độc lập — **đóng UI Flask vẫn chạy** nếu batch đã bắt đầu (vì thread là daemon
   của process `app.web`). Nếu user muốn chạy ngầm kể cả khi tắt server hoàn toàn → cần tách thành
   `app/daemon.py` chạy riêng (xem §"Tuỳ chọn nâng cao").

Run 1 pair: giống nhưng chỉ lặp 1 lần, không sleep.

### 5. `templates/index.html` (rewrite)

**Top navbar** (shadcn `NavigationMenu` style):

- Logo "Gemini Video Tool"
- Status pill: "5 queued · 1 running · 12 done · 1 failed"
- Button "Run All" (primary, lớn — đúng yêu cầu "button to để chạy tất cả 1 lúc")
- Button "+ Add Pair" (mở dialog `Dialog` shadcn-style)

**Left bar** (~ 360px):

- Stats mini (4 ô nhỏ: queued/running/done/failed).
- Scroll list `Card` cho mỗi pair:
  - Thumbnail image (16:9) + small badge "video" nếu có.
  - Tên file image.
  - Status badge (color-coded).
  - Nút "Run" riêng (icon play, nhỏ).
  - Nút "⋯" menu (Edit prompt, Delete).
- Empty state: "No pairs yet — click + Add Pair".

**Right bar** (flex-1):

- Khi **chưa chọn pair**: hiện grid thumbnail Done gallery (giống UI cũ).
- Khi **chọn 1 pair**: 2 tab shadcn-style `Tabs`:
  - **Detail**: preview lớn (image + video nếu có), prompt (read-only nếu đã chạy, editable nếu queued), log panel realtime, output player nếu done.
  - **Settings** (chỉ queued): sửa prompt, video_start, mode, account.

**Add Pair dialog** (`Dialog` shadcn-style):

- Reuse form upload cũ (image input + video input + prompt textarea + use_default).
- Preview thumbnail ngay khi chọn file.
- Submit → POST `/api/pairs`.

**Components shadcn-style dùng (custom Tailwind, không cần npm):**

- `Button` (variant: default, ghost, destructive)
- `Card` (border + rounded-xl)
- `Badge` (status colors)
- `Dialog` (modal với backdrop blur)
- `Tabs` (active underline)
- `Input` / `Textarea`
- `NavigationMenu` (navbar ngang)

---

## Tuỳ chọn nâng cao (defer)

Nếu sau này muốn **chạy ngầm kể cả khi tắt Flask UI hoàn toàn**:

- Tách `app/daemon.py` riêng: HTTP server siêu nhỏ chỉ phục vụ lệnh run/stop, chạy độc lập.
- Hoặc dùng subprocess: `python -m app.runner --pair-id p_xxx` → chạy nền, exit khi xong.

Hiện tại thread daemon trong Flask đủ dùng cho "không cần focus / không cần mở UI đang canh" — miễn
là process Flask còn sống.

---

## Steps triển khai (thứ tự)

1. **`app/store.py`** — CRUD pair + persist JSON. Test bằng script nhỏ.
2. **`app/browser.py`** — thêm `headless=True` vào `launch_profile`.
3. **`app/runner.py`** — `run_pair()` async, copy logic từ `cli.py`, dùng `log_cb`. Test 1 pair thủ
   công.
4. **`app/web.py`** — thêm endpoints `/api/pairs`, `/run`, `/run-all`, mở rộng SSE per-pair.
5. **`templates/index.html`** — rewrite layout 2 cột + navbar + dialog add pair + shadcn-style
   components. Theo dõi SSE realtime cập nhật card trái + log phải.
6. **Smoke test end-to-end**: tạo 2-3 pair, bấm Run All, kiểm tra file MP4 xuất hiện trong `output/`
   và card chuyển sang Done gallery.
7. **Polish**: confirm dialog xoá pair, retry failed pair (set status về queued), empty states.

---

## Rủi ro

- **Headless + Google login**: profile đã login rồi (`accounts/<name>/`) nên headless OK; nếu dùng
  `--attach` thì buộc phải có Chrome thật mở remote-debug.
- **Rate limit Gemini**: nếu queue > 20 pair, cần sleep dài hơn giữa các pair (configurable).
- **JSON corruption**: dùng atomic write (tmp file + rename) để tránh mất data khi crash giữa lúc
  save.
- **Log memory**: nếu job log quá dài, giữ tối đa 200 dòng cuối trong pair (full log lưu file riêng
  trong `logs/<pair_id>.log`).