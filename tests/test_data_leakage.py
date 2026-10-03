"""Phát hiện rò rỉ dữ liệu: video tương lai, chính video đang xét, chia Train/Test, fit transformer."""

import numpy as np
import pandas as pd
import pytest

from src.data.feature_engineering import (
    build_training_dataset,
    previous_video_stats,
)
from src.data.schemas import (
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURES,
    TARGET,
)
from src.data.validator import (
    SchemaError,
    assert_no_forbidden_features,
)
from src.ml.preprocessing import (
    build_pipeline,
    prepare_features,
    to_log_target,
)
from src.ml.train import chronological_split


def _hist(n=20):
    base = pd.Timestamp("2026-01-01", tz="UTC")

    return pd.DataFrame(
        {
            "video_id": [f"v{i}" for i in range(n)],
            "published_at": [
                base + pd.Timedelta(days=i)
                for i in range(n)
            ],
            "view_count": [
                1000.0 * (i + 1)
                for i in range(n)
            ],
        }
    )


def test_future_video_does_not_change_stats():
    videos = _hist()
    reference_time = videos.loc[10, "published_at"]

    original_stats = previous_video_stats(
        videos,
        reference_time,
        exclude_video_id="v10",
    )

    modified_videos = videos.copy()

    # Thay đổi lượt xem của video tương lai.
    modified_videos.loc[15, "view_count"] = 9e12

    modified_stats = previous_video_stats(
        modified_videos,
        reference_time,
        exclude_video_id="v10",
    )

    assert original_stats == modified_stats


def test_current_video_is_not_in_its_own_history():
    videos = _hist()
    reference_time = videos.loc[10, "published_at"]

    original_stats = previous_video_stats(
        videos,
        reference_time,
        exclude_video_id="v10",
    )

    modified_videos = videos.copy()

    # Thay đổi lượt xem của chính video đang xét.
    modified_videos.loc[10, "view_count"] = 9e12

    modified_stats = previous_video_stats(
        modified_videos,
        reference_time,
        exclude_video_id="v10",
    )

    assert original_stats == modified_stats


def test_same_timestamp_video_is_excluded_even_without_exclude_id():
    videos = _hist()
    reference_time = videos.loc[10, "published_at"]

    stats = previous_video_stats(
        videos,
        reference_time,
    )

    expected_average = np.mean(
        [
            1000.0 * (i + 1)
            for i in range(10)
        ]
    )

    assert stats["previous_video_count_used"] == 10
    assert stats["avg_previous_views"] == expected_average


def test_forbidden_features_are_rejected():
    assert not set(FEATURE_COLUMNS) & set(FORBIDDEN_FEATURES)
    assert TARGET not in FEATURE_COLUMNS

    with pytest.raises(SchemaError):
        assert_no_forbidden_features(
            FEATURE_COLUMNS + ["like_count"]
        )


def test_chronological_split_has_no_time_overlap(synthetic_df):
    train, test = chronological_split(
        synthetic_df,
        0.8,
        embargo_hours=1,
    )

    train_times = pd.to_datetime(
        train["published_at"],
        utc=True,
    )

    test_times = pd.to_datetime(
        test["published_at"],
        utc=True,
    )

    assert (
        train_times.max()
        <= test_times.min() - pd.Timedelta(hours=1)
    )

    assert (
        len(
            set(train["video_id"])
            & set(test["video_id"])
        )
        == 0
    )


def test_transformers_fit_only_on_train(synthetic_df):
    train, test = chronological_split(
        synthetic_df,
        0.8,
        embargo_hours=1,
    )

    pipeline = build_pipeline().fit(
        prepare_features(train),
        to_log_target(train[TARGET]),
    )

    scaler = (
        pipeline
        .named_steps["preprocess"]
        .named_transformers_["num"]
        .named_steps["scale"]
    )

    train_mean = (
        prepare_features(train)[["channel_age_days"]]
        .mean()
        .iloc[0]
    )

    all_data_mean = (
        prepare_features(synthetic_df)[["channel_age_days"]]
        .mean()
        .iloc[0]
    )

    assert scaler.mean_[0] == pytest.approx(train_mean)
    assert scaler.mean_[0] != pytest.approx(all_data_mean)


def _raw_frames(
    with_target_snapshot=True,
    future_views=None,
):
    published_start = pd.Timestamp(
        "2026-03-01T10:00:00Z"
    )

    videos = []
    snapshots = []

    channel_id = "UC" + ("x" * 22)

    for index in range(12):
        published_at = (
            published_start
            + pd.Timedelta(days=index * 3)
        )

        videos.append(
            {
                "video_id": f"v{index}",
                "channel_id": channel_id,
                "title": f"Bài {index}",
                "description": "d",
                "published_at": published_at.isoformat(),
                "tags": '["a"]',
                "category_id": "25",
                "duration_seconds": 240,
                "definition": "hd",
                "caption": False,
                "view_count": 1000 * (index + 1),
                "has_live_streaming_details": False,
                "collected_at": (
                    "2026-09-01T00:00:00Z"
                ),
            }
        )

    if future_views is not None:
        videos[11]["view_count"] = future_views

    target_video_index = 8

    target_published_at = (
        published_start
        + pd.Timedelta(
            days=target_video_index * 3
        )
    )

    # Snapshot sớm, chưa đạt mốc một giờ.
    snapshots.append(
        {
            "video_id": f"v{target_video_index}",
            "channel_id": channel_id,
            "published_at": (
                target_published_at.isoformat()
            ),
            "collected_at": (
                target_published_at
                + pd.Timedelta(hours=0.1)
            ).isoformat(),
            "video_age_hours": 0.1,
            "view_count": 10,
            "subscriber_count": 1000,
            "hidden_subscriber_count": False,
            "channel_total_views": 10**6,
            "channel_video_count": 100,
        }
    )

    if with_target_snapshot:
        # Snapshot mục tiêu khi video đủ một giờ tuổi.
        snapshots.append(
            {
                **snapshots[0],
                "collected_at": (
                    target_published_at
                    + pd.Timedelta(hours=1)
                ).isoformat(),
                "video_age_hours": 1.0,
                "view_count": 5555,
            }
        )

    channels = pd.DataFrame(
        [
            {
                "channel_id": channel_id,
                "channel_title": "K",
                "channel_published_at": (
                    "2015-01-01T00:00:00Z"
                ),
                "collected_at": (
                    "2026-09-01T00:00:00Z"
                ),
            }
        ]
    )

    return (
        pd.DataFrame(videos),
        channels,
        pd.DataFrame(snapshots),
    )


def test_build_dataset_uses_only_earlier_videos(settings):
    videos, channels, snapshots = _raw_frames()

    dataset, report = build_training_dataset(
        videos,
        channels,
        snapshots,
        settings,
    )

    assert len(dataset) == 1
    assert dataset.loc[0, TARGET] == 5545

    assert (
        dataset.loc[
            0,
            "previous_video_count_used",
        ]
        == 8
    )

    expected_average = np.mean(
        [
            1000 * (index + 1)
            for index in range(8)
        ]
    )

    assert (
        dataset.loc[0, "avg_previous_views"]
        == expected_average
    )

    modified_videos, modified_channels, modified_snapshots = (
        _raw_frames(
            future_views=10**10
        )
    )

    modified_dataset, _ = build_training_dataset(
        modified_videos,
        modified_channels,
        modified_snapshots,
        settings,
    )

    assert (
        modified_dataset.loc[
            0,
            "avg_previous_views",
        ]
        == dataset.loc[
            0,
            "avg_previous_views",
        ]
    )


def test_video_without_1h_snapshot_is_not_labeled(settings):
    videos, channels, snapshots = _raw_frames(
        with_target_snapshot=False
    )

    dataset, report = build_training_dataset(
        videos,
        channels,
        snapshots,
        settings,
    )

    assert len(dataset) == 0

    drop_reasons = report["drop_reasons"]

    reason_found = any(
        "snapshot" in str(reason).lower()
        for reason in drop_reasons
    )

    assert reason_found


def test_snapshot_outside_tolerance_is_rejected(settings):
    videos, channels, snapshots = _raw_frames()

    target_mask = (
        snapshots["video_age_hours"] == 1.0
    )

    published_at = pd.Timestamp(
        snapshots.iloc[0]["published_at"]
    )

    snapshots.loc[
        target_mask,
        "collected_at",
    ] = (
        published_at
        + pd.Timedelta(hours=2)
    ).isoformat()

    snapshots.loc[
        target_mask,
        "video_age_hours",
    ] = 2.0

    dataset, report = build_training_dataset(
        videos,
        channels,
        snapshots,
        settings,
    )

    assert len(dataset) == 0