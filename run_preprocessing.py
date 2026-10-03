"""Dựng tập huấn luyện từ raw + snapshots và tạo báo cáo chất lượng dữ liệu."""
import json

from src.config import load_settings
from src.data.feature_engineering import build_training_dataset
from src.data.storage import read_csv_safe
from src.logger import get_logger, setup_logging


def main() -> int:
    s = load_settings()
    setup_logging(s.log_dir)
    log = get_logger("preprocessing")
    videos, channels, snaps = (read_csv_safe(p) for p in (s.raw_videos_file, s.raw_channels_file, s.snapshots_file))
    if videos.empty or channels.empty or snaps.empty:
        log.error("Thiếu dữ liệu raw/snapshot. Hãy chạy run_collector.py và run_tracker.py trước "
                  "(tracker cần chạy lặp ít nhất vài ngày để có nhãn 72 giờ).")
        return 1
    df, report = build_training_dataset(videos, channels, snaps, s)
    s.processed_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(s.processed_file, index=False, encoding="utf-8")
    s.quality_report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Dòng ban đầu=%d | hợp lệ=%d | bị loại=%d | lý do=%s", report["initial_rows"], report["valid_rows"],
             report["dropped_rows"], report["drop_reasons"])
    log.info("Đã ghi %s và %s", s.processed_file, s.quality_report_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
