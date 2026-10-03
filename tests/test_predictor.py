import numpy as np
import pandas as pd
import pytest

from src.data.schemas import FEATURE_COLUMNS, TARGET
from src.ml.predictor import ModelNotReadyError, ViewPredictor
from src.ml.preprocessing import build_pipeline, from_log_prediction, prepare_features, to_log_target
from src.ml.train import InsufficientDataError, train_model


def test_pipeline_fit_and_predict(synthetic_df):
    X, y = prepare_features(synthetic_df), to_log_target(synthetic_df[TARGET])
    pipe = build_pipeline().fit(X, y)
    assert pipe.predict(X).shape == (len(X),)
    assert type(pipe.named_steps["model"]).__name__ == "LinearRegression"


def test_predictions_never_negative():
    assert (from_log_prediction([-50.0, -1.0, 0.0]) >= 0).all()


def test_inverse_log_is_correct():
    y = np.array([0, 10, 12345, 9_876_543])
    assert np.allclose(from_log_prediction(np.log1p(y)), y)


def test_pipeline_handles_missing_values_and_unknown_category(synthetic_df):
    pipe = build_pipeline().fit(prepare_features(synthetic_df), to_log_target(synthetic_df[TARGET]))
    row = synthetic_df.iloc[[0]].copy()
    row["subscriber_count"] = np.nan
    row["avg_previous_views"] = np.nan
    row["category_id"] = "99999"     # danh mục chưa từng thấy
    out = pipe.predict(prepare_features(row))
    assert np.isfinite(out).all()


def test_train_stops_when_not_enough_rows(settings, synthetic_df):
    with pytest.raises(InsufficientDataError):
        train_model(synthetic_df.head(20), settings)


def test_missing_model_file_means_not_ready(tmp_path):
    p = ViewPredictor(tmp_path / "nope.joblib", tmp_path)
    assert p.load() is False and p.is_ready is False
    assert p.info()["model_loaded"] is False
    with pytest.raises(ModelNotReadyError):
        p.predict(pd.DataFrame([{c: 1 for c in FEATURE_COLUMNS}]))


def test_train_save_load_predict_roundtrip(trained_settings, synthetic_df):
    p = ViewPredictor(trained_settings.model_file, trained_settings.reports_dir)
    assert p.load()
    res = p.predict(synthetic_df.iloc[[5]])
    assert res["views"] >= 0 and res["lower"] <= res["views"] <= res["upper"]
    assert res["method"] == "test_residual_quantiles"
    info = p.info()
    assert info["model_name"] == "LinearRegression" and info["target"] == TARGET and info["feature_count"] == 19
    assert (trained_settings.reports_dir / "model_card.md").exists()


def test_metrics_are_computed_in_real_view_units(trained_settings):
    import json
    md = json.loads((trained_settings.model_file.parent / "model_metadata.json").read_text(encoding="utf-8"))
    assert md["metrics"]["mae"] > 0          # đơn vị lượt xem thật, không phải log
    assert set(md["baseline_metrics"]) == {"avg_previous_views", "median_previous_views", "train_median_target"}
