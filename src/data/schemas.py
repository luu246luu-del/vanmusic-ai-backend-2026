"""Định nghĩa các cột dữ liệu dùng chung cho toàn bộ dự án."""

# Mô hình dự báo số lượt xem tăng thêm trong một giờ tiếp theo.
TARGET = "views_gained_next_1_hour"


# Các đặc trưng có sẵn tại thời điểm thực hiện dự báo.
FEATURE_COLUMNS = [
    "channel_age_days",
    "subscriber_count",
    "channel_video_count",
    "channel_total_views",
    "avg_previous_views",
    "median_previous_views",
    "duration_seconds",
    "title_length",
    "title_word_count",
    "tag_count",
    "description_length",
    "publish_hour",
    "publish_day_of_week",
    "category_id",
    "is_hd",
    "has_caption",
    "current_view_count",
    "current_video_age_hours",
    "recent_views_per_hour",
]


# Các biến đếm có độ lệch lớn.
LOG_FEATURES = [
    "subscriber_count",
    "channel_total_views",
    "avg_previous_views",
    "median_previous_views",
    "current_view_count",
    "recent_views_per_hour",
]


# Các đặc trưng số thông thường.
NUMERIC_FEATURES = [
    "channel_age_days",
    "channel_video_count",
    "duration_seconds",
    "title_length",
    "title_word_count",
    "tag_count",
    "description_length",
    "publish_hour",
    "current_video_age_hours",
]


# Các đặc trưng phân loại.
CATEGORICAL_FEATURES = [
    "publish_day_of_week",
    "category_id",
]


# Các đặc trưng nhị phân.
BINARY_FEATURES = [
    "is_hd",
    "has_caption",
]


# Các cột tương lai hoặc không được dùng làm đầu vào mô hình.
FORBIDDEN_FEATURES = [
    "views_gained_next_1_hour",
    "future_view_count",
    "like_count",
    "comment_count",
    "trending_rank",
]


# Cột thông tin bổ trợ, không phải đặc trưng mô hình.
META_COLUMNS = [
    "video_id",
    "channel_id",
    "channel_title",
    "published_at",
    "snapshot_time",
    "future_snapshot_time",
    "previous_video_count_used",
    "snapshot_gap_hours",
]


# Schema video thô.
RAW_VIDEO_COLUMNS = [
    "video_id",
    "channel_id",
    "title",
    "description",
    "published_at",
    "tags",
    "category_id",
    "duration",
    "duration_seconds",
    "definition",
    "caption",
    "view_count",
    "like_count",
    "comment_count",
    "has_live_streaming_details",
    "live_broadcast_content",
    "collected_at",
]


# Schema kênh thô.
RAW_CHANNEL_COLUMNS = [
    "channel_id",
    "channel_title",
    "channel_published_at",
    "subscriber_count",
    "hidden_subscriber_count",
    "channel_total_views",
    "channel_video_count",
    "uploads_playlist_id",
    "collected_at",
]


# Schema snapshot lượt xem.
SNAPSHOT_COLUMNS = [
    "video_id",
    "channel_id",
    "published_at",
    "collected_at",
    "video_age_hours",
    "view_count",
    "subscriber_count",
    "hidden_subscriber_count",
    "channel_total_views",
    "channel_video_count",
]


# Cấu trúc cuối cùng của tập dữ liệu huấn luyện.
PROCESSED_COLUMNS = (
    META_COLUMNS
    + FEATURE_COLUMNS
    + [TARGET]
)


# Cảnh báo bắt buộc cho dữ liệu minh họa.
DEMO_BANNER = (
    "SYNTHETIC DEMO DATA - "
    "KHÔNG DÙNG ĐỂ ĐÁNH GIÁ MÔ HÌNH THỰC TẾ"
)