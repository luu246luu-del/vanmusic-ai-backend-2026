"""Tracker lượt xem sau 72 giờ. Chạy lặp (Task Scheduler / cron), mỗi lần tạo snapshot mới.

Chỉ video có snapshot nằm trong [72h - tol, 72h + tol] mới có nhãn views_after_1_hour (xem
feature_engineering.select_target_snapshot). Không bao giờ nội suy.
"""
from __future__ import annotations

import pandas as pd

from src.config import Settings
from src.data.schemas import SNAPSHOT_COLUMNS
from src.data.storage import append_dedup, read_csv_safe
from src.logger import get_logger
from src.youtube.channel_collector import channels_to_frame, fetch_channels, read_channel_ids, utc_now_iso
from src.youtube.client import YouTubeClient
from src.youtube.video_collector import fetch_upload_video_ids, fetch_video_details, videos_to_frame

log = get_logger(__name__)


def is_target_snapshot(age_hours: float, settings: Settings) -> bool:
    return abs(age_hours - settings.target_age_hours) <= settings.target_tolerance_hours


def build_snapshot_rows(videos: list[dict], channel: dict, collected_at: str, settings: Settings) -> list[dict]:
    """Snapshot cho các video còn trong (hoặc gần) cửa sổ 72 giờ."""
    now = pd.Timestamp(collected_at)
    rows = []
    window = settings.target_age_hours + settings.target_tolerance_hours
    for v in videos:
        if not v.get("published_at") or v.get("view_count") is None:
            continue
        age = (now - pd.Timestamp(v["published_at"])).total_seconds() / 3600.0
        if age < 0 or age > window:
            continue
        rows.append({
            "video_id": v["video_id"], "channel_id": v["channel_id"], "published_at": v["published_at"],
            "collected_at": collected_at, "video_age_hours": round(age, 4), "view_count": v["view_count"],
            "subscriber_count": channel.get("subscriber_count"),
            "hidden_subscriber_count": channel.get("hidden_subscriber_count"),
            "channel_total_views": channel.get("channel_total_views"),
            "channel_video_count": channel.get("channel_video_count"),
        })
    return rows


def run_tracker(settings: Settings, client: YouTubeClient) -> dict:
    ids = read_channel_ids(settings.resolve(settings.channels_csv))
    if not ids:
        raise SystemExit("channels.csv chưa có Channel ID hợp lệ.")
    collected_at = utc_now_iso()
    channels = fetch_channels(client, ids, collected_at)
    append_dedup(settings.raw_channels_file, channels_to_frame(channels), ["channel_id", "collected_at"])

    known = read_csv_safe(settings.snapshots_file, usecols=["video_id", "video_age_hours"]) \
        if settings.snapshots_file.exists() else pd.DataFrame(columns=["video_id", "video_age_hours"])
    already_labeled = set(known.loc[(known["video_age_hours"] - settings.target_age_hours).abs()
                                    <= settings.target_tolerance_hours, "video_id"]) if len(known) else set()

    total_new_videos, total_snaps, new_targets = 0, 0, 0
    for ch in channels:
        try:
            vids = fetch_upload_video_ids(client, ch["uploads_playlist_id"], settings.tracker_recent_videos)
            details = fetch_video_details(client, vids, collected_at)
        except Exception as e:  # một kênh lỗi không làm hỏng cả lượt chạy
            log.error("Kênh %s lỗi: %s", ch["channel_id"], e)
            continue
        total_new_videos += append_dedup(settings.raw_videos_file, videos_to_frame(details), ["video_id", "collected_at"])
        snaps = [r for r in build_snapshot_rows(details, ch, collected_at, settings) if r["video_id"] not in already_labeled]
        total_snaps += append_dedup(settings.snapshots_file, pd.DataFrame(snaps, columns=SNAPSHOT_COLUMNS),
                                    ["video_id", "collected_at"])
        new_targets += sum(is_target_snapshot(r["video_age_hours"], settings) for r in snaps)
    summary = {"channels": len(channels), "raw_video_rows_added": total_new_videos,
               "snapshots_added": total_snaps, "target_snapshots_added": new_targets}
    log.info("Tracker xong: %s", summary)
    return summary
