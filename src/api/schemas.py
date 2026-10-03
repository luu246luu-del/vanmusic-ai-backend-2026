"""Pydantic schemas cho REST API.

Tên trường phải đồng bộ với API contract của VanMusic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class VanMusicPredictRequest(BaseModel):
    channel_id: str = Field(
        ...,
        min_length=1,
        max_length=300,
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=300,
    )
    description: str = Field(
        "",
        max_length=10000,
    )
    duration_seconds: int = Field(
        ...,
        ge=1,
        le=86400 * 2,
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    publish_datetime: datetime
    category_id: str = Field(
        "25",
        max_length=10,
    )
    is_hd: bool = True
    has_caption: bool = False

    # Trạng thái của video tại thời điểm dự báo.
    current_view_count: int = Field(
        ...,
        ge=0,
    )
    current_video_age_hours: float = Field(
        ...,
        ge=0,
    )
    recent_views_per_hour: float = Field(
        ...,
        ge=0,
    )

    user_id: Optional[str] = Field(
        None,
        max_length=200,
    )
    client_request_id: Optional[str] = Field(
        None,
        max_length=200,
    )

    @field_validator("channel_id", "title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "Không được để trống."
            )

        return value.strip()


class ManualPredictRequest(BaseModel):
    """Dự báo khi người dùng tự nhập thống kê kênh và video."""

    channel_title: str = Field(
        "Kênh nhập thủ công",
        max_length=200,
    )
    channel_age_days: int = Field(
        ...,
        ge=0,
    )
    subscriber_count: Optional[int] = Field(
        None,
        ge=0,
    )
    channel_video_count: int = Field(
        ...,
        ge=0,
    )
    channel_total_views: int = Field(
        ...,
        ge=0,
    )
    avg_previous_views: float = Field(
        ...,
        ge=0,
    )
    median_previous_views: float = Field(
        ...,
        ge=0,
    )
    previous_video_count_used: int = Field(
        10,
        ge=0,
    )

    title: str = Field(
        ...,
        min_length=1,
        max_length=300,
    )
    description: str = Field(
        "",
        max_length=10000,
    )
    duration_seconds: int = Field(
        ...,
        ge=1,
        le=86400 * 2,
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    publish_datetime: datetime
    category_id: str = Field(
        "25",
        max_length=10,
    )
    is_hd: bool = True
    has_caption: bool = False

    # Trạng thái của video tại thời điểm dự báo.
    current_view_count: int = Field(
        ...,
        ge=0,
    )
    current_video_age_hours: float = Field(
        ...,
        ge=0,
    )
    recent_views_per_hour: float = Field(
        ...,
        ge=0,
    )

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "Tiêu đề không được để trống."
            )

        return value.strip()

class LatestVideoPredictRequest(BaseModel):
    """Yêu cầu tự động dự báo video mới nhất của một kênh."""

    channel_id: str = Field(
        ...,
        min_length=1,
        max_length=300,
    )

    @field_validator("channel_id")
    @classmethod
    def _channel_id_not_blank(
        cls,
        value: str,
    ) -> str:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError(
                "Mã hoặc đường dẫn kênh không được để trống."
            )

        return normalized_value
class CollectChannelRequest(BaseModel):
    channel_id: str = Field(
        ...,
        min_length=1,
        max_length=300,
    )
    max_videos: Optional[int] = Field(
        None,
        ge=1,
        le=500,
    )


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ApiEnvelope(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[ApiErrorBody] = None
    request_id: str