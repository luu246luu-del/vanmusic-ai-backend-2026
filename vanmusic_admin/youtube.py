"""Bình luận YouTube qua backend: khóa API chỉ nằm ở biến môi trường YOUTUBE_API_KEY."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("vanmusic.youtube")

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-=.]{1,300}$")
API = "https://www.googleapis.com/youtube/v3/commentThreads"
TIMEOUT = float(os.getenv("VM_YT_TIMEOUT_SECONDS", "8"))
CACHE_TTL = float(os.getenv("VM_YT_CACHE_SECONDS", "120"))
MAX_LIMIT = 30
DEFAULT_LIMIT = 20

_cache: dict = {}
_lock = threading.Lock()


class CommentsError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _map_error(status, body):
    reason = ""
    try:
        reason = ((json.loads(body).get("error") or {}).get("errors") or [{}])[0].get("reason", "")
    except Exception:
        pass
    if reason == "commentsDisabled":
        return CommentsError("COMMENTS_DISABLED", "Bình luận của video này đã bị tắt.", 403)
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        return CommentsError("QUOTA_EXCEEDED", "Đã hết hạn mức YouTube API hôm nay.", 429)
    if reason in ("videoNotFound", "notFound") or status == 404:
        return CommentsError("VIDEO_NOT_FOUND", "Không tìm thấy video.", 404)
    if status in (400,) and reason in ("invalidPageToken", "badRequest"):
        return CommentsError("BAD_REQUEST", "Tham số không hợp lệ.", 400)
    if status in (401, 403):
        return CommentsError("UPSTREAM_DENIED", "YouTube từ chối yêu cầu.", 502)
    return CommentsError("UPSTREAM_ERROR", "YouTube tạm thời không phản hồi.", 502)


def _shape(item):
    top = ((item.get("snippet") or {}).get("topLevelComment") or {})
    sn = top.get("snippet") or {}
    avatar = sn.get("authorProfileImageUrl") or ""
    return {
        "comment_id": str(top.get("id") or item.get("id") or "")[:80],
        "author_name": str(sn.get("authorDisplayName") or "Ẩn danh")[:120],
        "author_avatar": avatar if avatar.startswith("https://") else "",
        "text": str(sn.get("textDisplay") or sn.get("textOriginal") or "")[:2000],
        "published_at": str(sn.get("publishedAt") or ""),
        "like_count": int(sn.get("likeCount") or 0),
        "reply_count": int((item.get("snippet") or {}).get("totalReplyCount") or 0),
    }


def fetch_comments(video_id, page_token=None, max_results=DEFAULT_LIMIT):
    if not VIDEO_RE.match(video_id or ""):
        raise CommentsError("INVALID_VIDEO_ID", "video_id không hợp lệ.", 400)
    if page_token and not TOKEN_RE.match(page_token):
        raise CommentsError("INVALID_PAGE_TOKEN", "page_token không hợp lệ.", 400)
    max_results = max(1, min(int(max_results or DEFAULT_LIMIT), MAX_LIMIT))
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise CommentsError("NOT_CONFIGURED", "Backend chưa cấu hình YOUTUBE_API_KEY.", 503)

    ck = (video_id, page_token or "", max_results)
    now = time.time()
    with _lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]

    params = {"part": "snippet", "videoId": video_id, "maxResults": max_results, "order": "relevance",
              "textFormat": "plainText", "key": key}
    if page_token:
        params["pageToken"] = page_token
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - URL cố định https
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        raise _map_error(e.code, body) from None  # không đưa URL (có key) vào traceback/log
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        is_timeout = isinstance(e, TimeoutError) or "timed out" in str(getattr(e, "reason", e)).lower()
        raise CommentsError("TIMEOUT" if is_timeout else "NETWORK",
                            "YouTube phản hồi quá lâu." if is_timeout else "Không kết nối được tới YouTube.", 504) from None
    except ValueError:
        raise CommentsError("UPSTREAM_ERROR", "Phản hồi YouTube không hợp lệ.", 502) from None

    data = {"items": [_shape(i) for i in (payload.get("items") or [])], "next_page_token": payload.get("nextPageToken")}
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[ck] = (now, data)
    return data
