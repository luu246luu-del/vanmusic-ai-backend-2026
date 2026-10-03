import numpy as np
import pandas as pd

from src.data.feature_engineering import (channel_age_days, parse_tags, previous_video_stats,
                                          publish_time_features, title_features)


def _videos(n=15, start="2026-01-01"):
    base = pd.Timestamp(start, tz="UTC")
    return pd.DataFrame({"video_id": [f"v{i}" for i in range(n)],
                         "published_at": [base + pd.Timedelta(days=i) for i in range(n)],
                         "view_count": [(i + 1) * 1000 for i in range(n)]})


def test_channel_age_days_at_publish_time():
    assert channel_age_days("2020-01-01T00:00:00Z", "2020-01-11T12:00:00Z") == 10


def test_title_and_tags():
    assert title_features("  Hello   world ") == (len("Hello   world"), 2)
    assert parse_tags('["a", "b"]') == ["a", "b"]
    assert parse_tags(None) == []
    assert parse_tags(float("nan")) == []


def test_publish_time_features_uses_timezone():
    # 20:00 UTC = 03:00 hôm sau giờ Việt Nam
    hour, dow = publish_time_features("2026-10-02T20:00:00Z", "Asia/Ho_Chi_Minh")
    assert hour == 3 and dow == 5  # 2026-10-03 là thứ Bảy (Thứ Hai = 0)


def test_previous_stats_avg_median_and_count():
    v = _videos(15)
    ref = v.loc[12, "published_at"]  # 12 video trước (v0..v11), chỉ lấy 10 gần nhất: v2..v11
    s = previous_video_stats(v, ref, n=10, exclude_video_id="v12")
    used = [(i + 1) * 1000 for i in range(2, 12)]
    assert s["previous_video_count_used"] == 10
    assert s["avg_previous_views"] == np.mean(used)
    assert s["median_previous_views"] == np.median(used)


def test_previous_stats_fewer_than_n_reports_actual_count():
    v = _videos(15)
    s = previous_video_stats(v, v.loc[3, "published_at"], n=10, exclude_video_id="v3")
    assert s["previous_video_count_used"] == 3


def test_previous_stats_no_history_gives_nan():
    v = _videos(5)
    s = previous_video_stats(v, v.loc[0, "published_at"], exclude_video_id="v0")
    assert s["previous_video_count_used"] == 0 and np.isnan(s["avg_previous_views"])


def test_missing_view_counts_are_ignored():
    v = _videos(6)
    v.loc[2, "view_count"] = np.nan
    s = previous_video_stats(v, v.loc[5, "published_at"], exclude_video_id="v5")
    assert s["previous_video_count_used"] == 4
