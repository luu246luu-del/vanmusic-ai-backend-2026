# TRẠNG THÁI DỰ ÁN

Đã hoàn thành đủ các file theo yêu cầu (backend ML, API, Streamlit, bộ tích hợp VanMusic, script inject, tài liệu, Docker).

## Đã kiểm tra trong môi trường tạo dự án (không có Internet)
- Huấn luyện bằng dữ liệu GIẢ chạy được (`run_training.py --synthetic-demo`).
- Các script Python biên dịch được; JS qua `node --check`; hàm thuần của JS (parseChannelInput, convertDurationToSeconds, formatViewCountVI) chạy đúng.
- Script inject chạy đúng trên một index.html MẪU (chèn đủ 6 vị trí, chặn chèn lần hai, dry-run, backup).
- Kiểm tra tĩnh bộ tích hợp: đủ file, CSS chỉ có class `vm-predict-`, không có YouTube API Key.

## CHƯA chạy được ở đây - bạn cần chạy trên máy của mình
- `pytest -v` (thiếu fastapi/pytest/httpx trong môi trường tạo). Bản trước ghi nhận 36 test pass cho phần ML; test_api.py và test_vanmusic_integration.py chưa được chạy.
- Thu thập dữ liệu YouTube thật (cần API Key và mạng).
- Script inject trên index.html THẬT của VanMusic: luôn chạy `--dry-run` trước và kiểm tra kết quả.
- Giao diện AI Dự Báo trên trình duyệt (chưa xem bằng mắt); Firebase Function chưa deploy.
- Chưa có mô hình huấn luyện trên dữ liệu thật: bạn cần thêm kênh vào channels.csv, chạy collector/tracker đủ lâu rồi training.
