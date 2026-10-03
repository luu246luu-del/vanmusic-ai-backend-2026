"""Giao diện Streamlit độc lập để kiểm thử API/mô hình trước khi ghép vào VanMusic.
Chạy:  streamlit run streamlit_app/app.py   (cần API đang chạy: python run_api.py)"""
import os
from datetime import datetime, time, timedelta

import requests
import streamlit as st

DISCLAIMER = "Kết quả được tạo bởi mô hình Hồi quy tuyến tính dựa trên dữ liệu lịch sử và chỉ mang tính tham khảo."
CATEGORIES = {"10": "Âm nhạc", "24": "Giải trí", "22": "Con người & Blog", "1": "Phim & Hoạt hình"}

st.set_page_config(page_title="AI Dự Báo View YouTube", page_icon="📈", layout="wide")
st.title("📈 YouTube View Predictor")
st.caption("Dự báo lượt xem sau 3 ngày (72 giờ) bằng Hồi quy tuyến tính")

with st.sidebar:
    api_url = st.text_input("API URL", os.getenv("PREDICTOR_API_URL", "http://127.0.0.1:8000")).rstrip("/")
    key = st.text_input("Integration key (nếu bật)", type="password")


def call(method: str, path: str, **kw):
    headers = {"X-VanMusic-Key": key} if key else {}
    try:
        r = requests.request(method, f"{api_url}/api/v1{path}", headers=headers, timeout=45, **kw)
        return r.json()
    except requests.RequestException:
        return {"success": False, "error": {"code": "NETWORK_ERROR", "message": "Không kết nối được API. Hãy chạy: python run_api.py"}}
    except ValueError:
        return {"success": False, "error": {"code": "BAD_RESPONSE", "message": "API trả về dữ liệu không phải JSON."}}


health = call("GET", "/health")
info = call("GET", "/model/info")
model_ready = bool(health.get("success") and health["data"].get("model_loaded"))
with st.sidebar:
    st.write("API:", "🟢 hoạt động" if health.get("success") else "🔴 không kết nối")
    st.write("Model:", "🟢 sẵn sàng" if model_ready else "🟠 chưa sẵn sàng")
    if model_ready and info.get("success"):
        d = info["data"]
        st.write(f"Phiên bản: `{d['model_version']}`")
        if d.get("is_synthetic"):
            st.error("SYNTHETIC DEMO DATA - KHÔNG DÙNG ĐỂ ĐÁNH GIÁ MÔ HÌNH THỰC TẾ")
        st.json({"metrics": d["metrics"], "baseline_metrics": d["baseline_metrics"]}, expanded=False)


def video_inputs(prefix: str) -> dict:
    title = st.text_input("Tiêu đề video", key=prefix + "t")
    desc = st.text_area("Mô tả", key=prefix + "d")
    c1, c2, c3 = st.columns(3)
    minutes = c1.number_input("Phút", 0, 600, 4, key=prefix + "m")
    seconds = c2.number_input("Giây", 0, 59, 0, key=prefix + "s")
    cat = c3.selectbox("Danh mục", list(CATEGORIES), format_func=lambda k: f"{k} - {CATEGORIES[k]}", key=prefix + "c")
    tags = st.text_input("Tags (ngăn cách bằng dấu phẩy)", key=prefix + "g")
    d1, d2 = st.columns(2)
    day = d1.date_input("Ngày đăng", datetime.now() + timedelta(days=1), key=prefix + "dd")
    tm = d2.time_input("Giờ đăng", time(20, 0), key=prefix + "tt")
    e1, e2 = st.columns(2)
    hd, cap = e1.checkbox("Video HD", True, key=prefix + "h"), e2.checkbox("Có phụ đề", False, key=prefix + "p")
    return {"title": title, "description": desc, "duration_seconds": int(minutes * 60 + seconds),
            "tags": [t.strip() for t in tags.split(",") if t.strip()], "category_id": cat, "is_hd": hd, "has_caption": cap,
            "publish_datetime": datetime.combine(day, tm).astimezone().isoformat()}


def show_result(resp: dict):
    if not resp.get("success"):
        e = resp.get("error") or {}
        if e.get("code") == "MODEL_NOT_READY":
            st.warning("Hệ thống dự báo đang được chuẩn bị. Vui lòng thử lại sau.")
        else:
            st.error(f"{e.get('message', 'Lỗi không xác định')} (mã: {e.get('code')}, request_id: {resp.get('request_id')})")
        return
    d = resp["data"]
    st.metric("Lượt xem dự kiến sau 3 ngày", f"{d['predicted_views_after_1_hour']:,}".replace(",", "."))
    if d.get("lower_estimate") is not None:
        st.write(f"Khoảng tham khảo: **{d['lower_estimate']:,}** – **{d['upper_estimate']:,}** ({d['estimate_method']})".replace(",", "."))
    ch = d["channel"]
    st.subheader("Thông tin kênh")
    st.json(ch, expanded=True)
    for w in d["warnings"]:
        st.warning(w)
    st.caption(f"Model: {d['model']['name']} {d['model']['version']} • request_id: {resp['request_id']}")
    st.info(DISCLAIMER)


tab_manual, tab_channel = st.tabs(["Nhập thủ công", "Nhập Channel ID"])

with tab_manual:
    st.subheader("Thống kê kênh")
    a, b, c = st.columns(3)
    age = a.number_input("Tuổi kênh (ngày)", 0, 20000, 1000)
    subs = b.number_input("Người đăng ký", 0, 500_000_000, 100_000)
    vcount = c.number_input("Số video của kênh", 0, 100_000, 200)
    d_, e_, f_ = st.columns(3)
    tviews = d_.number_input("Tổng lượt xem kênh", 0, 100_000_000_000, 50_000_000)
    avgv = e_.number_input("Lượt xem TB các video trước", 0, 1_000_000_000, 500_000)
    medv = f_.number_input("Lượt xem trung vị các video trước", 0, 1_000_000_000, 400_000)
    st.subheader("Video dự kiến")
    vi = video_inputs("man")
    if st.button("DỰ BÁO SAU 3 NGÀY", key="btn_manual", disabled=not model_ready):
        if not vi["title"].strip() or vi["duration_seconds"] <= 0:
            st.error("Vui lòng nhập tiêu đề và thời lượng > 0.")
        else:
            with st.spinner("Đang dự báo..."):
                show_result(call("POST", "/predict/manual", json={
                    **vi, "channel_age_days": age, "subscriber_count": subs, "channel_video_count": vcount,
                    "channel_total_views": tviews, "avg_previous_views": avgv, "median_previous_views": medv}))
    if not model_ready:
        st.warning("Hệ thống dự báo đang được chuẩn bị (mô hình chưa sẵn sàng). Không hiển thị kết quả giả.")

with tab_channel:
    ch_in = st.text_input("Channel ID (UC...), URL kênh hoặc @handle", key="chin")
    vi2 = video_inputs("chn")
    if st.button("DỰ BÁO SAU 3 NGÀY", key="btn_channel", disabled=not model_ready):
        if not ch_in.strip() or not vi2["title"].strip() or vi2["duration_seconds"] <= 0:
            st.error("Vui lòng nhập kênh, tiêu đề và thời lượng > 0.")
        else:
            with st.spinner("Đang phân tích dữ liệu kênh..."):
                show_result(call("POST", "/predict/channel", json={"channel_id": ch_in.strip(), **vi2}))
    if not model_ready:
        st.warning("Hệ thống dự báo đang được chuẩn bị (mô hình chưa sẵn sàng). Không hiển thị kết quả giả.")

st.divider()
st.caption(DISCLAIMER)
