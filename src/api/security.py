"""Kiểm tra Integration Key (header X-VanMusic-Key). Không log và không trả key."""
from __future__ import annotations

import hmac

from fastapi import Request

INTEGRATION_HEADER = "X-VanMusic-Key"


class ApiException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details=None):
        self.code, self.message, self.status_code, self.details = code, message, status_code, details
        super().__init__(message)


def verify_integration_key(request: Request) -> None:
    s = request.app.state.settings
    if not s.require_integration_key:
        return  # chạy local: không cần key
    if not s.integration_key:
        raise ApiException("INTEGRATION_KEY_NOT_CONFIGURED",
                           "Máy chủ bật REQUIRE_INTEGRATION_KEY nhưng chưa cấu hình VANMUSIC_INTEGRATION_KEY.", 503)
    supplied = request.headers.get(INTEGRATION_HEADER, "")
    if not hmac.compare_digest(supplied.encode("utf-8"), s.integration_key.encode("utf-8")):
        raise ApiException("UNAUTHORIZED", "Thiếu hoặc sai khóa tích hợp.", 401)
