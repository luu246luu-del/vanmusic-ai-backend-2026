"""Huấn luyện LinearRegression trên log1p(views_after_1_hour), chia Train/Test THEO THỜI GIAN."""
from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from src.config import Settings
from src.data.schemas import DEMO_BANNER, FEATURE_COLUMNS, TARGET
from src.data.validator import assert_no_forbidden_features, validate_schema
from src.logger import get_logger
from src.ml.evaluate import (baseline_metrics, compare_with_baselines, regression_metrics,
                             residual_quantiles, save_plots)
from src.ml.preprocessing import build_pipeline, from_log_prediction, prepare_features, to_log_target

log = get_logger(__name__)


class InsufficientDataError(RuntimeError):
    pass


def chronological_split(df: pd.DataFrame, train_ratio: float, embargo_hours: float = 0.0):
    """Video cũ -> Train, video mới -> Test. Có 'embargo': loại khỏi Train các video có cửa sổ 72h chồng lấn thời
    điểm bắt đầu của Test (nhãn của chúng được đo khi Test đã bắt đầu)."""
    d = df.sort_values("published_at").reset_index(drop=True)
    cut = int(len(d) * train_ratio)
    if cut < 1 or cut >= len(d):
        raise InsufficientDataError("Không đủ dữ liệu để chia Train/Test.")
    test = d.iloc[cut:].copy()
    train = d.iloc[:cut].copy()
    test_start = pd.to_datetime(test["published_at"], utc=True).min()
    pub = pd.to_datetime(train["published_at"], utc=True)
    train = train[pub <= test_start - pd.Timedelta(hours=embargo_hours)]
    if len(train) < 2:
        raise InsufficientDataError("Tập Train quá nhỏ sau khi áp embargo thời gian.")
    return train.reset_index(drop=True), test.reset_index(drop=True)


def train_model(df: pd.DataFrame, settings: Settings, synthetic: bool = False,
                model_file: Path | None = None, reports_dir: Path | None = None) -> dict:
    validate_schema(df, FEATURE_COLUMNS + [TARGET, "published_at"], "training dataset")
    assert_no_forbidden_features(FEATURE_COLUMNS)
    df = df.copy()
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
    df = df[df[TARGET].notna() & (df[TARGET] >= 0)]

    if len(df) < settings.minimum_training_rows:
        raise InsufficientDataError(
            f"Chỉ có {len(df)} dòng dữ liệu hợp lệ, cần tối thiểu {settings.minimum_training_rows}. "
            "DỪNG huấn luyện: hãy thu thập thêm dữ liệu thật (chạy collector/tracker nhiều ngày).")

    model_file = Path(model_file or settings.model_file)
    reports_dir = Path(reports_dir or settings.reports_dir)
    model_file.parent.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    train_df, test_df = chronological_split(df, settings.train_ratio, embargo_hours=settings.target_age_hours)
    X_train, X_test = prepare_features(train_df), prepare_features(test_df)
    y_train_log, y_test = to_log_target(train_df[TARGET]), test_df[TARGET].values.astype(float)

    pipe = build_pipeline()
    pipe.fit(X_train, y_train_log)                      # transformer chỉ thấy dữ liệu Train
    pred_log = pipe.predict(X_test)
    y_pred = from_log_prediction(pred_log)              # expm1 + chặn >= 0 => đơn vị lượt xem thật

    metrics = regression_metrics(y_test, y_pred)
    metrics["r2_log_space"] = float(regression_metrics(np.log1p(y_test), pred_log)["r2"])
    base = baseline_metrics(train_df, test_df, TARGET)
    comparison = compare_with_baselines(metrics, base)
    rq = residual_quantiles(y_test, pred_log, settings.interval_quantiles) \
        if len(y_test) >= settings.minimum_test_rows_for_interval else None

    version = datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    metadata = {
        "model_name": "LinearRegression", "model_version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": TARGET, "target_transform": "log1p (dự đoán) / expm1 (đổi về lượt xem)",
        "feature_names": FEATURE_COLUMNS, "feature_count": len(FEATURE_COLUMNS),
        "is_synthetic": bool(synthetic),
        "data_period": {"train_start": str(train_df["published_at"].min()), "train_end": str(train_df["published_at"].max()),
                        "test_start": str(test_df["published_at"].min()), "test_end": str(test_df["published_at"].max()),
                        "n_train": int(len(train_df)), "n_test": int(len(test_df)),
                        "n_channels": int(df["channel_id"].nunique()) if "channel_id" in df else None},
        "library_versions": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                             "pandas": pd.__version__, "numpy": np.__version__, "joblib": joblib.__version__},
        "metrics": metrics, "baseline_metrics": base, "baseline_comparison": comparison,
    }
    if synthetic:
        metadata["warning"] = DEMO_BANNER

    joblib.dump(pipe, model_file)
    with open(model_file.parent / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    with open(reports_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "baseline_metrics": base, "baseline_comparison": comparison}, f, ensure_ascii=False, indent=2)
    if rq:
        with open(reports_dir / "residual_quantiles.json", "w", encoding="utf-8") as f:
            json.dump(rq, f, indent=2)
    elif (reports_dir / "residual_quantiles.json").exists():
        (reports_dir / "residual_quantiles.json").unlink()  # tránh dùng khoảng của mô hình cũ
    save_plots(y_test, y_pred, reports_dir, "(SYNTHETIC)" if synthetic else "")
    write_model_card(metadata, comparison, rq, reports_dir / "model_card.md")
    log.info("Đã lưu mô hình %s tại %s", version, model_file)
    return metadata


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.4f}"


def write_model_card(md: dict, comp: dict, rq: dict | None, path: Path) -> None:
    m, b, dp = md["metrics"], md["baseline_metrics"], md["data_period"]
    banner = f"> **{DEMO_BANNER}**\n\n" if md.get("is_synthetic") else ""
    verdict = ("Mô hình **vượt** baseline tốt nhất trên cả MAE và RMSE của tập Test."
               if comp["beats_best_baseline_mae_and_rmse"] else
               "Mô hình **KHÔNG vượt** baseline tốt nhất trên cả MAE và RMSE => **không được coi là mô hình tốt**.")
    rows = "\n".join(f"| {k} | {_fmt(v['mae'])} | {_fmt(v['rmse'])} | {v['r2']:.4f} | {_fmt(v['median_absolute_error'])} |"
                     for k, v in b.items())
    interval = ("Có khoảng tham khảo thực nghiệm từ phân vị residual của tập Test "
                f"(độ phủ thực nghiệm trên Test = {rq['empirical_coverage_on_test']:.2%}; lạc quan vì tính trên chính tập Test)."
                if rq else "Chưa đủ dòng Test để tạo khoảng tham khảo; API trả lower/upper = null.")
    text = f"""# Model Card - YouTube View Predictor

{banner}## Mục tiêu
Dự báo số lượt xem một video YouTube đạt được sau khoảng 72 giờ (3 ngày) kể từ khi xuất bản.

## Thuật toán
`sklearn.linear_model.LinearRegression` trong `Pipeline` (SimpleImputer, log1p, StandardScaler, OneHotEncoder(handle_unknown="ignore")).
Mô hình dự đoán `log1p(views_after_1_hour)`, sau đó `expm1` và chặn tối thiểu 0.

## Dữ liệu
- Phiên bản mô hình: `{md['model_version']}`, huấn luyện lúc `{md['trained_at']}`
- Số kênh: {dp['n_channels']}; Train = {dp['n_train']} video ({dp['train_start']} -> {dp['train_end']}); Test = {dp['n_test']} video ({dp['test_start']} -> {dp['test_end']})
- Nhãn `views_after_1_hour` chỉ lấy từ snapshot đo trong dung sai quanh mốc 72 giờ; không nội suy.

## Đặc trưng ({md['feature_count']})
{', '.join(f'`{f}`' for f in md['feature_names'])}

## Target
`views_after_1_hour`

## Chia Train/Test
Theo thời gian (video cũ để huấn luyện, video mới để kiểm tra), có embargo 72 giờ để tránh nhãn Train chồng lấn thời gian Test.

## Metrics (Test, đơn vị lượt xem thật)
| MAE | RMSE | R² | Median AE | R² (log) |
|---|---|---|---|---|
| {_fmt(m['mae'])} | {_fmt(m['rmse'])} | {m['r2']:.4f} | {_fmt(m['median_absolute_error'])} | {m['r2_log_space']:.4f} |

## Baseline (Test)
| Baseline | MAE | RMSE | R² | Median AE |
|---|---|---|---|---|
{rows}

{verdict} (baseline tốt nhất theo MAE: `{comp['best_baseline']}`, cải thiện MAE {comp['mae_improvement_pct']:.1f}%).

## Khoảng tham khảo
{interval}

## Hạn chế
- Hồi quy tuyến tính chỉ nắm bắt quan hệ tuyến tính trong không gian log; video "bùng nổ" thường bị dự báo thấp.
- Chỉ dùng thông tin biết trước khi đăng; không biết chất lượng nội dung, thumbnail, quảng bá, sự kiện bên ngoài.
- `subscriber_count`, `channel_total_views`, `channel_video_count` lấy từ snapshot đầu tiên sau khi đăng (<= max_channel_stats_age_hours), không phải đúng thời điểm đăng.
- Lượt xem các video trước là giá trị mới nhất đã thu thập, không phải giá trị tại thời điểm video đang xét được đăng.

## Sai lệch dữ liệu
- Chỉ gồm các kênh trong `channels.csv` (thiên lệch chọn mẫu); tập nhỏ có thể không đại diện cho toàn YouTube.
- Chỉ video được tracker bắt kịp trong cửa sổ 72 giờ mới có nhãn.
- Phân phối lượt xem lệch mạnh; kênh rất lớn có ảnh hưởng lớn tới sai số tuyệt đối.

## Trường hợp không nên dùng
Ra quyết định tài chính/hợp đồng quảng cáo, kênh mới không có lịch sử, video Shorts/livestream (nếu bị loại khỏi huấn luyện), nội dung ngoài lĩnh vực âm nhạc đã huấn luyện.

## Cảnh báo
Tương quan không chứng minh quan hệ nhân quả: đổi tiêu đề hay giờ đăng theo hệ số của mô hình không đảm bảo tăng lượt xem.
Kết quả chỉ mang tính tham khảo.
"""
    path.write_text(text, encoding="utf-8")
