"""Các endpoint FastAPI của VanMusic Admin/Analytics/Bình luận YouTube.

Gắn vào ứng dụng hiện có:
    from vanmusic_admin import router as vanmusic_admin_router
    app.include_router(vanmusic_admin_router)
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from . import auth, youtube
from .analytics import Collector, now_local
from .store import build_store

log = logging.getLogger("vanmusic.router")
router = APIRouter(prefix="/api/v1/vanmusic", tags=["vanmusic-admin"])

VERSION = "1.0.0"
_collector: Collector | None = None
_limiter = auth.RateLimiter()
_model_info_provider = None
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_collector():
    global _collector
    if _collector is None:
        _collector = Collector(build_store())
    _collector.ensure_started()
    return _collector


def set_collector(c):  # dùng cho kiểm thử
    global _collector
    _collector = c


def register_model_info_provider(fn):
    """Cho phép backend AI hiện có cung cấp thông tin mô hình: fn() -> dict."""
    global _model_info_provider
    _model_info_provider = fn


# ---------------------------------------------------------------- tiện ích
def _rid():
    return uuid.uuid4().hex[:16]


def _ok(data, rid, status=200, admin=False):
    r = JSONResponse({"success": True, "data": data, "error": None, "request_id": rid}, status_code=status)
    if admin:
        r.headers["Cache-Control"] = "no-store"
    return r


def _fail(code, message, status, rid, headers=None):
    r = JSONResponse({"success": False, "data": None, "error": {"code": code, "message": message}, "request_id": rid},
                     status_code=status)
    r.headers["Cache-Control"] = "no-store"
    for k, v in (headers or {}).items():
        r.headers[k] = v
    return r


def _client_ip(request: Request):
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return request.client.host if request.client else "?"


def _guard(request: Request, rid):
    """Chỉ chấp nhận token Admin do backend cấp. Trả về None nếu hợp lệ."""
    h = request.headers.get("authorization", "")
    if h.startswith("Bearer ") and auth.verify_token(h[7:].strip()):
        return None
    return _fail("UNAUTHORIZED", "Không có quyền truy cập khu vực quản trị.", 401, rid)


# --------------------------------------------------------------- thu thập sự kiện
@router.post("/analytics/collect")
async def collect(request: Request):
    rid = _rid()
    ip = _client_ip(request)
    if not _limiter.allow("collect:" + ip, 600, 60):
        return _fail("RATE_LIMITED", "Quá nhiều yêu cầu.", 429, rid)
    raw = await request.body()
    if len(raw) > 16384:
        return _fail("PAYLOAD_TOO_LARGE", "Dữ liệu quá lớn.", 413, rid)
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        return _fail("BAD_REQUEST", "JSON không hợp lệ.", 400, rid)
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or len(events) > 25:
        return _fail("BAD_REQUEST", "Thiếu danh sách events (tối đa 25).", 400, rid)
    c = get_collector()
    accepted = sum(1 for ev in events if c.handle(ev))
    return _ok({"accepted": accepted}, rid)


# --------------------------------------------------------------- đăng nhập Admin
@router.post("/admin/login")
async def admin_login(request: Request):
    rid = _rid()
    ip = _client_ip(request)
    c = get_collector()
    key = "login:" + ip
    if _limiter.blocked(key, 5, 600):
        c.log_admin("login", False, auth.ip_hash(ip), "bị giới hạn tần suất")
        return _fail("RATE_LIMITED", "Thử sai quá nhiều lần. Vui lòng đợi vài phút.", 429, rid, {"Retry-After": "600"})
    if not auth.password_configured():
        return _fail("NOT_CONFIGURED", "Backend chưa cấu hình VM_ADMIN_PASSWORD.", 503, rid)
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        body = {}
    if not auth.check_password(body.get("password") if isinstance(body, dict) else None):
        _limiter.allow(key, 5, 600)  # chỉ đếm lần sai
        c.log_admin("login", False, auth.ip_hash(ip), "sai mật khẩu")
        return _fail("INVALID_CREDENTIALS", "Mật khẩu quản trị không đúng.", 401, rid)
    token, exp = auth.issue_token()
    c.log_admin("login", True, auth.ip_hash(ip))
    return _ok({"token": token, "expires_at": exp * 1000}, rid, admin=True)


@router.get("/admin/session")
def admin_session(request: Request):
    rid = _rid()
    bad = _guard(request, rid)
    return bad or _ok({"valid": True}, rid, admin=True)


# --------------------------------------------------------------- dữ liệu Admin
def _admin(request, fn):
    rid = _rid()
    bad = _guard(request, rid)
    if bad:
        return bad
    try:
        return _ok(fn(get_collector()), rid, admin=True)
    except ValueError:
        return _fail("BAD_REQUEST", "Tham số không hợp lệ.", 400, rid)
    except Exception as exc:
        log.warning("Lỗi truy vấn admin (%s)", type(exc).__name__)
        return _fail("INTERNAL", "Không đọc được dữ liệu thống kê.", 500, rid)


@router.get("/admin/overview")
def admin_overview(request: Request):
    def run(c):
        data = c.overview()
        data["backend_ok"] = True
        data["store"] = c.store.kind
        return data
    return _admin(request, run)


@router.get("/admin/online")
def admin_online(request: Request, filter: str = Query("all", pattern="^(all|guest|user)$")):
    return _admin(request, lambda c: c.online(filter))


@router.get("/admin/growth")
def admin_growth(request: Request,
                 metric: str = Query("sessions", pattern="^(new|returning|sessions|pageviews|plays|searches|ai)$"),
                 range: str = Query("7d", pattern="^(7d|30d|3m|6m|12m|custom)$"),
                 start: str | None = None, end: str | None = None):
    def run(c):
        today = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        if range == "custom":
            if not (start and end and DATE_RE.match(start) and DATE_RE.match(end)):
                raise ValueError
            s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=today.tzinfo)
            e = min(datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=today.tzinfo), today)
        else:
            days = {"7d": 7, "30d": 30, "3m": 90, "6m": 180, "12m": 365}[range]
            e, s = today, today - timedelta(days=days - 1)
        if s > e:
            raise ValueError
        return c.growth(metric, s, e)
    return _admin(request, run)


@router.get("/admin/top-content")
def admin_top_content(request: Request, period: str = Query("day", pattern="^(day|week|month|all)$")):
    return _admin(request, lambda c: c.top_content(period))


@router.get("/admin/keywords")
def admin_keywords(request: Request, period: str = Query("day", pattern="^(day|week|month|all)$")):
    return _admin(request, lambda c: c.keywords(period))


def _fetch_model_info():
    if _model_info_provider:
        try:
            return _model_info_provider()
        except Exception as exc:
            log.warning("model_info_provider lỗi (%s)", type(exc).__name__)
            return None
    url = os.getenv("VM_MODEL_INFO_URL", "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    try:
        with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - URL do quản trị viên cấu hình
            raw = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"_error": True}
    src = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
    if not isinstance(src, dict):
        return {"_error": True}
    metrics = src.get("metrics") if isinstance(src.get("metrics"), dict) else {}

    def pick(*keys):
        for k in keys:
            for d in (src, metrics):
                if d.get(k) is not None:
                    return d[k]
        return None
    return {"version": pick("model_version", "version", "model_name"),
            "trained_at": pick("trained_at", "training_date", "trained_on"),
            "samples": pick("n_samples", "samples", "training_samples", "train_samples"),
            "mae": pick("mae", "MAE"), "rmse": pick("rmse", "RMSE"), "r2": pick("r2", "R2", "r_squared"),
            "beats_baseline": pick("beats_baseline", "better_than_baseline", "outperforms_baseline")}


@router.get("/admin/ai")
def admin_ai(request: Request):
    def run(c):
        data = c.ai_stats()
        info = _fetch_model_info()
        data["model"] = None if (info is None or info.get("_error")) else info
        data["model_status"] = "not_configured" if info is None else ("error" if info.get("_error") else "ok")
        data["backend_ok"] = True
        return data
    return _admin(request, run)


@router.get("/admin/users")
def admin_users(request: Request):
    return _admin(request, lambda c: {"items": c.users(100)})


@router.get("/admin/system")
def admin_system(request: Request):
    def run(c):
        s = c.system()
        s.update(version=VERSION, youtube_key_configured=bool(os.getenv("YOUTUBE_API_KEY")),
                 admin_password_configured=auth.password_configured(),
                 token_secret_configured=bool(os.getenv("VM_ADMIN_TOKEN_SECRET")),
                 model_info_configured=bool(_model_info_provider or os.getenv("VM_MODEL_INFO_URL")))
        return s
    return _admin(request, run)


@router.get("/admin/logs")
def admin_logs(request: Request):
    return _admin(request, lambda c: {"items": [
        {"ts": r.get("ts"), "action": r.get("action"), "ok": r.get("ok"), "ip": r.get("ip"), "detail": r.get("detail")}
        for r in c.admin_logs(100)]})


# --------------------------------------------------------------- bình luận YouTube
@router.get("/youtube/comments")
def youtube_comments(request: Request, video_id: str = Query(..., max_length=32),
                     page_token: str | None = Query(None, max_length=300),
                     max_results: int = Query(youtube.DEFAULT_LIMIT, ge=1, le=100)):
    rid = _rid()
    if not _limiter.allow("yt:" + _client_ip(request), 60, 60):
        return _fail("RATE_LIMITED", "Quá nhiều yêu cầu bình luận.", 429, rid)
    try:
        data = youtube.fetch_comments(video_id, page_token, max_results)
    except youtube.CommentsError as e:
        return _fail(e.code, e.message, e.status, rid)
    except Exception as exc:
        log.warning("Lỗi bình luận YouTube (%s)", type(exc).__name__)
        return _fail("INTERNAL", "Không tải được bình luận.", 500, rid)
    r = _ok(data, rid)
    r.headers["Cache-Control"] = "public, max-age=60"
    return r
