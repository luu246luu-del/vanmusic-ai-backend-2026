"""FastAPI app factory. Chạy:  python run_api.py"""
from __future__ import annotations

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

    # CORS: chỉ cho phép các origin trong VANMUSIC_ALLOWED_ORIGINS (KHÔNG dùng "*")
    app.add_middleware(CORSMiddleware, allow_origins=[o for o in settings.cors_origins if o != "*"],
                       allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type", INTEGRATION_HEADER, "X-Request-ID"],
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
    return app
