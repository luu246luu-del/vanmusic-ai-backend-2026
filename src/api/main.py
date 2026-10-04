"""FastAPI app factory. Chạy:  python run_api.py"""
from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.routes import fail, router
from src.api.security import INTEGRATION_HEADER, ApiException
from src.api.services import PredictionService, YouTubeProvider
from src.config import Settings, load_settings
from src.logger import get_logger, setup_logging
from src.ml.predictor import ViewPredictor
from src.youtube.client import YouTubeClient

log = get_logger(__name__)

# Module Admin / Thống kê / Bình luận YouTube của VanMusic (cùng một backend, prefix /api/v1/vanmusic/*)
try:
    from vanmusic_admin import register_model_info_provider
    from vanmusic_admin import router as vanmusic_admin_router
except Exception as _e:  # không để lỗi module Admin làm sập API dự báo
    vanmusic_admin_router = None
    register_model_info_provider = None
    log.error("Không nạp được module vanmusic_admin: %s", type(_e).__name__)


def _model_info_for_admin(predictor: ViewPredictor):
    """Chuyển thông tin mô hình AI thành dạng trang Admin cần (không cần VM_MODEL_INFO_URL)."""
    def provider():
        info = predictor.info()
        if not info.get("model_loaded"):
            return {"_error": True}
        m = info.get("metrics") or {}
        dp = info.get("data_period") or {}
        n = None
        if dp.get("n_train") is not None and dp.get("n_test") is not None:
            n = int(dp["n_train"]) + int(dp["n_test"])
        bc = (predictor.metadata or {}).get("baseline_comparison") or {}
        return {"version": info.get("model_version") or info.get("model_name"), "trained_at": info.get("trained_at"),
                "samples": n, "mae": m.get("mae"), "rmse": m.get("rmse"), "r2": m.get("r2"),
                "beats_baseline": bc.get("beats_best_baseline_mae_and_rmse")}
    return provider


def create_app(settings: Settings | None = None, provider=None, predictor: ViewPredictor | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings.log_dir)

    if provider is None and settings.youtube_api_key:
        try:
            provider = YouTubeProvider(YouTubeClient(settings.youtube_api_key, settings.request_timeout_seconds,
                                                     settings.max_retries), settings)
        except Exception as e:  # không làm sập API nếu khóa lỗi
            log.error("Không khởi tạo được YouTube client: %s", type(e).__name__)
    if predictor is None:
        predictor = ViewPredictor(settings.model_file, settings.reports_dir)
        if not predictor.load():
            log.warning("Chưa tải được mô hình: %s (API vẫn chạy, /predict trả MODEL_NOT_READY)", predictor.load_error)

    app = FastAPI(title="YouTube View Predictor API", version="1.0.0")
    app.state.settings = settings
    app.state.predictor = predictor
    app.state.service = PredictionService(settings, predictor, provider)

    # CORS: chỉ cho phép các origin trong VANMUSIC_ALLOWED_ORIGINS (+ ALLOWED_ORIGINS cũ của module Admin), KHÔNG dùng "*"
    origins = list(settings.cors_origins)
    origins += [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    origins = [o for i, o in enumerate(origins) if o != "*" and o not in origins[:i]]
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type", INTEGRATION_HEADER, "X-Request-ID", "Authorization"],
                       expose_headers=["X-Request-ID"], max_age=600)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception:  # lỗi ngoài dự kiến
            log.exception("Lỗi nội bộ")
            response = fail(request.state.request_id, "INTERNAL_ERROR", "Lỗi nội bộ máy chủ.", 500)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    def _rid(request: Request) -> str:
        return getattr(request.state, "request_id", uuid.uuid4().hex)

    @app.exception_handler(ApiException)
    async def _api_exc(request: Request, exc: ApiException):
        return fail(_rid(request), exc.code, exc.message, exc.status_code, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return fail(_rid(request), "VALIDATION_ERROR", "Dữ liệu gửi lên không hợp lệ.", 422, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return fail(_rid(request), code, "Không tìm thấy đường dẫn." if exc.status_code == 404 else str(exc.detail), exc.status_code)

    app.include_router(router)
    if vanmusic_admin_router is not None:
        register_model_info_provider(_model_info_for_admin(predictor))
        app.include_router(vanmusic_admin_router)
    return app
