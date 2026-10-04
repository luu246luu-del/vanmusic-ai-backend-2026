"""Kiểm tra backend đã gộp: API dự báo + module Admin chạy chung một app."""
import os
import sys
from pathlib import Path

os.environ.update(VM_STORE="memory", VM_ADMIN_TOKEN_SECRET="s3cret")
os.environ.pop("VM_ADMIN_PASSWORD", None)
os.environ.pop("VM_BOSS_PASSWORD", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import create_app  # noqa: E402

P = "/api/v1/vanmusic"


@pytest.fixture()
def client(settings):
    from vanmusic_admin import router as rmod  # noqa: F401
    sys.modules["vanmusic_admin.router"]._limiter.hits.clear()
    return TestClient(create_app(settings))


def test_predictor_health_still_works(client):
    assert client.get("/api/v1/health").status_code == 200


def test_boss_password_logs_in_without_second_layer(client):
    r = client.post(P + "/admin/login", json={"password": "van123"})
    assert r.status_code == 200 and r.json()["data"]["token"]
    h = {"Authorization": "Bearer " + r.json()["data"]["token"]}
    assert client.get(P + "/admin/overview", headers=h).status_code == 200
    assert client.get(P + "/admin/ai", headers=h).status_code == 200


def test_admin_requires_token_and_wrong_password_rejected(client):
    assert client.get(P + "/admin/overview").status_code == 401
    assert client.post(P + "/admin/login", json={"password": "sai"}).status_code == 401


def test_cors_allows_authorization_header(client):
    r = client.options(P + "/admin/overview", headers={
        "Origin": "https://vanmusic.web.app", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert r.status_code == 200
    assert "authorization" in r.headers.get("access-control-allow-headers", "").lower()
