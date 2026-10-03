"""Pipeline scikit-learn: toàn bộ tiền xử lý + LinearRegression nằm trong MỘT Pipeline.

Transformer chỉ được fit trên tập Train (Pipeline.fit(X_train, y_train)) => không rò rỉ thống kê từ Test.
Mô hình dự đoán log1p(views_after_1_hour); dùng expm1 để đổi về lượt xem thật.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from src.data.schemas import (BINARY_FEATURES, CATEGORICAL_FEATURES, FEATURE_COLUMNS, LOG_FEATURES,
                              NUMERIC_FEATURES)

MAX_LOG_PREDICTION = 25.0  # expm1(25) ~ 7,2e10: chặn tràn số


def _cat_value(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return np.nan
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Đưa DataFrame về đúng cột/thứ tự/kiểu dữ liệu mà Pipeline mong đợi (không tính thống kê nào)."""
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Thiếu đặc trưng: {missing}")
    X = df[FEATURE_COLUMNS].copy()
    for c in LOG_FEATURES + NUMERIC_FEATURES + BINARY_FEATURES:
        X[c] = pd.to_numeric(X[c], errors="coerce").astype(float)
    for c in CATEGORICAL_FEATURES:
        X[c] = pd.Series([_cat_value(v) for v in X[c]], index=X.index, dtype=object)
    return X


def build_pipeline() -> Pipeline:
    log_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("log1p", FunctionTransformer(np.log1p, inverse_func=np.expm1, feature_names_out="one-to-one")),
        ("scale", StandardScaler()),
    ])
    num_pipe = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    cat_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    bin_pipe = Pipeline([("impute", SimpleImputer(strategy="most_frequent"))])
    pre = ColumnTransformer([
        ("log_num", log_pipe, LOG_FEATURES),
        ("num", num_pipe, NUMERIC_FEATURES),
        ("cat", cat_pipe, CATEGORICAL_FEATURES),
        ("bin", bin_pipe, BINARY_FEATURES),
    ], remainder="drop")
    return Pipeline([("preprocess", pre), ("model", LinearRegression())])


def to_log_target(y) -> np.ndarray:
    return np.log1p(np.asarray(y, dtype=float))


def from_log_prediction(pred_log) -> np.ndarray:
    """expm1 rồi chặn tối thiểu 0 (không có lượt xem âm)."""
    pred_log = np.clip(np.asarray(pred_log, dtype=float), None, MAX_LOG_PREDICTION)
    return np.clip(np.expm1(pred_log), 0.0, None)
