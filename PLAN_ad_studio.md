# Plan v2 — Ad Studio: chọn Prompt theo loại quảng cáo + UI mới có sidebar

## 1. Yêu cầu (đã chốt)

1. **Mỗi loại quảng cáo có prompt riêng**, không còn prompt chung / system prompt.
   Ví dụ: "Quần áo", "Mỹ phẩm", "Túi xách", "Nhảy"…
2. Khi tạo video: người dùng **chọn prompt trong ô Select** → **chỉ nhập Tên sản phẩm** → upload ảnh
   → thêm vào hàng đợi. Không phải tự viết prompt.
3. Prompt "Nhảy" là một prompt riêng trong danh sách (cần ảnh người + video nhảy mẫu).
4. Người dùng **tự thêm / sửa / xoá prompt** trong trang "Thư viện Prompt".
5. **Làm lại UI**: navbar trên + **sidebar trái** để chuyển trang, thay cho giao diện hiện tại.

## 2. Luồng người dùng

```
Tạo video
  ① Chọn prompt   [ Select: Mỹ phẩm – cận cảnh sản phẩm      ▾ ]
  ② Tên sản phẩm  [ Son kem lì Maybelline Superstay ]       ← chỉ hiện nếu prompt có {{product_name}}
  ③ Upload        [ Ảnh sản phẩm ]                          ← ô upload hiện theo prompt đã chọn
  ④ Xem trước     prompt đã thay tên sản phẩm (chỉ đọc, có nút "Sửa riêng cho lần này")
                  [ Thêm vào hàng đợi ]   [ Chạy ngay ]
```

Đổi prompt trong Select → các ô ở ② ③ tự đổi theo.

## 3. Mô hình Prompt

Lưu ở `data/prompts.json`. Mỗi prompt độc lập, tự chứa toàn bộ nội dung:

```json
{
  "id": "pr_cosmetic_closeup",
  "name": "Mỹ phẩm – cận cảnh sản phẩm",
  "category": "cosmetics",           // clothes | cosmetics | bag | shoes | dance | food | other
  "content": "Create a premium cosmetic advertisement video for {{product_name}}. ...",
  "inputs": {
    "model_image":   false,          // ảnh người mẫu
    "product_image": true,           // ảnh sản phẩm
    "ref_video":     false           // video mẫu (dùng cho Nhảy)
  },
  "created_at": "...", "updated_at": "..."
}
```

- Biến duy nhất: **`{{product_name}}`**. Prompt có biến này → form hiện ô "Tên sản phẩm" (bắt buộc).
  Prompt không có (vd Nhảy) → ẩn ô đó.
- `inputs` quyết định ô upload nào hiện ra và **thứ tự dán vào Gemini**: người mẫu → sản phẩm → video.
- Thay biến bằng `str.replace` đơn giản, không dùng template engine.

### Prompt có sẵn lần đầu (seed)

| Tên | Loại | Ảnh người | Ảnh SP | Video | Tên SP |
| --- | --- | :-: | :-: | :-: | :-: |
| Nhảy – theo video mẫu | dance | ✔ | | ✔ | |
| Quần áo – người mẫu trình diễn | clothes | ✔ | | | ✔ |
| Túi xách – người mẫu cầm túi | bag | ✔ | ✔ | | ✔ |
| Túi xách – xoay 360° studio | bag | | ✔ | | ✔ |
| Mỹ phẩm – cận cảnh sản phẩm | cosmetics | | ✔ | | ✔ |
| Giày – cận cảnh bước đi | shoes | ✔ | ✔ | | ✔ |

"Nhảy" lấy nguyên nội dung `prompts/default.txt` hiện tại.

## 4. Job trong hàng đợi (mở rộng `data/pairs.json`)

| Trường | Ý nghĩa |
| --- | --- |
| `prompt_id` | prompt đã chọn (pair cũ → `legacy`) |
| `product_name` | tên sản phẩm đã nhập |
| `model_image`, `product_image`, `video` | đường dẫn file upload (`image` cũ → `model_image`) |
| `prompt` | **prompt cuối đã thay tên** (lưu cứng) — sửa prompt sau này không ảnh hưởng job cũ |

Bỏ `use_default_prompt` và nút "Use system default prompt".

## 5. Backend (Flask)

| File | Việc |
| --- | --- |
| `app/prompt_store.py` (mới) | CRUD `data/prompts.json` (ghi atomic như `store.py`), seed 6 prompt, `render(prompt, product_name)` |
| `app/store.py` | thêm trường mới; chuyển pair cũ khi load (`image` → `model_image`, `prompt_id="legacy"`) |
| `app/models.py` | `Job.files: list[Path]` theo thứ tự người mẫu → sản phẩm → video |
| `app/runner.py` | `_job_from_pair()` lấy `files` + `prompt` đã lưu; bỏ nhánh prompt mặc định |
| `app/gemini.py` | không đổi (đã dán được nhiều file) |
| `app/web.py` | API dưới đây + serve frontend mới |

```
GET    /api/prompts              danh sách (cho Select, nhóm theo category)
POST   /api/prompts              thêm
PUT    /api/prompts/<id>         sửa
DELETE /api/prompts/<id>         xoá (cảnh báo nếu còn job đang chờ dùng nó)
POST   /api/prompts/<id>/duplicate
POST   /api/pairs                {prompt_id, product_name, model_image?, product_image?, video?, video_start?, account?}
                                 → server kiểm tra đủ file theo `inputs`, thay tên, lưu prompt cuối
```

## 6. UI mới

Stack theo chuẩn dự án: **React + TypeScript + Vite + shadcn/ui + Tailwind + lucide-react**,
form **React Hook Form + Zod**, bảng **TanStack Table**. Code ở `web/`, build ra `web/dist`,
Flask serve → vẫn chạy 1 lệnh `python -m app.web`. Có Light/Dark.

### Khung chung

```
┌───────────────────────────────────────────────────────────────────────┐
│ ▣ Ad Studio                     ● 2 đang chạy · 5 chờ   [Run All] ☾ │  ← Navbar
├──────────────────┬────────────────────────────────────────────────────┤
│ TẠO              │                                                    │
│  ✦ Tạo video     │                                                    │
│ QUẢN LÝ          │              Nội dung trang                         │
│  ☰ Hàng đợi   5  │                                                    │
│  ▶ Đang chạy  2  │                                                    │
│  ▦ Thư viện video│                                                    │
│ CẤU HÌNH         │                                                    │
│  ✎ Thư viện Prompt│                                                   │
│  👤 Tài khoản     │                                                    │
│  ⚙ Cài đặt       │                                                    │
│                  │                                                    │
│ [« thu gọn]      │                                                    │
└──────────────────┴────────────────────────────────────────────────────┘
```

Dùng shadcn **Sidebar** (thu gọn còn icon; trên mobile thành **Sheet**), Badge đếm số job.

### Từng trang

| Trang | Nội dung | Thành phần shadcn |
| --- | --- | --- |
| **Tạo video** | Trái: form (Select prompt nhóm theo loại → Tên SP → ô upload kéo-thả có ảnh xem trước → chọn account auto/cụ thể). Phải: Card xem trước prompt + ảnh. Nút "Thêm vào hàng đợi" / "Chạy ngay" | Form, Select (SelectGroup), Input, Card, Button, Badge, Collapsible "Sửa prompt lần này" |
| **Hàng đợi** | Bảng: ảnh nhỏ · Prompt · Tên SP · Account · Trạng thái · Thao tác (Chạy / Thử lại / Xoá). Lọc theo trạng thái & loại. Bấm dòng → Sheet bên phải: chi tiết, log realtime, video kết quả | TanStack Table + Table, Tabs lọc, Badge, DropdownMenu, Sheet, ScrollArea |
| **Đang chạy** | Mỗi job đang chạy 1 Card: account, bước `[n/7]` (Progress), thời gian, dòng log cuối, nút Dừng | Card, Progress, Button, AlertDialog |
| **Thư viện video** | Lưới video đã xong, lọc theo loại/prompt, bấm để xem lớn + tải về | Card, Dialog, Select, Button |
| **Thư viện Prompt** | Lưới Card theo loại (Tabs: Tất cả / Quần áo / Mỹ phẩm / Túi / Nhảy…). Mỗi Card: tên, loại, icon ô cần upload, đoạn đầu prompt; menu Sửa / Nhân bản / Xoá. Nút "Thêm prompt" mở Sheet editor: Tên, Loại, 3 Switch (ảnh người / ảnh SP / video), Textarea nội dung + nút "Chèn {{product_name}}" | Card, Tabs, Sheet, Form, Switch, Textarea, AlertDialog |
| **Tài khoản** | Port màn hiện tại: bảng account, trạng thái, Đăng nhập / Quét / Xoá, Dialog thêm | Table, Dialog, Badge |
| **Cài đặt** | Số trình duyệt song song, delay khởi động, headless | Input, Switch |

Loading dùng `Skeleton`; danh sách trống dùng Card + icon + Button ("Chưa có prompt — Thêm prompt").

## 7. Các giai đoạn

| GĐ | Việc | Xong khi |
| --- | --- | --- |
| **0. Thử nhanh** | Thử tay Gemini "Create video" với 2 ảnh (người + túi) | Biết prompt "Túi – người mẫu cầm túi" chạy được hay phải dùng 1 ảnh |
| **1. Backend** | `prompt_store`, API prompts, mở rộng pair + chuyển dữ liệu cũ, runner đọc `files` | Tạo job "Mỹ phẩm" qua API → ra video |
| **2. Khung UI** | Vite + React + shadcn, Navbar + Sidebar, routing, theme | Mở web thấy sidebar, chuyển trang được |
| **3. Trang chính** | Tạo video, Thư viện Prompt | Chọn prompt + nhập tên SP + upload → job vào hàng đợi |
| **4. Port màn cũ** | Hàng đợi (log SSE), Đang chạy, Thư viện video, Tài khoản, Cài đặt | Làm được mọi việc UI cũ làm → xoá `templates/index.html` |
| **5. Tuỳ chọn** | Tạo hàng loạt (1 prompt × nhiều sản phẩm), sinh caption TikTok, khung 9:16 | |

## 8. Rủi ro

- Gemini có thể chỉ nhận 1 ảnh khi tạo video → GĐ 0 kiểm tra trước.
- Thêm Node/Vite: phải `npm run build` trước khi chạy; ghi rõ trong README.
