"""Kiểm tra schema và tạo báo cáo chất lượng dữ liệu."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pandas as pd

from src.data.schemas import FEATURE_COLUMNS, FORBIDDEN_FEATURES, TARGET


class SchemaError(ValueError):
    pass


def validate_schema(df: pd.DataFrame, required: list[str], name: str = "dataset") -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SchemaError(f"{name} thiếu các cột bắt buộc: {missing}")


def assert_no_forbidden_features(feature_names: list[str]) -> None:
    bad = [c for c in feature_names if c in FORBIDDEN_FEATURES or c == TARGET]
    if bad:
        raise SchemaError(f"Phát hiện đặc trưng bị cấm (rò rỉ dữ liệu): {bad}")


def build_quality_report(initial_rows: int, final_df: pd.DataFrame, drop_reasons: Counter,
                         extra: dict | None = None) -> dict:
    valid = int(len(final_df))
    missing = {}
    if valid:
        cols = [c for c in FEATURE_COLUMNS + [TARGET] if c in final_df.columns]
        missing = {c: round(float(final_df[c].isna().mean()), 4) for c in cols}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "initial_rows": int(initial_rows),
        "valid_rows": valid,
        "dropped_rows": int(initial_rows - valid),
        "drop_reasons": dict(drop_reasons),
        "missing_rate_per_column": missing,
    }
    if extra:
        report.update(extra)
    return report
