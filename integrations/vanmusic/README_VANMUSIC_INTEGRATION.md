# Tích hợp VanMusic – tổng quan

```
VanMusic (Firebase Hosting)  --->  Firebase Cloud Function (proxy, giữ khóa)  --->  Prediction API (FastAPI, Python)
        frontend, tĩnh                    tùy chọn nhưng khuyến nghị                       model + YouTube API Key
```

- Firebase Hosting chỉ phục vụ file tĩnh; **không chạy được** Python/model. Backend FastAPI phải chạy trên nơi hỗ trợ Python (Render, Railway, Cloud Run, VPS...).
- Frontend chỉ biết `apiBaseUrl`. YouTube API Key chỉ nằm ở backend.

## Các file
| File | Vai trò |
|---|---|
| `vanmusic-section.html` | HTML trang `tab-predictor` |
| `vanmusic-menu-items.html` / `vanmusic-mobile-menu-item.html` | Mục menu máy tính / điện thoại |
| `vanmusic-predictor.css` | CSS, mọi class có tiền tố `vm-predict-` |
| `vanmusic-api-client.js` | `VanMusicPredictionClient.predictYouTubeViews()` (timeout, AbortController) |
| `vanmusic-predictor.js` | Điều khiển giao diện, namespace `window.VanMusicPredictor` |
| `vanmusic-config.example.js` | `apiBaseUrl`, `integrationKey`, `timeoutMs` |
| `api-contract.json`, `vanmusic-api-client.ts` | Hợp đồng API và kiểu TypeScript |
| `firebase-function-example.js` | Proxy giữ Integration Key bằng Firebase Secret |
| `example.html` | Trang demo độc lập |

## Chế độ chạy
- **Local:** `REQUIRE_INTEGRATION_KEY=false`, `integrationKey: ""`.
- **Production khuyến nghị:** backend `REQUIRE_INTEGRATION_KEY=true`; frontend gọi Firebase Function; Function gắn header `X-VanMusic-Key` lấy từ Firebase Secret. Frontend không giữ khóa nào.
- Đặt `VANMUSIC_ALLOWED_ORIGINS` đúng domain VanMusic (không dùng `*`).

## Kiểm thử
`python scripts/test_vanmusic_integration.py` (thêm `--live http://127.0.0.1:8000` khi API đang chạy).
