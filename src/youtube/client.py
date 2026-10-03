"""Bọc YouTube Data API v3: timeout, retry, xử lý lỗi. Khóa API không bao giờ được log."""
from __future__ import annotations

import json
import socket
import time

from src.logger import get_logger

log = get_logger(__name__)


class YouTubeAPIError(Exception):
    code = "YOUTUBE_API_ERROR"


class MissingAPIKeyError(YouTubeAPIError):
    code = "YOUTUBE_KEY_MISSING"


class YouTubeQuotaError(YouTubeAPIError):
    code = "YOUTUBE_QUOTA_EXCEEDED"


class YouTubeNotFoundError(YouTubeAPIError):
    code = "CHANNEL_NOT_FOUND"


class YouTubeClient:
    def __init__(self, api_key: str, timeout: int = 30, max_retries: int = 3):
        if not api_key:
            raise MissingAPIKeyError("Thiếu YOUTUBE_API_KEY. Hãy điền vào file .env.")
        import httplib2
        from googleapiclient.discovery import build
        self.max_retries = max_retries
        self._service = build("youtube", "v3", developerKey=api_key,
                              http=httplib2.Http(timeout=timeout), cache_discovery=False)

    def execute(self, request, what: str = "request"):
        from googleapiclient.errors import HttpError
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return request.execute()
            except HttpError as e:
                status = getattr(e.resp, "status", 0)
                reason = ""
                try:
                    reason = json.loads(e.content.decode("utf-8"))["error"]["errors"][0]["reason"]
                except Exception:
                    pass
                if status == 403 and reason in {"quotaExceeded", "dailyLimitExceeded"}:
                    raise YouTubeQuotaError("Đã hết quota YouTube API trong ngày.") from e
                if status == 400 and reason in {"keyInvalid", "badRequest"}:
                    raise YouTubeAPIError("YouTube API Key không hợp lệ.") from e
                if status == 403:
                    raise YouTubeAPIError(f"YouTube API từ chối truy cập ({reason or 'forbidden'}).") from e
                if status == 404:
                    raise YouTubeNotFoundError("Không tìm thấy tài nguyên YouTube.") from e
                last_err = e
                if status in (429, 500, 502, 503, 504) or reason == "rateLimitExceeded":
                    log.warning("%s: lỗi tạm thời HTTP %s (lần %d/%d)", what, status, attempt, self.max_retries)
                else:
                    raise YouTubeAPIError(f"Lỗi YouTube API HTTP {status}.") from e
            except (socket.timeout, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                log.warning("%s: lỗi mạng/timeout (lần %d/%d): %s", what, attempt, self.max_retries, type(e).__name__)
            except Exception as e:  # httplib2.HttpLib2Error, ...
                last_err = e
                log.warning("%s: lỗi không mong đợi (lần %d/%d): %s", what, attempt, self.max_retries, type(e).__name__)
            time.sleep(min(2 ** attempt, 10))
        raise YouTubeAPIError("Không gọi được YouTube API sau nhiều lần thử.") from last_err

    def channels_list(self, **kw):
        return self.execute(self._service.channels().list(**kw), "channels.list")

    def playlist_items_list(self, **kw):
        return self.execute(self._service.playlistItems().list(**kw), "playlistItems.list")

    def videos_list(self, **kw):
        return self.execute(self._service.videos().list(**kw), "videos.list")
