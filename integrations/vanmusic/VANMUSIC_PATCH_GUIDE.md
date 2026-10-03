# Hướng dẫn ghép AI Dự Báo vào VanMusic (index.html)

Có 2 cách: **Cách 1 (nhanh)** chạy một lệnh; **Cách 2** dán tay theo marker. Nên đọc cả hai để biết script làm gì.

## Cách 1 – Một lệnh (khuyến nghị)

```powershell
python scripts/inject_vanmusic_predictor.py --input index.html --output index-with-predictor.html --dry-run
python scripts/inject_vanmusic_predictor.py --input index.html --output index-with-predictor.html --backup
```

- `--dry-run`: chỉ kiểm tra tìm được đủ vị trí, không ghi file.
- Script **không ghi đè** `index.html` gốc. Nếu file đã có marker `VANMUSIC AI PREDICTOR`, script dừng, không chèn lần hai.
- Nếu không tìm thấy vị trí nào, script dừng và nói rõ thiếu gì. Khi đó dùng Cách 2.
- Sau khi chạy, copy 3 file JS cạnh HTML: `vanmusic-config.js` (sao chép từ `vanmusic-config.example.js`), `vanmusic-api-client.js`, `vanmusic-predictor.js`.

> Script được kiểm thử trên một index.html mẫu có cấu trúc tương tự VanMusic. Với index.html thật, luôn chạy `--dry-run` và mở file kết quả để kiểm tra trước khi dùng.

## Cách 2 – Dán tay theo từng bước

Dùng **Ctrl+F** để tìm các vị trí.

**BƯỚC A – Sao lưu.** Copy `index.html` thành `index.backup.html`.

**BƯỚC B – CSS.** Ctrl+F tìm `</style>`. Dán nội dung `vanmusic-predictor.css` NGAY TRƯỚC thẻ `</style>` cuối cùng (hoặc thêm `<link rel="stylesheet" href="vanmusic-predictor.css">` trong `<head>`).

**BƯỚC C – Menu máy tính.** Ctrl+F tìm `switchTab('chart'` (mục Bảng Xếp Hạng). Dán khối trong `vanmusic-menu-items.html` (chọn phiên bản sidebar hoặc menu ngang) NGAY SAU mục cuối cùng của nhóm menu. Sao chép class của mục cũ cho giống giao diện. Điểm cần khớp: `onclick="switchTab('predictor', event)"`.

**BƯỚC D – Menu điện thoại.** Ctrl+F tìm `mobile-menu-list`. Dán `vanmusic-mobile-menu-item.html` vào trong danh sách đó, sau mục cuối. Điểm cần khớp: `onclick="openMobileSection('predictor')"`.

**BƯỚC E – Trang tính năng.** Ctrl+F tìm `main-content`. Dán toàn bộ `vanmusic-section.html` (từ `<!-- VANMUSIC AI PREDICTOR START -->` đến `<!-- VANMUSIC AI PREDICTOR END -->`) bên trong `main-content`, ngay sau `page-section` cuối cùng (cạnh `tab-home`, `tab-chart`...).

**BƯỚC F – JavaScript.** Ctrl+F tìm `</body>`. Dán NGAY TRƯỚC nó, đúng thứ tự:

```html
<script src="vanmusic-config.js"></script>
<script src="vanmusic-api-client.js"></script>
<script src="vanmusic-predictor.js"></script>
```

**BƯỚC G – Hook trong switchTab.** Ctrl+F tìm `function switchTab`. Thêm ngay dòng đầu trong thân hàm (đổi `tabName` cho đúng tên tham số đầu tiên, ví dụ `t`):

```js
if (tabName === 'predictor' && window.initializeVanMusicPredictor) { window.initializeVanMusicPredictor(); }
```

Không sửa gì khác trong `switchTab`. Nếu `switchTab` ẩn/hiện trang bằng `document.getElementById('tab-' + tabName)`, `tab-predictor` sẽ tự hoạt động.

**BƯỚC H – Kiểm tra local.**
1. Chạy backend: `python run_api.py` (cổng 8000).
2. Mở VanMusic bằng Live Server (`http://127.0.0.1:5500`, đã có trong CORS mặc định).
3. Bấm "AI Dự Báo" trên menu máy tính và menu ba gạch điện thoại; kiểm tra các mục Trang Chủ, Bảng Xếp Hạng, Lịch Sử Nghe, Playlist vẫn hoạt động, player vẫn chạy.
4. Nếu chưa huấn luyện mô hình, trang phải hiện: "Hệ thống dự báo đang được chuẩn bị. Vui lòng thử lại sau." (không có số 0 giả).

**BƯỚC I – Production.** Sửa `vanmusic-config.js`: `apiBaseUrl` sang địa chỉ HTTPS của backend (hoặc của Firebase Function proxy). Xem README_VANMUSIC_INTEGRATION.md.

## Cảnh báo bảo mật
- Nếu index.html hiện tại của bạn đang chứa API key/khóa nhạy cảm trong JavaScript, hãy xử lý riêng (xoay khóa, giới hạn theo domain). Tính năng mới **không** dùng và **không** sao chép các khóa đó.
- Không đặt YouTube API Key trong frontend. Chỉ backend giữ khóa này.
- Production: để `integrationKey` trống ở frontend và dùng Firebase Function proxy giữ khóa.
