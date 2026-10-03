"""SYNTHETIC DEMO DATA - KHÔNG DÙNG ĐỂ ĐÁNH GIÁ MÔ HÌNH THỰC TẾ.

Sinh dữ liệu giả chỉ để kiểm tra toàn bộ quy trình:

dữ liệu hiện tại
→ huấn luyện Linear Regression
→ lưu mô hình
→ tải mô hình
→ dự báo lượt xem tăng trong một giờ tiếp theo

Các chỉ số tạo từ dữ liệu này không có ý nghĩa đối với YouTube thật.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.schemas import (
    DEMO_BANNER,
    PROCESSED_COLUMNS,
    TARGET,
)


def generate_synthetic_dataset(
    n_rows: int = 600,
    n_channels: int = 30,
    seed: int = 42,
) -> pd.DataFrame:
    """Tạo dữ liệu giả phục vụ kiểm thử kỹ thuật.

    Mỗi dòng mô tả trạng thái của một video tại thời điểm hiện tại.

    Target là số lượt xem video tăng thêm trong một giờ tiếp theo:

        views_gained_next_1_hour
        = future_view_count - current_view_count

    Không sử dụng dữ liệu giả này để đánh giá chất lượng mô hình thật.
    """

    rng = np.random.default_rng(seed)

    channel_ids = [
        f"UCSYNTHETIC{index:013d}"[:24]
        for index in range(n_channels)
    ]

    channel_subscribers = np.exp(
        rng.uniform(
            np.log(2_000),
            np.log(20_000_000),
            n_channels,
        )
    )

    channel_created_dates = (
        pd.Timestamp("2012-01-01", tz="UTC")
        + pd.to_timedelta(
            rng.integers(
                0,
                3_000,
                n_channels,
            ),
            unit="D",
        )
    )

    rows = []

    dataset_start = pd.Timestamp(
        "2024-01-01",
        tz="UTC",
    )

    for row_index in range(n_rows):
        channel_index = int(
            rng.integers(
                0,
                n_channels,
            )
        )

        published_at = (
            dataset_start
            + pd.Timedelta(
                hours=(
                    float(row_index)
                    * 24
                    * 400
                    / n_rows
                    + rng.uniform(0, 5)
                )
            )
        )

        subscriber_count = (
            channel_subscribers[channel_index]
            * (1 + 0.0005 * row_index)
        )

        avg_previous_views = (
            subscriber_count
            * rng.uniform(0.02, 0.30)
        )

        median_previous_views = (
            avg_previous_views
            * rng.uniform(0.60, 1.0)
        )

        duration_seconds = int(
            rng.integers(
                120,
                1_200,
            )
        )

        tag_count = int(
            rng.integers(
                0,
                25,
            )
        )

        current_video_age_hours = float(
            rng.uniform(
                0.25,
                24.0,
            )
        )

        snapshot_time = (
            published_at
            + pd.Timedelta(
                hours=current_video_age_hours
            )
        )

        future_snapshot_time = (
            snapshot_time
            + pd.Timedelta(hours=1)
        )

        channel_scale = np.log1p(
            subscriber_count
        )

        history_scale = np.log1p(
            avg_previous_views
        )

        age_decay = 1 / np.sqrt(
            current_video_age_hours + 1
        )

        recent_views_per_hour = float(
            max(
                0,
                np.expm1(
                    0.45 * history_scale
                    + 0.10 * channel_scale
                    + np.log(age_decay + 0.01)
                    + rng.normal(0, 0.30)
                ),
            )
        )

        current_view_count = float(
            max(
                1,
                avg_previous_views
                * rng.uniform(0.15, 1.50)
                * np.log1p(
                    current_video_age_hours
                ),
            )
        )

        publish_hour = int(
            published_at.hour
        )

        hour_effect = 1.15 if 18 <= publish_hour <= 22 else 1.0

        category_effect = rng.uniform(
            0.90,
            1.10,
        )

        expected_gain = (
            0.75 * recent_views_per_hour
            + 0.03 * np.sqrt(current_view_count)
            + 0.01 * np.sqrt(avg_previous_views)
        )

        views_gained_next_1_hour = float(
            max(
                0,
                expected_gain
                * hour_effect
                * category_effect
                * rng.lognormal(
                    mean=0,
                    sigma=0.20,
                ),
            )
        )

        rows.append(
            {
                "video_id": (
                    f"SYNVID{row_index:05d}"
                ),
                "channel_id": (
                    channel_ids[channel_index]
                ),
                "channel_title": (
                    f"Kênh giả lập {channel_index}"
                ),
                "published_at": published_at,
                "snapshot_time": snapshot_time,
                "future_snapshot_time": (
                    future_snapshot_time
                ),
                "previous_video_count_used": 10,
                "snapshot_gap_hours": 1.0,
                "channel_age_days": int(
                    (
                        published_at
                        - channel_created_dates[
                            channel_index
                        ]
                    ).days
                ),
                "subscriber_count": float(
                    subscriber_count
                ),
                "channel_video_count": int(
                    rng.integers(
                        50,
                        5_000,
                    )
                ),
                "channel_total_views": float(
                    subscriber_count
                    * rng.uniform(
                        80,
                        300,
                    )
                ),
                "avg_previous_views": float(
                    avg_previous_views
                ),
                "median_previous_views": float(
                    median_previous_views
                ),
                "duration_seconds": (
                    duration_seconds
                ),
                "title_length": int(
                    rng.integers(
                        15,
                        90,
                    )
                ),
                "title_word_count": int(
                    rng.integers(
                        3,
                        18,
                    )
                ),
                "tag_count": tag_count,
                "description_length": int(
                    rng.integers(
                        50,
                        1_500,
                    )
                ),
                "publish_hour": publish_hour,
                "publish_day_of_week": int(
                    published_at.dayofweek
                ),
                "category_id": "25",
                "is_hd": float(
                    rng.random() < 0.95
                ),
                "has_caption": float(
                    rng.random() < 0.30
                ),
                "current_view_count": (
                    current_view_count
                ),
                "current_video_age_hours": (
                    current_video_age_hours
                ),
                "recent_views_per_hour": (
                    recent_views_per_hour
                ),
                TARGET: views_gained_next_1_hour,
            }
        )

    dataframe = pd.DataFrame(rows)

    dataframe = dataframe[
        PROCESSED_COLUMNS
    ]

    dataframe.attrs["banner"] = DEMO_BANNER

    return dataframe