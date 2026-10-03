import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import create_app  # noqa: E402
from src.youtube.client import YouTubeAPIError  # noqa: E402
from tests.conftest import VALID_REQUEST, FakeProvider  # noqa: E402


def make_client(settings, provider=None):
    return TestClient(
        create_app(
            settings,
            provider=provider,
        )
    )


def test_health_without_model(settings):
    response = make_client(settings).get(
        "/api/v1/health"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["data"]["api"] == "ok"
    assert body["data"]["model_loaded"] is False
    assert body["request_id"]


def test_model_info_without_model(settings):
    response = make_client(settings).get(
        "/api/v1/model/info"
    )

    data = response.json()["data"]

    assert data["model_loaded"] is False
    assert data["model_name"] is None


def test_health_and_info_with_model(
    trained_settings,
):
    client = make_client(trained_settings)

    health_response = client.get(
        "/api/v1/health"
    )

    health_data = health_response.json()["data"]

    assert health_data["model_loaded"] is True

    info_response = client.get(
        "/api/v1/model/info"
    )

    info_data = info_response.json()["data"]

    assert info_data["model_loaded"] is True
    assert (
        info_data["model_name"]
        == "LinearRegression"
    )
    assert info_data["feature_count"] == 19
    assert info_data["metrics"]


def test_predict_refuses_when_model_missing(
    settings,
):
    response = make_client(
        settings,
        FakeProvider(),
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    body = response.json()

    assert response.status_code == 503
    assert body["success"] is False
    assert body["data"] is None
    assert (
        body["error"]["code"]
        == "MODEL_NOT_READY"
    )
    assert body["request_id"]


def test_validation_errors_have_request_id(
    trained_settings,
):
    client = make_client(
        trained_settings,
        FakeProvider(),
    )

    invalid_duration = {
        **VALID_REQUEST,
        "duration_seconds": -5,
    }

    response = client.post(
        "/api/v1/vanmusic/predict",
        json=invalid_duration,
    )

    response_body = response.json()

    assert response.status_code == 422
    assert (
        response_body["error"]["code"]
        == "VALIDATION_ERROR"
    )
    assert response_body["request_id"]

    missing_channel = {
        key: value
        for key, value in VALID_REQUEST.items()
        if key != "channel_id"
    }

    missing_channel_response = client.post(
        "/api/v1/vanmusic/predict",
        json=missing_channel,
    )

    assert (
        missing_channel_response.status_code
        == 422
    )

    invalid_datetime_response = client.post(
        "/api/v1/vanmusic/predict",
        json={
            **VALID_REQUEST,
            "publish_datetime": (
                "khong-phai-ngay-hop-le"
            ),
        },
    )

    assert (
        invalid_datetime_response.status_code
        == 422
    )


def test_valid_request_returns_contract_schema(
    trained_settings,
):
    response = make_client(
        trained_settings,
        FakeProvider(),
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["error"] is None
    assert body["request_id"]

    data = body["data"]

    assert set(data) == {
        "predicted_views_after_1_hour",
        "lower_estimate",
        "upper_estimate",
        "estimate_method",
        "channel",
        "video_input",
        "model",
        "warnings",
    }

    assert set(data["channel"]) == {
        "channel_id",
        "channel_title",
        "subscriber_count",
        "channel_age_days",
        "channel_video_count",
        "channel_total_views",
        "avg_previous_views",
        "median_previous_views",
        "previous_video_count_used",
    }

    assert (
        data["channel"][
            "previous_video_count_used"
        ]
        == 10
    )

    assert (
        data["model"]["name"]
        == "LinearRegression"
    )

    assert (
        data["model"]["target"]
        == "views_gained_next_1_hour"
    )

    assert (
        data["predicted_views_after_1_hour"]
        >= 0
    )

    assert (
        data["estimate_method"]
        == "test_residual_quantiles"
    )

    assert any(
        "SYNTHETIC" in warning
        for warning in data["warnings"]
    )


def test_unknown_channel(trained_settings):
    response = make_client(
        trained_settings,
        FakeProvider(exists=False),
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert response.status_code == 404
    assert (
        response.json()["error"]["code"]
        == "CHANNEL_NOT_FOUND"
    )


def test_bad_channel_url(trained_settings):
    response = make_client(
        trained_settings,
        FakeProvider(),
    ).post(
        "/api/v1/vanmusic/predict",
        json={
            **VALID_REQUEST,
            "channel_id": (
                "https://example.com/abc"
            ),
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["error"]["code"]
        == "INVALID_CHANNEL"
    )


def test_youtube_api_failure(trained_settings):
    provider = FakeProvider(
        error=YouTubeAPIError("boom"),
    )

    response = make_client(
        trained_settings,
        provider,
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert response.status_code == 502
    assert (
        response.json()["error"]["code"]
        == "YOUTUBE_API_ERROR"
    )
    assert response.json()["request_id"]


def test_insufficient_history_is_refused(
    trained_settings,
):
    response = make_client(
        trained_settings,
        FakeProvider(n_videos=0),
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert response.status_code == 422
    assert (
        response.json()["error"]["code"]
        == "INSUFFICIENT_HISTORY"
    )


def test_short_history_gives_warning(
    trained_settings,
):
    response = make_client(
        trained_settings,
        FakeProvider(n_videos=4),
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert response.status_code == 200

    data = response.json()["data"]

    assert (
        data["channel"][
            "previous_video_count_used"
        ]
        == 4
    )

    assert any(
        "4/10" in warning
        for warning in data["warnings"]
    )


def test_missing_youtube_key_gives_clear_error(
    trained_settings,
):
    response = make_client(
        trained_settings,
        None,
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert response.status_code == 503
    assert (
        response.json()["error"]["code"]
        == "YOUTUBE_KEY_MISSING"
    )


def test_manual_prediction(trained_settings):
    request_body = {
        "channel_age_days": 900,
        "subscriber_count": 200000,
        "channel_video_count": 150,
        "channel_total_views": 40_000_000,
        "avg_previous_views": 300000,
        "median_previous_views": 250000,
        "previous_video_count_used": 10,
        "title": "Thu nghiem",
        "description": "Ban tin thoi su",
        "duration_seconds": 200,
        "tags": [
            "tin tuc",
            "thoi su",
        ],
        "publish_datetime": (
            "2026-10-02T20:00:00+07:00"
        ),
        "category_id": "25",
        "is_hd": True,
        "has_caption": False,
        "current_view_count": 15000,
        "current_video_age_hours": 4.0,
        "recent_views_per_hour": 2500.0,
    }

    response = make_client(
        trained_settings
    ).post(
        "/api/v1/predict/manual",
        json=request_body,
    )

    assert response.status_code == 200

    predicted_views = response.json()["data"][
        "predicted_views_after_1_hour"
    ]

    assert predicted_views >= 0


def test_integration_key_enforced(
    trained_settings,
):
    trained_settings.require_integration_key = (
        True
    )

    trained_settings.integration_key = (
        "vanmusic-test-secret"
    )

    client = make_client(
        trained_settings,
        FakeProvider(),
    )

    no_key_response = client.post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert no_key_response.status_code == 401

    wrong_key_response = client.post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
        headers={
            "X-VanMusic-Key": "wrong-key",
        },
    )

    assert wrong_key_response.status_code == 401

    correct_key_response = client.post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
        headers={
            "X-VanMusic-Key": (
                "vanmusic-test-secret"
            ),
        },
    )

    assert (
        correct_key_response.status_code
        == 200
    )

    assert (
        "vanmusic-test-secret"
        not in correct_key_response.text
    )

    health_response = client.get(
        "/api/v1/health"
    )

    assert health_response.status_code == 200


def test_integration_key_not_required_locally(
    trained_settings,
):
    response = make_client(
        trained_settings,
        FakeProvider(),
    ).post(
        "/api/v1/vanmusic/predict",
        json=VALID_REQUEST,
    )

    assert response.status_code == 200


def test_cors_allows_configured_origin_only(
    settings,
):
    client = make_client(settings)

    allowed_response = client.options(
        "/api/v1/vanmusic/predict",
        headers={
            "Origin": (
                "https://vanmusic.web.app"
            ),
            "Access-Control-Request-Method": (
                "POST"
            ),
            "Access-Control-Request-Headers": (
                "content-type,x-vanmusic-key"
            ),
        },
    )

    assert (
        allowed_response.headers.get(
            "access-control-allow-origin"
        )
        == "https://vanmusic.web.app"
    )

    blocked_response = client.options(
        "/api/v1/vanmusic/predict",
        headers={
            "Origin": (
                "https://evil.example"
            ),
            "Access-Control-Request-Method": (
                "POST"
            ),
        },
    )

    assert (
        "access-control-allow-origin"
        not in blocked_response.headers
    )


def test_collect_requires_youtube_key_and_jobs(
    settings,
):
    client_without_provider = make_client(
        settings,
        None,
    )

    channel_id = "UC" + ("a" * 22)

    missing_key_response = (
        client_without_provider.post(
            "/api/v1/collect/channel",
            json={
                "channel_id": channel_id,
            },
        )
    )

    assert (
        missing_key_response.json()[
            "error"
        ]["code"]
        == "YOUTUBE_KEY_MISSING"
    )

    client_with_provider = make_client(
        settings,
        FakeProvider(),
    )

    collect_response = (
        client_with_provider.post(
            "/api/v1/collect/channel",
            json={
                "channel_id": channel_id,
            },
        )
    )

    assert collect_response.status_code == 202

    job_id = collect_response.json()["data"][
        "job_id"
    ]

    job_response = client_with_provider.get(
        f"/api/v1/jobs/{job_id}"
    )

    job = job_response.json()["data"]

    assert job["status"] in {
        "queued",
        "running",
        "succeeded",
    }

    unknown_job_response = (
        client_with_provider.get(
            "/api/v1/jobs/khong-ton-tai"
        )
    )

    assert unknown_job_response.status_code == 404


def test_unknown_route_still_has_request_id(
    settings,
):
    response = make_client(settings).get(
        "/api/v1/khong-co"
    )

    assert response.status_code == 404
    assert response.json()["request_id"]