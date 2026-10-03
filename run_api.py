"""Chạy REST API:  python run_api.py   (docs: http://127.0.0.1:8000/docs)"""
import uvicorn

from src.config import load_settings

if __name__ == "__main__":
    s = load_settings()
    uvicorn.run("src.api.main:create_app", factory=True, host=s.api_host, port=s.api_port, log_level="info")
