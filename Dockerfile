FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Mô hình phải được huấn luyện trước và nằm trong models/trained/ (không có model thì /predict trả MODEL_NOT_READY).
# YOUTUBE_API_KEY, VANMUSIC_INTEGRATION_KEY, VANMUSIC_ALLOWED_ORIGINS: truyền qua biến môi trường của nền tảng, KHÔNG ghi vào image.
ENV API_HOST=0.0.0.0 REQUIRE_INTEGRATION_KEY=true
EXPOSE 8000
CMD ["python", "run_api.py"]
