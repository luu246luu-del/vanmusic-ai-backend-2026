"""Thu thập thông tin kênh + video (lịch sử) từ YouTube Data API v3 vào data/raw (chỉ thêm, không ghi đè)."""
from src.config import load_settings
from src.data.schemas import RAW_CHANNEL_COLUMNS
from src.data.storage import append_dedup
from src.logger import get_logger, setup_logging
from src.youtube.channel_collector import channels_to_frame, fetch_channels, read_channel_ids, utc_now_iso
from src.youtube.client import YouTubeAPIError, YouTubeClient
from src.youtube.video_collector import fetch_upload_video_ids, fetch_video_details, videos_to_frame


def main() -> int:
    s = load_settings()
    setup_logging(s.log_dir)
    log = get_logger("collector")
    try:
        client = YouTubeClient(s.youtube_api_key, s.request_timeout_seconds, s.max_retries)
        ids = read_channel_ids(s.resolve(s.channels_csv))
        if not ids:
            log.error("channels.csv chưa có Channel ID hợp lệ (xem data/sample/channels.csv).")
            return 1
        collected_at = utc_now_iso()
        channels = fetch_channels(client, ids, collected_at)
        n = append_dedup(s.raw_channels_file, channels_to_frame(channels), ["channel_id", "collected_at"])
        log.info("Đã thêm %d dòng kênh vào %s", n, s.raw_channels_file)
        total = 0
        for ch in channels:
            try:
                vids = fetch_upload_video_ids(client, ch["uploads_playlist_id"], s.max_videos_per_channel)
                rows = fetch_video_details(client, vids, collected_at)
                total += append_dedup(s.raw_videos_file, videos_to_frame(rows), ["video_id", "collected_at"])
                log.info("Kênh %s: %d video", ch["channel_title"], len(rows))
            except YouTubeAPIError as e:
                log.error("Kênh %s lỗi: %s", ch["channel_id"], e)
        log.info("Hoàn tất. Đã thêm %d dòng video vào %s", total, s.raw_videos_file)
        return 0
    except YouTubeAPIError as e:
        log.error("%s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
