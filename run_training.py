"""Huấn luyện LinearRegression. Dừng nếu chưa đủ dữ liệu thật.

  python run_training.py                      # dữ liệu thật: data/processed/training_dataset.csv
  python run_training.py --synthetic-demo     # CHỈ để thử pipeline; lưu vào models/demo/ (SYNTHETIC DEMO DATA)
"""
import argparse

import pandas as pd

from src.config import load_settings
from src.data.schemas import DEMO_BANNER
from src.data.storage import read_csv_safe
from src.logger import get_logger, setup_logging
from src.ml.train import InsufficientDataError, train_model


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic-demo", action="store_true", help="dùng dữ liệu GIẢ (không dùng để đánh giá thực tế)")
    args = ap.parse_args()
    s = load_settings()
    setup_logging(s.log_dir)
    log = get_logger("training")
    try:
        if args.synthetic_demo:
            src = s.resolve("data/synthetic_demo/training_dataset_SYNTHETIC.csv")
            if not src.exists():
                log.error("Chưa có dữ liệu giả. Chạy: python scripts/generate_synthetic_demo.py")
                return 1
            log.warning("=== %s ===", DEMO_BANNER)
            df = pd.read_csv(src)
            meta = train_model(df, s, synthetic=True, model_file=s.resolve("models/demo/model.joblib"),
                               reports_dir=s.resolve("models/demo/reports"))
        else:
            df = read_csv_safe(s.processed_file)
            if df.empty:
                log.error("Chưa có %s. Hãy chạy run_preprocessing.py trước.", s.processed_file)
                return 1
            meta = train_model(df, s)
        m, c = meta["metrics"], meta["baseline_comparison"]
        log.info("MAE=%.1f RMSE=%.1f R2=%.4f MedAE=%.1f | baseline tốt nhất: %s | vượt baseline: %s",
                 m["mae"], m["rmse"], m["r2"], m["median_absolute_error"], c["best_baseline"],
                 c["beats_best_baseline_mae_and_rmse"])
        return 0
    except InsufficientDataError as e:
        log.error("%s", e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
