#!/usr/bin/env python
"""Kiểm thử tích hợp VanMusic (in tiếng Việt).

    python scripts/test_vanmusic_integration.py                       # chạy bộ test tự động
    python scripts/test_vanmusic_integration.py --live http://127.0.0.1:8000   # thử thêm với API đang chạy
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "integrations" / "vanmusic" / "api-contract.json").read_text(encoding="utf-8"))["request"]["example"]


def run_pytest() -> bool:
    print("=" * 60)
    print("BƯỚC 1: Chạy pytest cho API và bộ tích hợp VanMusic")
    print("=" * 60)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_api.py", "tests/test_vanmusic_integration.py"], cwd=ROOT)
    print("KẾT QUẢ: ĐẠT" if r.returncode == 0 else "KẾT QUẢ: KHÔNG ĐẠT (xem chi tiết phía trên)")
    return r.returncode == 0


def http(method: str, url: str, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def run_live(base: str, key: str) -> bool:
    print("=" * 60)
    print(f"BƯỚC 2: Thử với API đang chạy tại {base}")
    print("=" * 60)
    hdr = {"X-VanMusic-Key": key} if key else {}
    ok = True

    def check(name: str, cond: bool, note: str = ""):
        nonlocal ok
        ok &= cond
        print(f"  [{'ĐẠT' if cond else 'LỖI'}] {name} {note}")

    try:
        st, js = http("GET", f"{base}/api/v1/health")
    except Exception as e:
        print(f"  [LỖI] Không kết nối được API: {type(e).__name__}. Hãy chạy 'python run_api.py' trước.")
        return False
    check("Health trả request_id", bool(js.get("request_id")))
    model_loaded = bool((js.get("data") or {}).get("model_loaded"))
    print(f"  Mô hình đã sẵn sàng: {model_loaded}")

    st, js = http("POST", f"{base}/api/v1/vanmusic/predict", {k: v for k, v in SAMPLE.items() if k != "channel_id"}, hdr)
    check("Thiếu channel_id -> 422 VALIDATION_ERROR", st == 422 and js.get("error", {}).get("code") == "VALIDATION_ERROR")

    st, js = http("POST", f"{base}/api/v1/vanmusic/predict", dict(SAMPLE, duration_seconds=-5), hdr)
    check("duration_seconds âm -> 422", st == 422 and js.get("success") is False)

    st, js = http("POST", f"{base}/api/v1/vanmusic/predict", dict(SAMPLE, publish_datetime="không-phải-ngày"), hdr)
    check("publish_datetime sai -> 422", st == 422)

    st, js = http("POST", f"{base}/api/v1/vanmusic/predict", SAMPLE, hdr)
    check("Response luôn có request_id", bool(js.get("request_id")))
    if js.get("success"):
        d = js["data"]
        print(f"  Dự báo thật: {d['predicted_views_after_1_hour']:,} lượt xem sau 3 ngày (mô hình {d['model']['version']})")
        for w in d.get("warnings", []):
            print("  CẢNH BÁO:", w)
    else:
        e = js.get("error") or {}
        check("Lỗi có mã và thông báo, không có số dự báo giả", js.get("data") is None and bool(e.get("code")), f"({e.get('code')}: {e.get('message')})")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", help="URL API đang chạy, ví dụ http://127.0.0.1:8000")
    ap.add_argument("--key", default="", help="Integration key nếu backend bật REQUIRE_INTEGRATION_KEY")
    a = ap.parse_args()
    good = run_pytest()
    if a.live:
        good = run_live(a.live.rstrip("/"), a.key) and good
    print("\nTỔNG KẾT:", "TẤT CẢ ĐẠT" if good else "CÓ LỖI - hãy đọc các dòng [LỖI] ở trên")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
