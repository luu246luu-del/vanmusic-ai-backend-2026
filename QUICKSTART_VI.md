# QUICKSTART (Windows + VS Code + PowerShell)

Mở thư mục `youtube-view-predictor` trong VS Code, mở Terminal (PowerShell).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Nếu PowerShell chặn Activate: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` rồi chạy lại.

Mở `.env`, điền `YOUTUBE_API_KEY=` (khóa của bạn). Mở `data/sample/channels.csv` và thêm nhiều kênh nhạc (nên >= 30 kênh).

## A. Thử nhanh KHÔNG cần API key (dữ liệu GIẢ, chỉ để chạy thử luồng)
```powershell
python scripts/generate_synthetic_demo.py
python run_training.py --synthetic-demo
python run_api.py
```
Chỉ số của chạy này KHÔNG có giá trị đánh giá thực tế.

## B. Quy trình dữ liệu thật
```powershell
python run_collector.py        # thu thập kênh + video
python run_tracker.py          # chụp snapshot; chạy lặp lại nhiều lần (Task Scheduler)
python run_preprocessing.py
python run_training.py
python run_api.py
```
Mỗi video cần snapshot ở khoảng 72 giờ (±2 giờ) mới có nhãn `views_after_3_days`. Tracker phải chạy đều đặn (ví dụ mỗi 1 giờ) trong nhiều ngày, nếu không sẽ thiếu dữ liệu và training sẽ dừng.

## Terminal khác
```powershell
.venv\Scripts\Activate.ps1
streamlit run streamlit_app/app.py
```

## Kiểm thử
```powershell
pytest -v
python scripts/test_vanmusic_integration.py
python scripts/test_vanmusic_integration.py --live http://127.0.0.1:8000
```

## Ghép vào VanMusic
```powershell
python scripts/inject_vanmusic_predictor.py --input index.html --output index-with-predictor.html --dry-run
python scripts/inject_vanmusic_predictor.py --input index.html --output index-with-predictor.html --backup
Copy-Item integrations\vanmusic\vanmusic-config.example.js .\vanmusic-config.js
Copy-Item integrations\vanmusic\vanmusic-api-client.js, integrations\vanmusic\vanmusic-predictor.js .
```
Xem `integrations/vanmusic/VANMUSIC_PATCH_GUIDE.md`.
