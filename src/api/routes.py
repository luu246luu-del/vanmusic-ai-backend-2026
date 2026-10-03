"""Các endpoint /api/v1/*.

Mọi phản hồi thành công hoặc thất bại đều có request_id.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Request,
)
from fastapi.responses import JSONResponse

from src.api.schemas import (
    CollectChannelRequest,
    LatestVideoPredictRequest,
    ManualPredictRequest,
    VanMusicPredictRequest,
)
from src.api.security import (
    ApiException,
    verify_integration_key,
)


router = APIRouter(prefix="/api/v1")


def ok(
    request: Request,
    data,
    status_code: int = 200,
) -> JSONResponse:
    """Tạo phản hồi thành công."""

    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": data,
            "error": None,
            "request_id": (
                request.state.request_id
            ),
        },
    )


def fail(
    request_id: str,
    code: str,
    message: str,
    status_code: int,
    details=None,
) -> JSONResponse:
    """Tạo phản hồi lỗi."""

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "request_id": request_id,
        },
    )


@router.get("/health")
def health(
    request: Request,
):
    """Kiểm tra trạng thái API, mô hình và YouTube API."""

    app_state = request.app.state

    return ok(
        request,
        {
            "api": "ok",
            "model_loaded": (
                app_state.predictor.is_ready
            ),
            "youtube_configured": (
                app_state.service.provider
                is not None
            ),
            "server_time": (
                datetime.now(
                    timezone.utc
                ).isoformat(
                    timespec="seconds"
                )
            ),
        },
    )


@router.get(
    "/model/info",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def model_info(
    request: Request,
):
    """Trả thông tin mô hình đã tải."""

    return ok(
        request,
        request.app.state.predictor.info(),
    )


@router.post(
    "/predict/manual",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def predict_manual(
    body: ManualPredictRequest,
    request: Request,
):
    """Dự báo với dữ liệu nhập thủ công."""

    result = (
        request.app.state.service
        .predict_manual(body)
    )

    return ok(
        request,
        result,
    )


@router.post(
    "/predict/channel",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def predict_channel(
    body: VanMusicPredictRequest,
    request: Request,
):
    """Dự báo với dữ liệu kênh và video được cung cấp."""

    result = (
        request.app.state.service
        .predict_for_channel(body)
    )

    return ok(
        request,
        result,
    )


@router.post(
    "/vanmusic/predict",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def vanmusic_predict(
    body: VanMusicPredictRequest,
    request: Request,
):
    """Endpoint dự báo tiêu chuẩn dành cho VanMusic."""

    result = (
        request.app.state.service
        .predict_for_channel(body)
    )

    return ok(
        request,
        result,
    )


@router.post(
    "/vanmusic/predict-latest",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def vanmusic_predict_latest(
    body: LatestVideoPredictRequest,
    request: Request,
):
    """Tự tìm và dự báo video mới nhất của một kênh."""

    result = (
        request.app.state.service
        .predict_latest_video(
            body.channel_id
        )
    )

    return ok(
        request,
        result,
    )


@router.post(
    "/collect/channel",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def collect_channel(
    body: CollectChannelRequest,
    request: Request,
    background: BackgroundTasks,
):
    """Tạo công việc thu thập dữ liệu kênh chạy nền."""

    service = request.app.state.service

    if service.provider is None:
        raise ApiException(
            "YOUTUBE_KEY_MISSING",
            (
                "Máy chủ chưa cấu hình "
                "YouTube API Key."
            ),
            503,
        )

    job_id = service.jobs.create()

    max_videos = (
        body.max_videos
        or request.app.state.settings
        .max_videos_per_channel
    )

    background.add_task(
        service.run_collect_job,
        job_id,
        body.channel_id,
        max_videos,
    )

    return ok(
        request,
        {
            "job_id": job_id,
            "status": "queued",
        },
        202,
    )


@router.get(
    "/jobs/{job_id}",
    dependencies=[
        Depends(verify_integration_key)
    ],
)
def get_job(
    job_id: str,
    request: Request,
):
    """Lấy trạng thái công việc thu thập."""

    job = (
        request.app.state.service.jobs.get(
            job_id
        )
    )

    if job is None:
        raise ApiException(
            "JOB_NOT_FOUND",
            "Không tìm thấy công việc.",
            404,
        )

    return ok(
        request,
        job,
    )
