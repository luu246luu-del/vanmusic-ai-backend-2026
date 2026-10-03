"""Tạo snapshot lượt xem cho video mới để lấy nhãn views_after_1_hour (72 giờ). Chạy lặp bằng Task Scheduler/cron (nên mỗi 1-6 giờ)."""
from src.config import load_settings
from src.logger import get_logger, setup_logging
from src.youtube.client import YouTubeAPIError, YouTubeClient
from src.youtube.tracker import run_tracker


def main() -> int:
    s = load_settings()
    setup_logging(s.log_dir)
    log = get_logger("tracker")
    try:
        run_tracker(s, YouTubeClient(s.youtube_api_key, s.request_timeout_seconds, s.max_retries))
        return 0
    except YouTubeAPIError as e:
        log.error("%s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
