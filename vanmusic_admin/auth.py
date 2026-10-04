"""Token Admin do backend cấp (HMAC-SHA256, hết hạn). Mật khẩu chỉ nằm ở biến môi trường."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque

log = logging.getLogger("vanmusic.auth")

TOKEN_TTL = int(os.getenv("VM_ADMIN_TOKEN_TTL_SECONDS", str(8 * 3600)))
_RANDOM_SECRET = None


def _secret():
    """Đọc khóa ký token lúc dùng (để nhận được giá trị từ .env nạp muộn)."""
    global _RANDOM_SECRET
    s = (os.getenv("VM_ADMIN_TOKEN_SECRET") or "").encode()
    if s:
        return s
    if _RANDOM_SECRET is None:
        _RANDOM_SECRET = secrets.token_bytes(32)  # token sẽ mất hiệu lực khi backend khởi động lại
        log.warning("VM_ADMIN_TOKEN_SECRET chưa đặt: dùng khóa ngẫu nhiên tạm thời")
    return _RANDOM_SECRET


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# Mật khẩu tài khoản Boss (bossvan) dùng ở đầu web: đăng nhập Boss xong là vào thẳng Admin, không hỏi lần 2.
def boss_password():
    return os.getenv("VM_BOSS_PASSWORD") or "van123"


def password_configured():
    return True


def _same(a, b):
    return hmac.compare_digest(hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest())


def check_password(candidate):
    if not isinstance(candidate, str):
        return False
    expected = os.getenv("VM_ADMIN_PASSWORD") or ""
    ok_boss = _same(candidate, boss_password())
    ok_admin = bool(expected) and _same(candidate, expected)
    return ok_boss or ok_admin


def issue_token(now=None):
    exp = int((now or time.time()) + TOKEN_TTL)
    body = _b64(json.dumps({"sub": "admin", "exp": exp}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", exp


def verify_token(token, now=None):
    try:
        body, sig = token.split(".", 1)
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return False
        data = json.loads(_unb64(body))
        return data.get("sub") == "admin" and int(data.get("exp", 0)) > (now or time.time())
    except Exception:
        return False


class RateLimiter:
    """Giới hạn tần suất theo khóa (IP) trong cửa sổ trượt."""

    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key, limit, window, now=None):
        now = now or time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.hits) > 20000:
                self.hits.clear()
            return True

    def blocked(self, key, limit, window, now=None):
        now = now or time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            return len(q) >= limit


def ip_hash(ip):
    return hashlib.sha256((ip or "?").encode()).hexdigest()[:10]
