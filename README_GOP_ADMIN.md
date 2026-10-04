# Backend gộp: AI dự báo + VanMusic Admin

Một backend duy nhất (`python run_api.py`) phục vụ cả hai:

| Nhóm | Đường dẫn | Xác thực |
|---|---|---|
| AI dự báo (cũ) | `/api/v1/health`, `/api/v1/predict/*`, `/api/v1/model/info` ... | `X-VanMusic-Key` (nếu bật) |
| Thống kê + Admin + Bình luận YouTube (mới) | `/api/v1/vanmusic/*` | Token Admin (`Authorization: Bearer`) |

Thay đổi so với bản trước:
- `vanmusic_admin/` được chép vào gốc dự án và gắn vào `src/api/main.py`.
- CORS thêm header `Authorization` và nhận thêm `ALLOWED_ORIGINS`.
- Trang Admin lấy thông tin mô hình trực tiếp từ mô hình đang chạy (không cần `VM_MODEL_INFO_URL`).
- Đăng nhập Admin: mật khẩu Boss `van123` (đổi bằng `VM_BOSS_PASSWORD`) – web không hỏi mật khẩu lần 2.
- Thêm `firebase-admin` vào requirements; không cấu hình Firebase thì thống kê lưu bộ nhớ tạm.

Trên Render đặt: `VM_ADMIN_TOKEN_SECRET` (chuỗi ngẫu nhiên dài), `FIREBASE_CREDENTIALS_JSON` (để lưu lâu dài, đặt `VM_STORE` trống), `VANMUSIC_ALLOWED_ORIGINS`.
Trong `apiBaseUrl` của web (`vanmusic-predictor-config.js`) trỏ tới URL backend này.
