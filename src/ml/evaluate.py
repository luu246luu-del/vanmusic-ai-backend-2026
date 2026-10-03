"""Đánh giá mô hình trên đơn vị lượt xem THẬT, so sánh baseline, tạo biểu đồ."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error, r2_score


def regression_metrics(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)) if len(y_true) > 1 else float("nan"),
        "median_absolute_error": float(median_absolute_error(y_true, y_pred)),
        "n": int(len(y_true)),
    }


def baseline_metrics(train_df: pd.DataFrame, test_df: pd.DataFrame, target: str) -> dict:
    """3 baseline: avg_previous_views, median_previous_views, median target của Train."""
    y_test = test_df[target].values
    train_median = float(train_df[target].median())
    out = {}
    for name, col in [("avg_previous_views", "avg_previous_views"), ("median_previous_views", "median_previous_views")]:
        pred = test_df[col].fillna(train_median).values  # điền thiếu bằng thống kê của Train (không dùng Test)
        out[name] = regression_metrics(y_test, pred)
    out["train_median_target"] = regression_metrics(y_test, np.full(len(y_test), train_median))
    return out


def compare_with_baselines(model_m: dict, base_m: dict) -> dict:
    best_name = min(base_m, key=lambda k: base_m[k]["mae"])
    best = base_m[best_name]
    beats = bool(model_m["mae"] < best["mae"] and model_m["rmse"] < best["rmse"])
    return {"best_baseline": best_name, "beats_best_baseline_mae_and_rmse": beats,
            "mae_improvement_pct": float((best["mae"] - model_m["mae"]) / best["mae"] * 100) if best["mae"] else float("nan")}


def residual_quantiles(y_true, pred_log, quantiles=(0.1, 0.9)) -> dict:
    """Phân vị sai số trong không gian log1p (sai số nhân) từ tập Test."""
    res = np.log1p(np.asarray(y_true, float)) - np.asarray(pred_log, float)
    lo, hi = np.quantile(res, quantiles)
    cover = float(np.mean((res >= lo) & (res <= hi)))
    return {"method": "test_residual_quantiles", "space": "log1p", "quantiles": list(quantiles),
            "lower_log_residual": float(lo), "upper_log_residual": float(hi),
            "empirical_coverage_on_test": cover, "n_test": int(len(res))}


def save_plots(y_true, y_pred, out_dir: Path, title_suffix: str = "") -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    files = []

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_true + 1, y_pred + 1, s=14, alpha=0.6)
    lim = [1, max(y_true.max(), y_pred.max()) * 1.1 + 1]
    ax.plot(lim, lim, "r--", label="Dự đoán hoàn hảo")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Thực tế (lượt xem sau 3 ngày)"); ax.set_ylabel("Dự đoán")
    ax.set_title("Actual vs Predicted " + title_suffix); ax.legend()
    p = out_dir / "actual_vs_predicted.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig); files.append(p.name)

    resid = y_true - y_pred
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.scatter(y_pred, resid, s=14, alpha=0.6); ax.axhline(0, color="r", ls="--")
    ax.set_xlabel("Dự đoán (lượt xem)"); ax.set_ylabel("Sai số = thực tế - dự đoán")
    ax.set_title("Residual plot " + title_suffix)
    p = out_dir / "residual_plot.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig); files.append(p.name)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(resid, bins=30); ax.set_xlabel("Sai số (lượt xem)"); ax.set_ylabel("Số video")
    ax.set_title("Phân phối sai số " + title_suffix)
    p = out_dir / "error_distribution.png"; fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig); files.append(p.name)
    return files
