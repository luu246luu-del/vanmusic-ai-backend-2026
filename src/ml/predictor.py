"""Tải mô hình đã lưu và dự đoán. Không bao giờ trả kết quả nếu chưa có mô hình."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.logger import get_logger
from src.ml.preprocessing import from_log_prediction, prepare_features

log = get_logger(__name__)


class ModelNotReadyError(RuntimeError):
    pass


class ViewPredictor:
    def __init__(self, model_file: str | Path, reports_dir: str | Path):
        self.model_file = Path(model_file)
        self.reports_dir = Path(reports_dir)
        self.pipeline = None
        self.metadata: dict = {}
        self.residuals: dict | None = None
        self.load_error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.pipeline is not None

    def load(self) -> bool:
        self.pipeline, self.metadata, self.residuals, self.load_error = None, {}, None, None
        if not self.model_file.exists():
            self.load_error = "Chưa có file mô hình."
            return False
        try:
            self.pipeline = joblib.load(self.model_file)
            meta = self.model_file.parent / "model_metadata.json"
            self.metadata = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            rq = self.reports_dir / "residual_quantiles.json"
            self.residuals = json.loads(rq.read_text(encoding="utf-8")) if rq.exists() else None
            return True
        except Exception as e:  # file hỏng / khác phiên bản sklearn
            log.error("Không tải được mô hình: %s", e)
            self.pipeline, self.load_error = None, f"Không tải được mô hình: {type(e).__name__}"
            return False

    def info(self) -> dict:
        md = self.metadata if self.is_ready else {}
        return {
            "model_loaded": self.is_ready, "model_name": md.get("model_name"),
            "model_version": md.get("model_version"), "trained_at": md.get("trained_at"),
            "target": md.get("target"), "feature_count": md.get("feature_count"),
            "metrics": md.get("metrics"), "baseline_metrics": md.get("baseline_metrics"),
            "data_period": md.get("data_period"), "is_synthetic": md.get("is_synthetic", False),
        }

    def predict(self, features: pd.DataFrame) -> dict:
        """Trả về dict: views, lower, upper, method (lower/upper = None nếu chưa có residual thực nghiệm)."""
        if not self.is_ready:
            raise ModelNotReadyError(self.load_error or "Mô hình chưa sẵn sàng.")
        X = prepare_features(features)
        pred_log = float(self.pipeline.predict(X)[0])
        views = float(from_log_prediction([pred_log])[0])
        lower = upper = method = None
        if self.residuals:
            lower = float(from_log_prediction([pred_log + self.residuals["lower_log_residual"]])[0])
            upper = float(from_log_prediction([pred_log + self.residuals["upper_log_residual"]])[0])
            method = self.residuals.get("method", "test_residual_quantiles")
        return {"views": views, "lower": lower, "upper": upper, "method": method}
