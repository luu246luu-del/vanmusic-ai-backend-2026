import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.data.synthetic_demo import generate_synthetic_dataset  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return load_settings(load_env=False, overrides={
        "project_root": tmp_path, "model_path": "models/model.joblib", "reports_path": "models/reports",
        "minimum_training_rows": 100, "cors_origins": ["http://localhost:5173", "https://vanmusic.web.app"],
        "youtube_api_key": "", "require_integration_key": False, "integration_key": ""})


@pytest.fixture(scope="session")
def synthetic_df():
    return generate_synthetic_dataset(n_rows=400, n_channels=20, seed=1)


@pytest.fixture()
def trained_settings(settings, synthetic_df):
    """Settings có sẵn mô hình đã huấn luyện trên DỮ LIỆU GIẢ (chỉ dùng cho test)."""
    from src.ml.train import train_model
    train_model(synthetic_df, settings, synthetic=True)
    return settings


class FakeProvider:
    """Giả lập YouTube (không gọi mạng)."""

    def __init__(self, n_videos=12, exists=True, error=None):
        self.n_videos, self.exists, self.error = n_videos, exists, error

    def resolve_channel(self, text):
        if self.error:
            raise self.error
        if text.startswith("http") and "youtube.com" not in text:
            raise ValueError("Định dạng kênh không hợp lệ.")
        return "UC" + "a" * 22

    def get_channel(self, channel_id):
        from src.youtube.client import YouTubeNotFoundError
        if self.error:
            raise self.error
        if not self.exists:
            raise YouTubeNotFoundError("x")
        return {"channel_id": channel_id, "channel_title": "Kênh thử", "channel_published_at": pd.Timestamp("2015-01-01", tz="UTC"),
                "subscriber_count": 500000, "channel_video_count": 300, "channel_total_views": 90_000_000}

    def get_recent_videos(self, channel_id, limit=50):
        if self.error:
            raise self.error
        base = pd.Timestamp("2026-01-01", tz="UTC")
        rows = [{"video_id": f"v{i}", "published_at": base - pd.Timedelta(days=7 * i), "view_count": 100000 + i * 1000,
                 "duration_seconds": 240, "has_live_streaming_details": False} for i in range(self.n_videos)]
        return pd.DataFrame(rows)

    def collect(self, channel_id, max_videos):
        return {"channel_id": channel_id, "videos_fetched": 0, "raw_rows_added": 0}


VALID_REQUEST = {
    "current_view_count": 15000,
"current_video_age_hours": 4.0,
"recent_views_per_hour": 2500.0,
    "channel_id": "UClyA28-01x4z60eWQ2kiNbA", "title": "Tên video dự kiến", "description": "Mô tả",
    "duration_seconds": 260, "tags": ["music", "mv"], "publish_datetime": "2026-10-02T20:00:00+07:00",
    "category_id": "25", "is_hd": True, "has_caption": False, "user_id": None, "client_request_id": None}
