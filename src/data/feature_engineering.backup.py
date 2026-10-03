"""Kỹ thuật đặc trưng + dựng tập huấn luyện. Mọi thống kê lịch sử chỉ dùng video xuất bản TRƯỚC video đang xét."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.config import Settings
from src.data.schemas import (FEATURE_COLUMNS, META_COLUMNS, PROCESSED_COLUMNS, TARGET)
from src.data.validator import build_quality_report, validate_schema
from src.logger import get_logger

log = get_logger(__name__)

_DUR_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")


def parse_duration_seconds(iso_duration) -> int | None:
    """Chuyển ISO 8601 (vd 'PT4M20S', 'P1DT2H') thành số giây. Trả None nếu thiếu/sai định dạng."""
    if iso_duration is None or (isinstance(iso_duration, float) and np.isnan(iso_duration)):
        return None
    s = str(iso_duration).strip()
    if not s:
        return None
    try:  # ưu tiên thư viện isodate nếu có
        import isodate
        return int(isodate.parse_duration(s).total_seconds())
    except ImportError:
        pass
    except Exception:
        return None
    m = _DUR_RE.match(s)
    if not m or s in ("P", "PT"):
        return None
    d, h, mi, sec = m.groups()
    total = int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(sec or 0)
    return int(total)


def parse_tags(tags) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, float) and np.isnan(tags):
        return []
    if isinstance(tags, (list, tuple)):
        return [str(t) for t in tags]
    s = str(tags).strip()
    if not s:
        return []
    try:
        v = json.loads(s)
        return [str(t) for t in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return [t for t in s.split("|") if t]


def title_features(title: str | None) -> tuple[int, int]:
    t = (title or "").strip()
    return len(t), len(t.split())


def to_utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def publish_time_features(published_at, tz_name: str) -> tuple[int, int]:
    """(publish_hour, publish_day_of_week) theo múi giờ cấu hình. Thứ Hai = 0."""
    local = to_utc(published_at).tz_convert(ZoneInfo(tz_name))
    return int(local.hour), int(local.dayofweek)


def channel_age_days(channel_published_at, video_published_at) -> int:
    """Tuổi kênh (ngày) TẠI THỜI ĐIỂM video được đăng."""
    delta = to_utc(video_published_at) - to_utc(channel_published_at)
    return int(delta.total_seconds() // 86400)


def previous_video_stats(videos: pd.DataFrame, published_at, n: int = 10,
                         exclude_video_id: str | None = None, min_gap_hours: float = 0.0) -> dict:
    """avg/median lượt xem của tối đa n video xuất bản TRƯỚC `published_at`.

    - Không bao giờ dùng chính video đang xét (exclude_video_id) hay video tương lai.
    - Trả về số video thực tế đã dùng (previous_video_count_used).
    """
    empty = {"avg_previous_views": np.nan, "median_previous_views": np.nan, "previous_video_count_used": 0}
    if videos is None or len(videos) == 0:
        return empty
    ref = to_utc(published_at) - pd.Timedelta(hours=min_gap_hours)
    pub = pd.to_datetime(videos["published_at"], utc=True, errors="coerce")
    mask = (pub < ref) & videos["view_count"].notna()
    if exclude_video_id is not None:
        mask &= videos["video_id"].astype(str) != str(exclude_video_id)
    prev = videos.loc[mask].assign(_pub=pub[mask]).sort_values("_pub", ascending=False).head(n)
    if prev.empty:
        return empty
    views = prev["view_count"].astype(float)
    return {"avg_previous_views": float(views.mean()),
            "median_previous_views": float(views.median()),
            "previous_video_count_used": int(len(prev))}


def build_feature_row(*, channel: dict, previous: dict, title: str, description: str, duration_seconds,
                      tags, publish_datetime, category_id, is_hd, has_caption, tz_name: str) -> dict:
    """Dựng 1 dòng đặc trưng (dùng chung cho huấn luyện và dự đoán để tránh lệch pha)."""
    tl, tw = title_features(title)
    hour, dow = publish_time_features(publish_datetime, tz_name)
    return {
        "channel_age_days": channel_age_days(channel["channel_published_at"], publish_datetime),
        "subscriber_count": channel.get("subscriber_count", np.nan),
        "channel_video_count": channel.get("channel_video_count", np.nan),
        "channel_total_views": channel.get("channel_total_views", np.nan),
        "avg_previous_views": previous["avg_previous_views"],
        "median_previous_views": previous["median_previous_views"],
        "duration_seconds": duration_seconds,
        "title_length": tl,
        "title_word_count": tw,
        "tag_count": len(parse_tags(tags)),
        "description_length": len((description or "").strip()) if isinstance(description, str) or description is None else len(str(description)),
        "publish_hour": hour,
        "publish_day_of_week": dow,
        "category_id": str(category_id) if category_id is not None else np.nan,
        "is_hd": float(bool(is_hd)) if is_hd is not None and not pd.isna(is_hd) else np.nan,
        "has_caption": float(bool(has_caption)) if has_caption is not None and not pd.isna(has_caption) else np.nan,
    }


def _as_bool(v):
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "hd", "yes"}
    return bool(v) if not pd.isna(v) else np.nan


def filter_history(videos: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Áp dụng include_shorts / include_live_streams giống nhau cho huấn luyện và dự đoán."""
    df = videos.copy()
    if not settings.include_shorts and "duration_seconds" in df.columns:
        df = df[~(df["duration_seconds"].fillna(10**9) <= settings.shorts_max_seconds)]
    if not settings.include_live_streams and "has_live_streaming_details" in df.columns:
        df = df[~df["has_live_streaming_details"].map(lambda v: _as_bool(v) is True)]
    return df


def select_target_snapshot(snaps: pd.DataFrame, target_h: float, tol_h: float) -> pd.Series | None:
    """Chọn snapshot gần mốc 72h nhất, và CHỈ khi nằm trong dung sai. Không nội suy."""
    if snaps.empty:
        return None
    cand = snaps[(snaps["video_age_hours"] - target_h).abs() <= tol_h].dropna(subset=["view_count"])
    if cand.empty:
        return None
    return cand.loc[(cand["video_age_hours"] - target_h).abs().idxmin()]


def build_training_dataset(videos_raw: pd.DataFrame, channels_raw: pd.DataFrame,
                           snapshots: pd.DataFrame, settings: Settings) -> tuple[pd.DataFrame, dict]:
    """Dựng tập huấn luyện. Trả về (dataframe, báo cáo chất lượng)."""
    validate_schema(videos_raw, ["video_id", "channel_id", "published_at", "view_count", "collected_at"], "videos_raw")
    validate_schema(channels_raw, ["channel_id", "channel_published_at", "collected_at"], "channels_raw")
    validate_schema(snapshots, ["video_id", "channel_id", "published_at", "collected_at", "view_count"], "snapshots")

    drops: Counter = Counter()
    n_dup_raw = int(videos_raw.duplicated(subset=["video_id", "collected_at"]).sum())
    videos_raw = videos_raw.drop_duplicates(subset=["video_id", "collected_at"], keep="last").copy()
    snapshots = snapshots.drop_duplicates(subset=["video_id", "collected_at"], keep="last").copy()

    videos_raw["published_at"] = pd.to_datetime(videos_raw["published_at"], utc=True, errors="coerce")
    videos_raw["collected_at"] = pd.to_datetime(videos_raw["collected_at"], utc=True, errors="coerce")
    channels_raw["collected_at"] = pd.to_datetime(channels_raw["collected_at"], utc=True, errors="coerce")
    channels_raw["channel_published_at"] = pd.to_datetime(channels_raw["channel_published_at"], utc=True, errors="coerce")
    snapshots["published_at"] = pd.to_datetime(snapshots["published_at"], utc=True, errors="coerce")
    snapshots["collected_at"] = pd.to_datetime(snapshots["collected_at"], utc=True, errors="coerce")

    if "duration_seconds" not in videos_raw.columns:
        videos_raw["duration_seconds"] = videos_raw.get("duration", pd.Series(dtype=object)).map(parse_duration_seconds)
    videos_raw["duration_seconds"] = pd.to_numeric(videos_raw["duration_seconds"], errors="coerce")

    # bản ghi mới nhất của mỗi video / kênh
    videos = videos_raw.sort_values("collected_at").drop_duplicates("video_id", keep="last").set_index("video_id", drop=False)
    channels = channels_raw.sort_values("collected_at").drop_duplicates("channel_id", keep="last").set_index("channel_id", drop=False)
    history_all = filter_history(videos.reset_index(drop=True), settings)
    history_by_channel = {cid: g for cid, g in history_all.groupby("channel_id")}

    # tuổi video tính lại từ mốc thời gian (không tin cột có sẵn)
    snapshots["video_age_hours"] = (snapshots["collected_at"] - snapshots["published_at"]).dt.total_seconds() / 3600.0
    snapshots["view_count"] = pd.to_numeric(snapshots["view_count"], errors="coerce")

    candidate_ids = list(snapshots["video_id"].dropna().unique())
    initial_rows = len(candidate_ids)
    rows = []
    for vid, snaps in snapshots.groupby("video_id"):
        if vid not in videos.index:
            drops["thiếu_metadata_video"] += 1
            continue
        v = videos.loc[vid]
        if pd.isna(v["published_at"]):
            drops["thiếu_published_at"] += 1
            continue
        if not settings.include_shorts and pd.notna(v["duration_seconds"]) and v["duration_seconds"] <= settings.shorts_max_seconds:
            drops["video_shorts_bị_loại"] += 1
            continue
        if not settings.include_live_streams and _as_bool(v.get("has_live_streaming_details", False)) is True:
            drops["live_stream_bị_loại"] += 1
            continue
        target_snap = select_target_snapshot(snaps, settings.target_age_hours, settings.target_tolerance_hours)
        if target_snap is None:
            drops["chưa_có_snapshot_72h_trong_dung_sai"] += 1
            continue
        target = float(target_snap["view_count"])
        if target < 0:
            drops["target_âm"] += 1
            continue
        early = snaps[(snaps["video_age_hours"] >= 0) & (snaps["video_age_hours"] <= settings.max_channel_stats_age_hours)]
        if early.empty:
            drops["không_có_thống_kê_kênh_gần_thời_điểm_đăng"] += 1
            continue
        stats = early.sort_values("video_age_hours").iloc[0]
        cid = v["channel_id"]
        if cid not in channels.index:
            drops["thiếu_thông_tin_kênh"] += 1
            continue
        ch = channels.loc[cid]
        if pd.isna(ch["channel_published_at"]):
            drops["thiếu_ngày_tạo_kênh"] += 1
            continue
        if pd.isna(v["duration_seconds"]):
            drops["thiếu_duration"] += 1
            continue
        age_days = channel_age_days(ch["channel_published_at"], v["published_at"])
        if age_days < 0:
            drops["tuổi_kênh_âm"] += 1
            continue
        prev = previous_video_stats(history_by_channel.get(cid), v["published_at"], settings.previous_video_count,
                                    exclude_video_id=vid, min_gap_hours=settings.previous_video_min_gap_hours)
        feat = build_feature_row(
            channel={"channel_published_at": ch["channel_published_at"],
                     "subscriber_count": stats.get("subscriber_count", np.nan),
                     "channel_video_count": stats.get("channel_video_count", np.nan),
                     "channel_total_views": stats.get("channel_total_views", np.nan)},
            previous=prev, title=v.get("title", ""), description=v.get("description", ""),
            duration_seconds=v["duration_seconds"], tags=v.get("tags"), publish_datetime=v["published_at"],
            category_id=v.get("category_id"), is_hd=_as_bool(str(v.get("definition", "")).lower() == "hd"),
            has_caption=_as_bool(v.get("caption", np.nan)), tz_name=settings.feature_timezone)
        feat.update({
            "video_id": vid, "channel_id": cid, "channel_title": ch.get("channel_title", ""),
            "published_at": v["published_at"], "previous_video_count_used": prev["previous_video_count_used"],
            "target_snapshot_age_hours": float(target_snap["video_age_hours"]), TARGET: target,
        })
        rows.append(feat)

    df = pd.DataFrame(rows, columns=PROCESSED_COLUMNS) if rows else pd.DataFrame(columns=PROCESSED_COLUMNS)
    before = len(df)
    df = df.drop_duplicates(subset=["video_id"], keep="last")
    if before - len(df):
        drops["trùng_video_id"] += before - len(df)
    df = df.sort_values("published_at").reset_index(drop=True)
    report = build_quality_report(initial_rows, df, drops,
                                  extra={"duplicate_raw_rows_removed": n_dup_raw,
                                         "channels_in_dataset": int(df["channel_id"].nunique()) if len(df) else 0})
    return df, report
