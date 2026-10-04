# Kiến trúc — Gemini Video Tool

Tài liệu này giải thích dự án hoạt động thế nào, mỗi file làm gì và dữ liệu đi qua những bước nào.
Cách dùng nhanh xem `README.md`.

## 1. Tổng quan

Tool là một CLI Python dùng **Playwright** để điều khiển trang **gemini.google.com** giống như người
dùng thật: mở Gemini → chọn công cụ "Create video" → dán ảnh (và video tham chiếu) → nhập prompt →
gửi → chờ video → tải file MP4 về máy.

```
 Ảnh (người) ──┐
 Video mẫu ────┼──►  CLI (app/cli.py)  ──►  Chrome (Playwright)  ──►  gemini.google.com
 Prompt ───────┘           │                                              │
                           └────────────── output/<ảnh>-<giờ>.mp4  ◄──────┘
```

Không dùng API chính thức của Google: tool tự động hoá giao diện web, nên phụ thuộc vào nhãn các
nút trên trang (xem mục 5).

## 2. Cấu trúc thư mục

| Đường dẫn | Vai trò |
| --- | --- |
| `app/cli.py` | Điểm vào. Đọc tham số dòng lệnh, mở phiên trình duyệt, chạy từng job theo 7 bước. |
| `app/gemini.py` | Lớp `GeminiAutomation`: mọi thao tác trên trang Gemini và **toàn bộ selector**. |
| `app/browser.py` | Mở trình duyệt: kết nối Chrome đang chạy (`--attach`) hoặc profile riêng (`--account`). |
| `app/models.py` | Kiểu dữ liệu `Job`, kiểm tra ảnh/video/tên account, đọc `jobs.json`, prompt mặc định. |
| `app/media.py` | Xử lý video cục bộ: đọc độ dài MP4, cắt video > 10 giây (giới hạn của Gemini). |
| `prompts/default.txt` | Prompt mặc định khi không truyền `--prompt`. |
| `jobs.example.json` | Mẫu file chạy hàng loạt. |
| `output/` | Video kết quả. `output/.trimmed/` chứa video mẫu đã cắt (cache). |
| `screenshots/<account>/` | Ảnh chụp + HTML + danh sách nút khi lỗi; `progress.png` khi đang chờ video. |
| `accounts/<name>/` | Profile trình duyệt riêng của tool (chỉ dùng với `--account`). |

Các thư mục `output/`, `screenshots/`, `accounts/` đều bị git-ignore.

## 3. Các module và phụ thuộc

```
cli.py ──► browser.py   (mở/kết nối trình duyệt)
   │──► gemini.py    (thao tác trên trang)
   │──► media.py     (cắt video)  ──► models.py
   └──► models.py    (Job, validate, prompt)
gemini.py ──► models.py (SCREENSHOTS_DIR)
```

`gemini.py` không biết gì về CLI; `cli.py` không chứa selector nào. Khi giao diện Gemini đổi, chỉ
cần sửa `gemini.py`.

## 4. Luồng chạy một job

`main()` → kiểm tra tham số → tạo `Job` → `cmd_jobs()` → `session()` → `prepare()` → `run_job()`.

| Bước | Hàm | Việc làm |
| --- | --- | --- |
| 1/7 | `session()` → `connect_running_chrome()` hoặc `launch_profile()` | Có trình duyệt; tool mở **một tab riêng** và đưa lên trước. |
| 2/7 | `prepare()` → `ensure_authenticated()`, `account_email()` | Kiểm tra đã đăng nhập Gemini, đọc email; dừng nếu khác `--email`. |
| 3/7 | `select_video_tool()` → `_dismiss_intro()`; `prepare_reference_video()`; `attach_file()` | Chọn "Create video" trong menu "Upload & tools", đóng hộp giới thiệu "Try it", cắt video mẫu ≤ 10s, **dán** ảnh rồi video vào ô prompt. |
| 4/7 | `enter_prompt()` | Điền prompt (mặc định từ `prompts/default.txt`). |
| 5/7 | `start_generation()` | Chờ nút "Send message" bật rồi bấm; chờ có câu trả lời mới. |
| 6/7 | `wait_for_video()` | Chờ đến khi câu trả lời mới nhất có `<video>` với nguồn `https://` **và** nút Stop đã biến mất; mỗi phút chụp `progress.png`. |
| 7/7 | `download_video()` | Tải nguồn video bằng `fetch` ngay trong trang (dùng phiên đăng nhập sẵn có); dự phòng: bấm "Download video". Kiểm tra header MP4. |

Chạy hàng loạt (`batch`): các job chạy **tuần tự** trong cùng một tab; từ job thứ 2 tool mở
cuộc trò chuyện mới (`new_chat()`). Một job lỗi không làm dừng các job sau.

### Vì sao "dán" thay vì "upload"?

`attach_file()` tạo `File` trong trang rồi phát sự kiện `paste` vào ô prompt (giống Cmd+V).
Cách này không mở hộp chọn file của hệ điều hành, nên chạy ổn cả khi điều khiển Chrome thật qua
remote debugging. Mỗi file dán thành công sẽ sinh một nút `close attachment` — tool đếm nút này để
biết file đã vào.

## 5. Selector và ngôn ngữ giao diện

- Tab của tool luôn mở `https://gemini.google.com/app?hl=en` để **ép giao diện tiếng Anh**, nhờ đó
  các nhãn như "Upload & tools", "Create video", "Send message", "Download video" luôn khớp, kể cả
  khi tài khoản dùng tiếng Việt. Một số selector có thêm nhãn tiếng Việt để dự phòng.
- Selector được tìm theo **vai trò + nhãn accessibility** (`get_by_role("button", name=...)`),
  ít phụ thuộc vào class CSS hay đổi.
- Trong `gemini.py`, mỗi selector có ghi chú `VERIFIED` (đã thấy trên trang thật) hoặc `CANDIDATE`
  (chưa xác nhận).

Những điều đã kiểm chứng trên trang thật (2026-10-01):

| Hiện tượng | Cách tool xử lý |
| --- | --- |
| Không có nút "Tools" riêng; công cụ nằm trong menu "Upload & tools" | `select_video_tool()` mở menu "+" và chọn mục `menuitemcheckbox` "Create video". |
| Lần đầu dùng có hộp "Create videos … Try it" che giao diện | `_dismiss_intro()` bấm "Try it". |
| Video mẫu > 10s mở hộp cắt và khoá nút gửi | `media.prepare_reference_video()` cắt trước bằng `ffmpeg` hoặc `avconvert` (có sẵn trên macOS). |
| Trong lúc tạo có `<video>` giữ chỗ | Chỉ nhận video có nguồn `http(s)` khi nút Stop đã tắt. |
| `<video>` thật nằm ẩn trong trình phát | Tải bằng `fetch(src)` thay vì rê chuột vào video. |

## 6. Hai chế độ trình duyệt

| | `--attach` (đang dùng) | `--account <name>` |
| --- | --- | --- |
| Trình duyệt | Chrome bạn đang mở, profile **Default** | Chrome riêng do Playwright khởi động, profile trong `accounts/<name>/` |
| Đăng nhập | Dùng phiên sẵn có của bạn | Đăng nhập tay một lần — **Google thường chặn** ("This browser or app may not be secure") |
| Điều kiện | Bật `chrome://inspect/#remote-debugging` và bấm Allow khi Chrome hỏi | Không |
| Phạm vi tác động | Chỉ tab do tool mở; đóng đúng tab đó khi xong; chỉ ngắt kết nối, không tắt Chrome | Toàn bộ cửa sổ riêng |

`connect_running_chrome()` đọc file `DevToolsActivePort` trong thư mục dữ liệu Chrome để lấy cổng
và đường dẫn WebSocket, rồi gọi `connect_over_cdp`. Chrome chỉ cho thấy profile Default, nên tool
luôn làm việc trên tài khoản của profile đó; `--email` là bước kiểm tra an toàn bổ sung.

## 7. Dữ liệu đầu vào

`Job` (trong `models.py`):

| Trường | Bắt buộc | Ý nghĩa |
| --- | --- | --- |
| `image` | có | Ảnh người (png/jpg/jpeg/webp) |
| `video` | không | Video mẫu động tác (mp4/mov/webm, ≤ 100 MB) |
| `video_start` | không | Giây bắt đầu đoạn 10s khi video dài hơn |
| `prompt` | không | Mặc định: nội dung `prompts/default.txt` (hoặc `prompt_file`) |
| `output` | không | Mặc định: `output/<tên ảnh>-<giờ>.mp4` (generate) hoặc `output/job-NN-<ảnh>.mp4` (batch) |

Ví dụ `jobs.json`:

```json
[
  {"image": "./a.jpeg", "video": "./dance.mp4", "video_start": 3},
  {"image": "./b.jpeg", "prompt": "A woman dancing slowly"}
]
```

## 8. Xử lý lỗi và gỡ lỗi

- `ValidationError` (models.py): lỗi đầu vào (file không có, sai định dạng, thiếu prompt) → thoát
  mã 2, không mở trình duyệt.
- `GeminiError(operation, message)` (gemini.py): lỗi ở một bước trên trang. Timeout của Playwright
  trong `run_job()` cũng được đổi thành `GeminiError` mang tên bước.
- Mỗi `GeminiError` gọi `dump_debug()` → `screenshots/<account>/error-<giờ>.png/.html/.controls.txt`.
  File `.controls.txt` liệt kê mọi nút đang hiển thị kèm nhãn — dùng nó để sửa selector khi Gemini
  đổi giao diện.
- `FAILURE_TEXT` nhận diện câu trả lời từ chối/hết quota của Gemini để báo lỗi sớm thay vì chờ hết
  thời gian.
- `--keep-open-on-error` giữ trạng thái để xem trước khi đóng; `-v` bật log chi tiết.

## 9. Mở rộng

- **Đổi prompt mặc định:** sửa `prompts/default.txt`.
- **Gemini đổi nhãn nút:** chạy lại, mở `.controls.txt`, cập nhật hằng số tương ứng ở đầu
  `gemini.py` và đổi ghi chú thành `VERIFIED`.
- **Thêm thao tác mới** (ví dụ chọn khung dọc 9:16): thêm selector + phương thức trong
  `GeminiAutomation`, gọi nó trong `run_job()` và thêm tham số ở `build_parser()`.

## 10. Giới hạn và rủi ro

- Phụ thuộc giao diện web Gemini; giao diện đổi thì selector có thể phải sửa.
- Cần tài khoản có quyền tạo video; mỗi video trừ vào quota hằng ngày của tài khoản.
- Video mẫu tối đa 10 giây; video kết quả hiện là khung ngang 16:9 (mặc định của Gemini).
- Kết quả có thể trộn ngoại hình người trong video mẫu với người trong ảnh — đây là hành vi của
  model, chỉ điều chỉnh được qua prompt/đầu vào.
- Tự động hoá giao diện web có thể không phù hợp điều khoản của Google; dùng với một tài khoản,
  theo dõi được, và tắt remote debugging khi không dùng.
