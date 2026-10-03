"""Logic dự đoán: lấy dữ liệu kênh, dựng đặc trưng, gọi mô hình, đóng gói kết quả."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.api.security import ApiException
from src.config import Settings
from src.data.feature_engineering import (build_feature_row, channel_age_days, filter_history,
                                          parse_duration_seconds, previous_video_stats, publish_time_features)
from src.data.schemas import DEMO_BANNER
from src.logger import get_logger
from src.ml.predictor import ModelNotReadyError, ViewPredictor
from src.youtube.client import (MissingAPIKeyError, YouTubeAPIError, YouTubeClient, YouTubeNotFoundError,
                                YouTubeQuotaError)

log = get_logger(__name__)


class ChannelProvider(Protocol):
    def resolve_channel(self, text: str) -> str: ...
    def get_channel(self, channel_id: str) -> dict: ...
    def get_recent_videos(self, channel_id: str, limit: int = 50) -> pd.DataFrame: ...
    def collect(self, channel_id: str, max_videos: int) -> dict: ...


class YouTubeProvider:
    """Lấy dữ liệu trực tiếp từ YouTube Data API v3 (có cache TTL để tiết kiệm quota)."""

    def __init__(self, client: YouTubeClient, settings: Settings, ttl_seconds: int = 600):
        self.client, self.settings, self.ttl = client, settings, ttl_seconds
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _cached(self, key, fn):
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        val = fn()
        with self._lock:
            self._cache[key] = (time.time(), val)
        return val

    def resolve_channel(self, text: str) -> str:
        from src.youtube.channel_collector import resolve_channel_input
        return self._cached(("resolve", text), lambda: resolve_channel_input(self.client, text))

    def get_channel(self, channel_id: str) -> dict:
        from src.youtube.channel_collector import fetch_channels

        def _f():
            rows = fetch_channels(self.client, [channel_id])
            if not rows:
                raise YouTubeNotFoundError("Không tìm thấy kênh.")
            r = rows[0]
            r["channel_published_at"] = pd.Timestamp(r["channel_published_at"])
            return r
        return self._cached(("channel", channel_id), _f)

    def get_recent_videos(self, channel_id: str, limit: int = 50) -> pd.DataFrame:
        from src.youtube.video_collector import fetch_upload_video_ids, fetch_video_details, videos_to_frame

        def _f():
            ch = self.get_channel(channel_id)
            ids = fetch_upload_video_ids(self.client, ch["uploads_playlist_id"], limit)
            rows = fetch_video_details(self.client, ids, datetime.now(timezone.utc).isoformat(timespec="seconds"))
            return videos_to_frame(rows)
        return self._cached(("recent", channel_id, limit), _f)

    def collect(self, channel_id: str, max_videos: int) -> dict:
        from src.data.storage import append_dedup
        from src.youtube.channel_collector import channels_to_frame, fetch_channels, utc_now_iso
        from src.youtube.video_collector import fetch_upload_video_ids, fetch_video_details, videos_to_frame
        now = utc_now_iso()
        rows = fetch_channels(self.client, [channel_id], now)
        if not rows:
            raise YouTubeNotFoundError("Không tìm thấy kênh.")
        append_dedup(self.settings.raw_channels_file, channels_to_frame(rows), ["channel_id", "collected_at"])
        ids = fetch_upload_video_ids(self.client, rows[0]["uploads_playlist_id"], max_videos)
        vids = fetch_video_details(self.client, ids, now)
        added = append_dedup(self.settings.raw_videos_file, videos_to_frame(vids), ["video_id", "collected_at"])
        return {"channel_id": channel_id, "videos_fetched": len(vids), "raw_rows_added": added}


class JobStore:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        jid = uuid.uuid4().hex
        with self._lock:
            self._jobs[jid] = {"job_id": jid, "status": "queued", "result": None, "error": None,
                               "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        return jid

    def update(self, jid: str, **kw) -> None:
        with self._lock:
            self._jobs[jid].update(kw)

    def get(self, jid: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(jid)
            return dict(j) if j else None


def map_youtube_error(e: Exception) -> ApiException:
    if isinstance(e, MissingAPIKeyError):
        return ApiException("YOUTUBE_KEY_MISSING", "Máy chủ chưa cấu hình YouTube API Key.", 503)
    if isinstance(e, YouTubeNotFoundError):
        return ApiException("CHANNEL_NOT_FOUND", "Không tìm thấy kênh YouTube này.", 404)
    if isinstance(e, YouTubeQuotaError):
        return ApiException("YOUTUBE_QUOTA_EXCEEDED", "Đã hết hạn mức YouTube API hôm nay. Vui lòng thử lại sau.", 503)
    return ApiException("YOUTUBE_API_ERROR", "Không lấy được dữ liệu từ YouTube. Vui lòng thử lại sau.", 502)


class PredictionService:
    def __init__(self, settings: Settings, predictor: ViewPredictor, provider: ChannelProvider | None):
        self.settings, self.predictor, self.provider = settings, predictor, provider
        self.jobs = JobStore()

    # ---------- helpers ----------
    def _require_model(self) -> None:
        if not self.predictor.is_ready:
            raise ApiException("MODEL_NOT_READY", "Mô hình chưa được huấn luyện hoặc chưa có file mô hình.", 503)

    def _require_provider(self) -> ChannelProvider:
        if self.provider is None:
            raise ApiException("YOUTUBE_KEY_MISSING", "Máy chủ chưa cấu hình YouTube API Key.", 503)
        return self.provider

    def _publish_ts(self, dt: datetime, warnings: list[str]) -> pd.Timestamp:
        if dt.tzinfo is None:
            warnings.append(f"publish_datetime không có múi giờ; hệ thống giả định {self.settings.feature_timezone}.")
            dt = dt.replace(tzinfo=ZoneInfo(self.settings.feature_timezone))
        return pd.Timestamp(dt).tz_convert("UTC")

    def _assemble(self, *, channel: dict, previous: dict, req, publish_ts: pd.Timestamp, warnings: list[str]) -> dict:
        if publish_ts < pd.Timestamp(channel["channel_published_at"]).tz_convert("UTC"):
            raise ApiException("INVALID_INPUT", "Thời điểm đăng sớm hơn ngày tạo kênh.", 422)
        n = self.settings.previous_video_count
        used = previous["previous_video_count_used"]
        if used == 0:
            raise ApiException("INSUFFICIENT_HISTORY",
                               "Kênh chưa có video trước đó để tính lượt xem trung bình. Không thể dự báo đáng tin cậy.", 422)
        if used < n:
            warnings.append(f"Chỉ có {used}/{n} video trước đó nên thống kê lịch sử kém ổn định.")
        if channel.get("subscriber_count") is None or pd.isna(channel.get("subscriber_count")):
            warnings.append("Kênh ẩn số người đăng ký; hệ thống dùng giá trị trung vị của dữ liệu huấn luyện.")
        feat = build_feature_row(channel=channel, previous=previous, title=req.title, description=req.description,
                                 duration_seconds=req.duration_seconds, tags=req.tags, publish_datetime=publish_ts,
                                 category_id=req.category_id, is_hd=req.is_hd, has_caption=req.has_caption,
                                 tz_name=self.settings.feature_timezone)
        feat.update(
        {
            "current_view_count": float(req.current_view_count),
            "current_video_age_hours": float(
                req.current_video_age_hours
            ),
            "recent_views_per_hour": float(
                req.recent_views_per_hour
            ),
        }
    )
        try:
            res = self.predictor.predict(pd.DataFrame([feat]))
        except ModelNotReadyError:
            raise ApiException("MODEL_NOT_READY", "Mô hình chưa được huấn luyện hoặc chưa có file mô hình.", 503)
        if res["lower"] is None:
            warnings.append("Chưa có khoảng tham khảo (thiếu residual của tập Test).")
        if self.predictor.metadata.get("is_synthetic"):
            warnings.append(DEMO_BANNER)
        cmp_ = self.predictor.metadata.get("baseline_comparison") or {}
        if cmp_ and not cmp_.get("beats_best_baseline_mae_and_rmse", True):
            warnings.append("Mô hình hiện tại không vượt baseline trên tập Test; kết quả kém tin cậy.")
        md = self.predictor.metadata
        hour, dow = publish_time_features(publish_ts, self.settings.feature_timezone)
        sub = channel.get("subscriber_count")
        return {
            "predicted_views_after_1_hour": round(res["views"]),
            "lower_estimate": None if res["lower"] is None else round(res["lower"]),
            "upper_estimate": None if res["upper"] is None else round(res["upper"]),
            "estimate_method": res["method"],
            "channel": {
                "channel_id": channel.get("channel_id", ""), "channel_title": channel.get("channel_title", ""),
                "subscriber_count": None if sub is None or pd.isna(sub) else int(sub),
                "channel_age_days": int(feat["channel_age_days"]),
                "channel_video_count": int(feat["channel_video_count"]) if pd.notna(feat["channel_video_count"]) else 0,
                "channel_total_views": int(feat["channel_total_views"]) if pd.notna(feat["channel_total_views"]) else 0,
                "avg_previous_views": round(float(previous["avg_previous_views"]), 2),
                "median_previous_views": round(float(previous["median_previous_views"]), 2),
                "previous_video_count_used": int(used),
            },
            "video_input": {
                "title": req.title, "duration_seconds": int(req.duration_seconds), "tag_count": int(feat["tag_count"]),
                "publish_datetime": publish_ts.isoformat(), "publish_hour": hour, "publish_day_of_week": dow,
                "category_id": str(req.category_id),
            },
            "model": {"name": md.get("model_name", "LinearRegression"), "version": md.get("model_version", ""),
                      "trained_at": md.get("trained_at", ""), "target": md.get("target", "views_after_1_hour")},
            "warnings": warnings,
        }

    # ---------- API ----------
    def predict_for_channel(self, req) -> dict:
        self._require_model()
        provider = self._require_provider()
        warnings: list[str] = []
        try:
            channel_id = provider.resolve_channel(req.channel_id)
            channel = provider.get_channel(channel_id)
            recent = provider.get_recent_videos(channel_id, 50)
        except ValueError as e:
            raise ApiException("INVALID_CHANNEL", str(e), 422)
        except YouTubeAPIError as e:
            raise map_youtube_error(e)
        publish_ts = self._publish_ts(req.publish_datetime, warnings)
        history = filter_history(recent, self.settings) if len(recent) else recent
        previous = previous_video_stats(history, publish_ts, self.settings.previous_video_count,
                                        min_gap_hours=self.settings.previous_video_min_gap_hours)
        return self._assemble(channel=channel, previous=previous, req=req, publish_ts=publish_ts, warnings=warnings)

    def predict_manual(self, req) -> dict:
        self._require_model()
        warnings: list[str] = []
        publish_ts = self._publish_ts(req.publish_datetime, warnings)
        channel_pub = publish_ts - pd.Timedelta(days=req.channel_age_days)
        channel = {"channel_id": "", "channel_title": req.channel_title, "channel_published_at": channel_pub,
                   "subscriber_count": req.subscriber_count, "channel_video_count": req.channel_video_count,
                   "channel_total_views": req.channel_total_views}
        previous = {"avg_previous_views": req.avg_previous_views, "median_previous_views": req.median_previous_views,
                    "previous_video_count_used": req.previous_video_count_used}
        return self._assemble(channel=channel, previous=previous, req=req, publish_ts=publish_ts, warnings=warnings)

    def run_collect_job(self, job_id: str, channel_id: str, max_videos: int) -> None:
        self.jobs.update(job_id, status="running")
        try:
            provider = self._require_provider()
            cid = provider.resolve_channel(channel_id)
            self.jobs.update(job_id, status="succeeded", result=provider.collect(cid, max_videos))
        except ApiException as e:
            self.jobs.update(job_id, status="failed", error={"code": e.code, "message": e.message})
        except Exception as e:
            err = map_youtube_error(e) if isinstance(e, YouTubeAPIError) else ApiException("INTERNAL_ERROR", "Lỗi nội bộ.", 500)
            log.error("Job %s lỗi: %s", job_id, type(e).__name__)
            self.jobs.update(job_id, status="failed", error={"code": err.code, "message": err.message})
