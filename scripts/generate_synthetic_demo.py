"""SYNTHETIC DEMO DATA - KHÔNG DÙNG ĐỂ ĐÁNH GIÁ MÔ HÌNH THỰC TẾ.
Chạy:  python scripts/generate_synthetic_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.schemas import DEMO_BANNER  # noqa: E402
from src.data.synthetic_demo import generate_synthetic_dataset  # noqa: E402

out = Path(__file__).resolve().parents[1] / "data" / "synthetic_demo" / "training_dataset_SYNTHETIC.csv"
out.parent.mkdir(parents=True, exist_ok=True)
generate_synthetic_dataset().to_csv(out, index=False, encoding="utf-8")
(out.parent / "README_SYNTHETIC.txt").write_text(DEMO_BANNER + "\n", encoding="utf-8")
print(f"[{DEMO_BANNER}]\nĐã tạo: {out}")
