"""Cấu hình trung tâm. Đọc config.yaml, sau đó ghi đè bằng biến môi trường (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

try:  # python-dotenv là tùy chọn khi chạy test
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(os.environ.get("YVP_HOME", Path(__file__).resolve().parents[1]))

# Hằng số mặc định theo đặc tả (có thể ghi đè trong config.yaml)
TARGET_AGE_HOURS = 72
TARGET_TOLERANCE_HOURS = 2
PREVIOUS_VIDEO_COUNT = 10


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    region_code: str = "VN"
    category_id: str = "10"
    max_videos_per_channel: int = 200
    previous_video_count: int = PREVIOUS_VIDEO_COUNT
    previous_video_min_gap_hours: float = 0.0
    target_age_hours: float = TARGET_AGE_HOURS
    target_tolerance_hours: float = TARGET_TOLERANCE_HOURS
    max_channel_stats_age_hours: float = 24.0
    tracker_recent_videos: int = 15
    include_shorts: bool = False
    shorts_max_seconds: int = 60
    include_live_streams: bool = False
    feature_timezone: str = "Asia/Ho_Chi_Minh"
    train_ratio: float = 0.8
    random_state: int = 42
    minimum_training_rows: int = 200
    minimum_test_rows_for_interval: int = 20
    interval_quantiles: tuple = (0.1, 0.9)
    channels_csv: str = "data/sample/channels.csv"
    model_path: str = "models/trained/model.joblib"
    raw_data_path: str = "data/raw"
    snapshot_path: str = "data/snapshots"
    processed_data_path: str = "data/processed"
    reports_path: str = "models/reports"
    log_path: str = "logs"
    request_timeout_seconds: int = 30
    max_retries: int = 3
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list = field(default_factory=list)
    youtube_api_key: str = ""
    integration_key: str = ""
    require_integration_key: bool = False
    project_root: Path = PROJECT_ROOT

    # ---- tiện ích đường dẫn ----
    def resolve(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else Path(self.project_root) / p

    @property
    def model_file(self) -> Path:
        return self.resolve(self.model_path)

    @property
    def model_dir(self) -> Path:
        return self.model_file.parent

    @property
    def reports_dir(self) -> Path:
        return self.resolve(self.reports_path)

    @property
    def raw_dir(self) -> Path:
        return self.resolve(self.raw_data_path)

    @property
    def snapshot_dir(self) -> Path:
        return self.resolve(self.snapshot_path)

    @property
    def processed_dir(self) -> Path:
        return self.resolve(self.processed_data_path)

    @property
    def log_dir(self) -> Path:
        return self.resolve(self.log_path)

    @property
    def raw_channels_file(self) -> Path:
        return self.raw_dir / "channels_raw.csv"

    @property
    def raw_videos_file(self) -> Path:
        return self.raw_dir / "videos_raw.csv"

    @property
    def snapshots_file(self) -> Path:
        return self.snapshot_dir / "snapshots.csv"

    @property
    def processed_file(self) -> Path:
        return self.processed_dir / "training_dataset.csv"

    @property
    def quality_report_file(self) -> Path:
        return self.processed_dir / "data_quality_report.json"


def load_settings(config_path: str | Path | None = None,
                  overrides: dict | None = None,
                  load_env: bool = True) -> Settings:
    """Đọc config.yaml + .env. `overrides` (dùng cho test) có ưu tiên cao nhất."""
    root = Path(PROJECT_ROOT)
    if load_env and load_dotenv is not None:
        load_dotenv(root / ".env", override=False)

    cfg_file = Path(config_path) if config_path else root / "config.yaml"
    raw: dict[str, Any] = {}
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    api = raw.pop("api", {}) or {}
    if "host" in api:
        raw["api_host"] = api["host"]
    if "port" in api:
        raw["api_port"] = api["port"]
    if "cors_origins" in api:
        raw["cors_origins"] = api["cors_origins"]

    valid = {f.name for f in fields(Settings)}
    kwargs = {k: v for k, v in raw.items() if k in valid}
    if "interval_quantiles" in kwargs:
        kwargs["interval_quantiles"] = tuple(kwargs["interval_quantiles"])
    if "category_id" in kwargs:
        kwargs["category_id"] = str(kwargs["category_id"])

    settings = Settings(**kwargs)
    settings.project_root = root

    if not load_env:
        env = {}
    else:
        env = os.environ
    if env.get("API_HOST"):
        settings.api_host = env["API_HOST"]
    port_value = env.get("API_PORT") or env.get("PORT")  # PORT do Render/Railway cấp
    if port_value:
        settings.api_port = int(port_value)
    if env.get("VANMUSIC_ALLOWED_ORIGINS"):
        settings.cors_origins = [o.strip() for o in env["VANMUSIC_ALLOWED_ORIGINS"].split(",") if o.strip()]
    if env.get("MODEL_PATH"):
        settings.model_path = env["MODEL_PATH"]
    if env.get("REPORTS_PATH"):
        settings.reports_path = env["REPORTS_PATH"]
    settings.youtube_api_key = env.get("YOUTUBE_API_KEY", "").strip()
    settings.integration_key = env.get("VANMUSIC_INTEGRATION_KEY", "").strip()
    settings.require_integration_key = _to_bool(env.get("REQUIRE_INTEGRATION_KEY"), False)

    for k, v in (overrides or {}).items():
        setattr(settings, k, v)
    return settings
