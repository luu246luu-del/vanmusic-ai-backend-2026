"""Lưu trữ CSV dạng chỉ-thêm (append-only). Không bao giờ ghi đè dữ liệu raw cũ."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.logger import get_logger

log = get_logger(__name__)


def read_csv_safe(path: str | Path, **kwargs) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(p, encoding="utf-8", **kwargs)


def append_dedup(path: str | Path, df: pd.DataFrame, key_cols: list[str]) -> int:
    """Thêm các dòng chưa có (theo key_cols) vào cuối file. Trả về số dòng đã thêm."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if df is None or df.empty:
        return 0
    df = df.drop_duplicates(subset=key_cols, keep="last").copy()

    if p.exists() and p.stat().st_size > 0:
        existing_cols = list(pd.read_csv(p, nrows=0, encoding="utf-8").columns)
        existing_keys = pd.read_csv(p, usecols=key_cols, dtype=str, encoding="utf-8")
        seen = set(map(tuple, existing_keys.astype(str).values.tolist()))
        mask = [tuple(map(str, row)) not in seen for row in df[key_cols].astype(str).values.tolist()]
        df = df.loc[mask]
        if df.empty:
            return 0
        missing = [c for c in df.columns if c not in existing_cols]
        if missing:
            log.warning("Cột mới %s không có trong file %s; sẽ bị bỏ qua để giữ nguyên schema cũ.", missing, p.name)
        df = df.reindex(columns=existing_cols)
        df.to_csv(p, mode="a", header=False, index=False, encoding="utf-8")
    else:
        df.to_csv(p, mode="w", header=True, index=False, encoding="utf-8")
    return len(df)
