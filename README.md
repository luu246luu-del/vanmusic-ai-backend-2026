# YouTube View Predictor

Dự án Machine Learning độc lập: dự đoán số lượt xem một video YouTube đạt được sau 3 ngày (~72 giờ) kể từ khi đăng, bằng **Hồi quy tuyến tính** (`sklearn.linear_model.LinearRegression`). Kèm REST API (FastAPI), giao diện thử nghiệm (Streamlit) và bộ tích hợp vào website VanMusic (menu "AI Dự Báo").

> Kết quả chỉ mang tính tham khảo. Tương quan trong dữ liệu không chứng minh quan hệ nhân quả.

## 1. Kiến trúc
```
YouTube Data API v3 -> collector/tracker -> data/raw + data/snapshots
   -> preprocessing (đặc trưng + target) -> data/processed
   -> training (Pipeline: ColumnTransformer + LinearRegression) -> models/trained/model.joblib
   -> FastAPI (/api/v1/...) -> Streamlit hoặc VanMusic (qua HTTPS, tùy chọn Firebase Function proxy)
```
VanMusic (frontend) và backend Python tách biệt, giao tiếp bằng JSON qua REST.

## 2. Vì sao là Machine Learning
Mô hình học quan hệ giữa đặc trưng video/kênh và lượt xem từ dữ liệu lịch sử (`fit`), rồi dự đoán video mới (`predict`), đánh giá trên tập Test tách theo thời gian.

## 3. Vì sao Hồi quy tuyến tính
Dự đoán giá trị số liên tục, dễ giải thích, làm baseline tốt. Nhược điểm: giả định quan hệ tuyến tính, nhạy với ngoại lai, nên dùng log (mục 4).

## 4. log1p và expm1
Lượt xem và số người đăng ký lệch rất mạnh (vài trăm đến hàng trăm triệu). Ta dùng `log1p(x) = ln(1 + x)` cho `subscriber_count`, `channel_total_views`, `avg_previous_views`, `median_previous_views` và cho target. Mô hình dự đoán `log1p(views_after_3_days)`; sau đó `expm1(y) = e^y - 1` đổi về lượt xem thật, giới hạn tối thiểu 0. MAE/RMSE được tính trên **lượt xem thật**.

Chống rò rỉ dữ liệu: `avg_previous_views` và `median_previous_views` chỉ tính từ tối đa 10 video đăng **trước** video đang xét; chia Train/Test theo thời gian; toàn bộ tiền xử lý nằm trong Pipeline và chỉ `fit` trên Train.

## 5. Lấy YouTube API Key
Google Cloud Console -> tạo project -> bật "YouTube Data API v3" -> Credentials -> Create API key. Nên giới hạn khóa theo API. Khóa chỉ để trong `.env` của backend.

## 6–16. Cài đặt và chạy
Xem `QUICKSTART_VI.md` (lệnh PowerShell chính xác cho: venv, requirements, `.env`, `channels.csv`, collector, tracker, preprocessing, training, API, Streamlit, pytest).

## 17. Đọc MAE, RMSE, R²
- **MAE**: sai số tuyệt đối trung bình (đơn vị lượt xem); dễ hiểu.
- **RMSE**: phạt nặng sai số lớn; luôn >= MAE.
- **R²**: tỷ lệ phương sai giải thích được; càng gần 1 càng tốt, có thể âm nếu kém hơn dự đoán hằng số.
- **Median Absolute Error**: ít bị ngoại lai làm lệch.

## 18. Baseline
Baseline gồm `avg_previous_views`, `median_previous_views` và median target của tập Train. Chỉ khi mô hình thắng baseline trên tập Test (MAE và RMSE) mới được coi là có giá trị. Nếu không, API sẽ thêm cảnh báo.

## 19–20. Ghép vào VanMusic
Xem `integrations/vanmusic/VANMUSIC_PATCH_GUIDE.md`. Một lệnh: `python scripts/inject_vanmusic_predictor.py --input index.html --output index-with-predictor.html`. Chạy `--dry-run` trước; script không ghi đè file gốc và không chèn trùng.

## 21. Triển khai backend
Firebase Hosting chỉ phục vụ file tĩnh của VanMusic và **không chạy được model Python**. Chạy FastAPI trên nền tảng hỗ trợ Python (Docker: `Dockerfile`, mẫu `render.yaml.example`, `railway.json.example`). Cần đưa file `models/trained/model.joblib` (và `models/reports`) vào image hoặc volume; nếu không API trả `MODEL_NOT_READY`. VanMusic gọi backend qua HTTPS.

Production: bật `REQUIRE_INTEGRATION_KEY=true`, giới hạn CORS, dùng HTTPS, không để khóa trong frontend.

## 22. CORS
`VANMUSIC_ALLOWED_ORIGINS` (phân cách bằng dấu phẩy) trong `.env`. Không dùng `*`. Mặc định gồm localhost:3000, :5173, 127.0.0.1:5500 và https://vanmusic.web.app. Thêm domain riêng khi có.

## 23–24. Firebase Function proxy và đổi URL production
Xem `integrations/vanmusic/firebase-function-example.js` và `README_VANMUSIC_INTEGRATION.md`. Trong `vanmusic-config.js` đổi `apiBaseUrl` từ `http://127.0.0.1:8000` sang địa chỉ HTTPS của backend/proxy.

## 25. Lỗi thường gặp
| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| `MODEL_NOT_READY` | Chưa chạy `run_training.py` hoặc thiếu `models/trained/model.joblib` |
| `YOUTUBE_KEY_MISSING` | Chưa điền `YOUTUBE_API_KEY` trong `.env` của backend |
| `YOUTUBE_QUOTA_EXCEEDED` | Hết quota ngày; đợi hôm sau hoặc xin tăng hạn mức |
| `INSUFFICIENT_HISTORY` | Kênh chưa có video trước đó để tính lịch sử |
| Lỗi CORS trên trình duyệt | Origin của VanMusic chưa có trong `VANMUSIC_ALLOWED_ORIGINS` |
| `UNAUTHORIZED` | Backend bật `REQUIRE_INTEGRATION_KEY` nhưng thiếu/sai `X-VanMusic-Key` |
| Training dừng vì thiếu dòng | Dưới `minimum_training_rows`; cần thêm kênh và chạy tracker lâu hơn |
| PowerShell không cho Activate | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

## 26. Quota
YouTube Data API v3 có hạn mức ngày (mặc định 10.000 đơn vị). Dự án lấy video qua uploads playlist và gọi theo batch để tiết kiệm; vẫn nên giới hạn số kênh/video và cache. Mỗi dự đoán theo kênh có gọi API (đã cache 10 phút).

## 27. Dữ liệu 72 giờ
Nhãn `views_after_3_days` chỉ được gán khi có snapshot trong khoảng 72 ± 2 giờ tuổi video. Không nội suy, không dùng tổng view hiện tại của video cũ. Vì vậy phải chạy tracker đều đặn (Task Scheduler hoặc cron) và chờ đủ dữ liệu.

## 28. Dự báo chỉ mang tính tham khảo
Mô hình không biết chất lượng nội dung, quảng bá, xu hướng hay sự kiện bất ngờ. Khoảng tham khảo (nếu có) là phân vị residual của tập Test, không phải khoảng tin cậy đảm bảo. Dữ liệu demo tổng hợp (SYNTHETIC DEMO DATA) KHÔNG DÙNG ĐỂ ĐÁNH GIÁ MÔ HÌNH THỰC TẾ.
