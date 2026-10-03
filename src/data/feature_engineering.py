"""Kỹ thuật đặc trưng và xây dựng tập dữ liệu huấn luyện.

Mục tiêu mới:

    views_gained_next_1_hour

Mỗi mẫu dữ liệu được tạo từ:

    snapshot hiện tại
    + snapshot tương lai cách khoảng một giờ

Target được tính bằng:

    future_view_count - current_view_count

Mọi thống kê lịch sử kênh chỉ sử dụng video xuất bản trước
video đang được xét.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.config import Settings
from src.data.schemas import (
    PROCESSED_COLUMNS,
    TARGET,
)
from src.data.validator import (
    build_quality_report,
    validate_schema,
)
from src.logger import get_logger


log = get_logger(__name__)


_DURATION_PATTERN = re.compile(
    r"^P"
    r"(?:(\d+)D)?"
    r"(?:T"
    r"(?:(\d+)H)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+(?:\.\d+)?)S)?"
    r")?$"
)


def parse_duration_seconds(
    iso_duration,
) -> int | None:
    """Chuyển thời lượng ISO 8601 thành tổng số giây."""

    if iso_duration is None:
        return None

    if (
        isinstance(iso_duration, float)
        and np.isnan(iso_duration)
    ):
        return None

    value = str(iso_duration).strip()

    if not value:
        return None

    try:
        import isodate

        return int(
            isodate.parse_duration(
                value
            ).total_seconds()
        )
    except ImportError:
        pass
    except Exception:
        return None

    match = _DURATION_PATTERN.match(value)

    if not match or value in {"P", "PT"}:
        return None

    days, hours, minutes, seconds = match.groups()

    total_seconds = (
        int(days or 0) * 86400
        + int(hours or 0) * 3600
        + int(minutes or 0) * 60
        + float(seconds or 0)
    )

    return int(total_seconds)


def parse_tags(tags) -> list[str]:
    """Chuẩn hóa tags thành danh sách chuỗi."""
    if tags is None:
        return []

    if (
        isinstance(tags, float)
        and np.isnan(tags)
    ):
        return []

    if isinstance(tags, (list, tuple)):
        return [
            str(tag)
            for tag in tags
        ]

    value = str(tags).strip()

    if not value:
        return []

    try:
        parsed = json.loads(value)

        if isinstance(parsed, list):
            return [
                str(tag)
                for tag in parsed
            ]

        return []
    except json.JSONDecodeError:
        return [
            tag
            for tag in value.split("|")
            if tag
        ]


def title_features(
    title: str | None,
) -> tuple[int, int]:
    """Trả về độ dài ký tự và số từ trong tiêu đề."""

    normalized_title = (
        title or ""
    ).strip()

    return (
        len(normalized_title),
        len(normalized_title.split()),
    )


def to_utc(value) -> pd.Timestamp:
    """Chuyển giá trị thời gian thành pandas Timestamp UTC."""

    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(
            "UTC"
        )

    return timestamp.tz_convert("UTC")


def publish_time_features(
    published_at,
    timezone_name: str,
) -> tuple[int, int]:
    """Trả về giờ đăng và thứ trong tuần theo múi giờ cấu hình."""

    local_time = to_utc(
        published_at
    ).tz_convert(
        ZoneInfo(timezone_name)
    )

    return (
        int(local_time.hour),
        int(local_time.dayofweek),
    )


def channel_age_days(
    channel_published_at,
    video_published_at,
) -> int:
    """Tính tuổi kênh tại thời điểm video được xuất bản."""

    difference = (
        to_utc(video_published_at)
        - to_utc(channel_published_at)
    )

    return int(
        difference.total_seconds()
        // 86400
    )


def previous_video_stats(
    videos: pd.DataFrame,
    published_at,
    n: int = 10,
    exclude_video_id: str | None = None,
    min_gap_hours: float = 0.0,
) -> dict:
    """Tính thống kê từ các video xuất bản trước video hiện tại."""

    empty_result = {
        "avg_previous_views": np.nan,
        "median_previous_views": np.nan,
        "previous_video_count_used": 0,
    }

    if videos is None or len(videos) == 0:
        return empty_result

    reference_time = (
        to_utc(published_at)
        - pd.Timedelta(
            hours=min_gap_hours
        )
    )

    published_times = pd.to_datetime(
        videos["published_at"],
        utc=True,
        errors="coerce",
    )

    view_counts = pd.to_numeric(
        videos["view_count"],
        errors="coerce",
    )

    valid_mask = (
        (published_times < reference_time)
        & view_counts.notna()
    )

    if exclude_video_id is not None:
        valid_mask &= (
            videos["video_id"].astype(str)
            != str(exclude_video_id)
        )

    previous_videos = (
        videos.loc[valid_mask]
        .assign(
            _published_at=published_times[
                valid_mask
            ],
            _view_count=view_counts[
                valid_mask
            ],
        )
        .sort_values(
            "_published_at",
            ascending=False,
        )
        .head(n)
    )

    if previous_videos.empty:
        return empty_result

    views = previous_videos[
        "_view_count"
    ].astype(float)

    return {
        "avg_previous_views": float(
            views.mean()
        ),
        "median_previous_views": float(
            views.median()
        ),
        "previous_video_count_used": int(
            len(previous_videos)
        ),
    }


def build_feature_row(
    *,
    channel: dict,
    previous: dict,
    title: str,
    description: str,
    duration_seconds,
    tags,
    publish_datetime,
    category_id,
    is_hd,
    has_caption,
    tz_name: str,
) -> dict:
    """Tạo các đặc trưng chung của video và kênh."""

    title_length, title_word_count = (
        title_features(title)
    )

    publish_hour, publish_day_of_week = (
        publish_time_features(
            publish_datetime,
            tz_name,
        )
    )

    if (
        isinstance(description, str)
        or description is None
    ):
        description_length = len(
            (description or "").strip()
        )
    else:
        description_length = len(
            str(description)
        )

    return {
        "channel_age_days": (
            channel_age_days(
                channel[
                    "channel_published_at"
                ],
                publish_datetime,
            )
        ),
        "subscriber_count": channel.get(
            "subscriber_count",
            np.nan,
        ),
        "channel_video_count": channel.get(
            "channel_video_count",
            np.nan,
        ),
        "channel_total_views": channel.get(
            "channel_total_views",
            np.nan,
        ),
        "avg_previous_views": previous[
            "avg_previous_views"
        ],
        "median_previous_views": previous[
            "median_previous_views"
        ],
        "duration_seconds": duration_seconds,
        "title_length": title_length,
        "title_word_count": (
            title_word_count
        ),
        "tag_count": len(
            parse_tags(tags)
        ),
        "description_length": (
            description_length
        ),
        "publish_hour": publish_hour,
        "publish_day_of_week": (
            publish_day_of_week
        ),
        "category_id": (
            str(category_id)
            if category_id is not None
            else np.nan
        ),
        "is_hd": (
            float(bool(is_hd))
            if (
                is_hd is not None
                and not pd.isna(is_hd)
            )
            else np.nan
        ),
        "has_caption": (
            float(bool(has_caption))
            if (
                has_caption is not None
                and not pd.isna(
                    has_caption
                )
            )
            else np.nan
        ),
    }


def _as_bool(value):
    """Chuyển nhiều kiểu giá trị về bool an toàn."""

    if isinstance(value, str):
        return (
            value.strip().lower()
            in {
                "true",
                "1",
                "hd",
                "yes",
            }
        )

    if pd.isna(value):
        return np.nan

    return bool(value)


def filter_history(
    videos: pd.DataFrame,
    settings: Settings,
) -> pd.DataFrame:
    """Lọc Shorts và livestream giống nhau ở train và predict."""

    dataframe = videos.copy()

    if (
        not settings.include_shorts
        and "duration_seconds"
        in dataframe.columns
    ):
        dataframe = dataframe[
            ~(
                dataframe[
                    "duration_seconds"
                ]
                .fillna(10**9)
                <= settings.shorts_max_seconds
            )
        ]

    if (
        not settings.include_live_streams
        and "has_live_streaming_details"
        in dataframe.columns
    ):
        dataframe = dataframe[
            ~dataframe[
                "has_live_streaming_details"
            ].map(
                lambda value: (
                    _as_bool(value) is True
                )
            )
        ]

    return dataframe


def _find_future_snapshot(
    current_snapshot: pd.Series,
    later_snapshots: pd.DataFrame,
    target_gap_hours: float,
    tolerance_hours: float,
) -> pd.Series | None:
    """Tìm snapshot tương lai gần mốc một giờ nhất.

    Ví dụ với target bằng một giờ và tolerance bằng 0,25 giờ:

        khoảng hợp lệ là 45 đến 75 phút.
    """

    if later_snapshots.empty:
        return None

    time_gaps = (
        later_snapshots["collected_at"]
        - current_snapshot["collected_at"]
    ).dt.total_seconds() / 3600.0

    valid_mask = (
        (time_gaps > 0)
        & (
            (
                time_gaps
                - target_gap_hours
            ).abs()
            <= tolerance_hours
        )
    )

    candidates = later_snapshots.loc[
        valid_mask
    ].copy()

    if candidates.empty:
        return None

    candidates["_gap_hours"] = (
        (
            candidates["collected_at"]
            - current_snapshot[
                "collected_at"
            ]
        ).dt.total_seconds()
        / 3600.0
    )

    closest_index = (
        candidates["_gap_hours"]
        .sub(target_gap_hours)
        .abs()
        .idxmin()
    )

    return candidates.loc[
        closest_index
    ]


def _recent_views_per_hour(
    snapshots_before_current: pd.DataFrame,
    current_snapshot: pd.Series,
) -> float:
    """Tính tốc độ tăng lượt xem gần nhất trước thời điểm dự báo."""

    if snapshots_before_current.empty:
        return 0.0

    previous_snapshot = (
        snapshots_before_current
        .sort_values("collected_at")
        .iloc[-1]
    )

    time_difference_hours = (
        current_snapshot["collected_at"]
        - previous_snapshot[
            "collected_at"
        ]
    ).total_seconds() / 3600.0

    if time_difference_hours <= 0:
        return 0.0

    current_views = float(
        current_snapshot["view_count"]
    )

    previous_views = float(
        previous_snapshot["view_count"]
    )

    view_difference = (
        current_views
        - previous_views
    )

    return float(
        max(
            0.0,
            view_difference
            / time_difference_hours,
        )
    )


def build_training_dataset(
    videos_raw: pd.DataFrame,
    channels_raw: pd.DataFrame,
    snapshots: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, dict]:
    """Tạo tập huấn luyện từ các cặp snapshot cách khoảng một giờ."""

    validate_schema(
        videos_raw,
        [
            "video_id",
            "channel_id",
            "published_at",
            "view_count",
            "collected_at",
        ],
        "videos_raw",
    )

    validate_schema(
        channels_raw,
        [
            "channel_id",
            "channel_published_at",
            "collected_at",
        ],
        "channels_raw",
    )

    validate_schema(
        snapshots,
        [
            "video_id",
            "channel_id",
            "published_at",
            "collected_at",
            "view_count",
        ],
        "snapshots",
    )

    drop_reasons: Counter = Counter()

    duplicate_raw_rows = int(
        videos_raw.duplicated(
            subset=[
                "video_id",
                "collected_at",
            ]
        ).sum()
    )

    videos_raw = (
        videos_raw
        .drop_duplicates(
            subset=[
                "video_id",
                "collected_at",
            ],
            keep="last",
        )
        .copy()
    )

    snapshots = (
        snapshots
        .drop_duplicates(
            subset=[
                "video_id",
                "collected_at",
            ],
            keep="last",
        )
        .copy()
    )

    videos_raw["published_at"] = (
        pd.to_datetime(
            videos_raw["published_at"],
            utc=True,
            errors="coerce",
        )
    )

    videos_raw["collected_at"] = (
        pd.to_datetime(
            videos_raw["collected_at"],
            utc=True,
            errors="coerce",
        )
    )

    channels_raw["collected_at"] = (
        pd.to_datetime(
            channels_raw["collected_at"],
            utc=True,
            errors="coerce",
        )
    )

    channels_raw[
        "channel_published_at"
    ] = pd.to_datetime(
        channels_raw[
            "channel_published_at"
        ],
        utc=True,
        errors="coerce",
    )

    snapshots["published_at"] = (
        pd.to_datetime(
            snapshots["published_at"],
            utc=True,
            errors="coerce",
        )
    )

    snapshots["collected_at"] = (
        pd.to_datetime(
            snapshots["collected_at"],
            utc=True,
            errors="coerce",
        )
    )

    snapshots["view_count"] = (
        pd.to_numeric(
            snapshots["view_count"],
            errors="coerce",
        )
    )

    snapshots = snapshots.dropna(
        subset=[
            "video_id",
            "collected_at",
            "published_at",
            "view_count",
        ]
    )

    snapshots["video_age_hours"] = (
        (
            snapshots["collected_at"]
            - snapshots["published_at"]
        ).dt.total_seconds()
        / 3600.0
    )

    if (
        "duration_seconds"
        not in videos_raw.columns
    ):
        duration_series = videos_raw.get(
            "duration",
            pd.Series(
                index=videos_raw.index,
                dtype=object,
            ),
        )

        videos_raw[
            "duration_seconds"
        ] = duration_series.map(
            parse_duration_seconds
        )

    videos_raw[
        "duration_seconds"
    ] = pd.to_numeric(
        videos_raw["duration_seconds"],
        errors="coerce",
    )

    videos = (
        videos_raw
        .sort_values("collected_at")
        .drop_duplicates(
            "video_id",
            keep="last",
        )
        .set_index(
            "video_id",
            drop=False,
        )
    )

    channels = (
        channels_raw
        .sort_values("collected_at")
        .drop_duplicates(
            "channel_id",
            keep="last",
        )
        .set_index(
            "channel_id",
            drop=False,
        )
    )

    filtered_history = filter_history(
        videos.reset_index(drop=True),
        settings,
    )

    history_by_channel = {
        channel_id: group
        for channel_id, group
        in filtered_history.groupby(
            "channel_id"
        )
    }

    target_gap_hours = float(
        settings.target_age_hours
    )

    tolerance_hours = float(
        settings.target_tolerance_hours
    )

    rows = []

    all_snapshot_rows = len(snapshots)

    for video_id, video_snapshots in (
        snapshots.groupby("video_id")
    ):
        video_snapshots = (
            video_snapshots
            .sort_values("collected_at")
            .reset_index(drop=True)
        )

        if video_id not in videos.index:
            drop_reasons[
                "thiếu_metadata_video"
            ] += len(video_snapshots)
            continue

        video = videos.loc[video_id]

        if pd.isna(video["published_at"]):
            drop_reasons[
                "thiếu_published_at"
            ] += len(video_snapshots)
            continue

        if (
            not settings.include_shorts
            and pd.notna(
                video["duration_seconds"]
            )
            and (
                video["duration_seconds"]
                <= settings.shorts_max_seconds
            )
        ):
            drop_reasons[
                "video_shorts_bị_loại"
            ] += len(video_snapshots)
            continue

        if (
            not settings.include_live_streams
            and _as_bool(
                video.get(
                    "has_live_streaming_details",
                    False,
                )
            )
            is True
        ):
            drop_reasons[
                "live_stream_bị_loại"
            ] += len(video_snapshots)
            continue

        channel_id = video["channel_id"]

        if channel_id not in channels.index:
            drop_reasons[
                "thiếu_thông_tin_kênh"
            ] += len(video_snapshots)
            continue

        channel = channels.loc[
            channel_id
        ]

        if pd.isna(
            channel[
                "channel_published_at"
            ]
        ):
            drop_reasons[
                "thiếu_ngày_tạo_kênh"
            ] += len(video_snapshots)
            continue

        if pd.isna(
            video["duration_seconds"]
        ):
            drop_reasons[
                "thiếu_duration"
            ] += len(video_snapshots)
            continue

        age_days = channel_age_days(
            channel[
                "channel_published_at"
            ],
            video["published_at"],
        )

        if age_days < 0:
            drop_reasons[
                "tuổi_kênh_âm"
            ] += len(video_snapshots)
            continue

        previous_stats = previous_video_stats(
            history_by_channel.get(
                channel_id
            ),
            video["published_at"],
            settings.previous_video_count,
            exclude_video_id=video_id,
            min_gap_hours=(
                settings
                .previous_video_min_gap_hours
            ),
        )

        for current_index in range(
            len(video_snapshots)
        ):
            current_snapshot = (
                video_snapshots.iloc[
                    current_index
                ]
            )

            later_snapshots = (
                video_snapshots.iloc[
                    current_index + 1:
                ]
            )

            future_snapshot = (
                _find_future_snapshot(
                    current_snapshot,
                    later_snapshots,
                    target_gap_hours,
                    tolerance_hours,
                )
            )

            if future_snapshot is None:
                drop_reasons[
                    "không_có_snapshot_tương_lai_gần_1_giờ"
                ] += 1
                continue

            current_view_count = float(
                current_snapshot[
                    "view_count"
                ]
            )

            future_view_count = float(
                future_snapshot[
                    "view_count"
                ]
            )

            views_gained = (
                future_view_count
                - current_view_count
            )

            if views_gained < 0:
                drop_reasons[
                    "lượt_xem_tương_lai_nhỏ_hơn_hiện_tại"
                ] += 1
                continue

            previous_snapshots = (
                video_snapshots.iloc[
                    :current_index
                ]
            )

            recent_rate = (
                _recent_views_per_hour(
                    previous_snapshots,
                    current_snapshot,
                )
            )

            snapshot_gap_hours = (
                future_snapshot[
                    "collected_at"
                ]
                - current_snapshot[
                    "collected_at"
                ]
            ).total_seconds() / 3600.0

            feature_row = build_feature_row(
                channel={
                    "channel_published_at": (
                        channel[
                            "channel_published_at"
                        ]
                    ),
                    "subscriber_count": (
                        current_snapshot.get(
                            "subscriber_count",
                            np.nan,
                        )
                    ),
                    "channel_video_count": (
                        current_snapshot.get(
                            "channel_video_count",
                            np.nan,
                        )
                    ),
                    "channel_total_views": (
                        current_snapshot.get(
                            "channel_total_views",
                            np.nan,
                        )
                    ),
                },
                previous=previous_stats,
                title=video.get(
                    "title",
                    "",
                ),
                description=video.get(
                    "description",
                    "",
                ),
                duration_seconds=video[
                    "duration_seconds"
                ],
                tags=video.get("tags"),
                publish_datetime=video[
                    "published_at"
                ],
                category_id=video.get(
                    "category_id",
                    "25",
                ),
                is_hd=_as_bool(
                    str(
                        video.get(
                            "definition",
                            "",
                        )
                    ).lower()
                    == "hd"
                ),
                has_caption=_as_bool(
                    video.get(
                        "caption",
                        np.nan,
                    )
                ),
                tz_name=(
                    settings
                    .feature_timezone
                ),
            )

            feature_row.update(
                {
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "channel_title": (
                        channel.get(
                            "channel_title",
                            "",
                        )
                    ),
                    "published_at": video[
                        "published_at"
                    ],
                    "snapshot_time": (
                        current_snapshot[
                            "collected_at"
                        ]
                    ),
                    "future_snapshot_time": (
                        future_snapshot[
                            "collected_at"
                        ]
                    ),
                    "previous_video_count_used": (
                        previous_stats[
                            "previous_video_count_used"
                        ]
                    ),
                    "snapshot_gap_hours": float(
                        snapshot_gap_hours
                    ),
                    "current_view_count": (
                        current_view_count
                    ),
                    "current_video_age_hours": float(
                        current_snapshot[
                            "video_age_hours"
                        ]
                    ),
                    "recent_views_per_hour": (
                        recent_rate
                    ),
                    TARGET: float(
                        views_gained
                    ),
                }
            )

            rows.append(feature_row)

    if rows:
        dataframe = pd.DataFrame(
            rows
        )

        dataframe = dataframe[
            PROCESSED_COLUMNS
        ]
    else:
        dataframe = pd.DataFrame(
            columns=PROCESSED_COLUMNS
        )

    before_deduplication = len(
        dataframe
    )

    if len(dataframe):
        dataframe = (
            dataframe
            .drop_duplicates(
                subset=[
                    "video_id",
                    "snapshot_time",
                ],
                keep="last",
            )
            .sort_values(
                [
                    "snapshot_time",
                    "video_id",
                ]
            )
            .reset_index(drop=True)
        )

    removed_duplicates = (
        before_deduplication
        - len(dataframe)
    )

    if removed_duplicates:
        drop_reasons[
            "trùng_video_id_snapshot_time"
        ] += removed_duplicates

    report = build_quality_report(
        all_snapshot_rows,
        dataframe,
        drop_reasons,
        extra={
            "duplicate_raw_rows_removed": (
                duplicate_raw_rows
            ),
            "channels_in_dataset": (
                int(
                    dataframe[
                        "channel_id"
                    ].nunique()
                )
                if len(dataframe)
                else 0
            ),
            "target": TARGET,
            "target_gap_hours": (
                target_gap_hours
            ),
            "target_tolerance_hours": (
                tolerance_hours
            ),
        },
    )

    return dataframe, report