"""Thu thập & truy vấn thống kê VanMusic (bộ đếm tổng hợp, không ghi theo giây).

Mô hình dữ liệu (chỉ backend đọc/ghi, Security Rules chặn toàn bộ client):
  analytics_periods/{pid}                 bộ đếm theo kỳ  (pid: d-YYYY-MM-DD | w-YYYY-Www | m-YYYY-MM | all)
  analytics_content/{pid}/items/{cid}     lượt phát theo nội dung
  analytics_search/{pid}/items/{key}      lượt tìm theo từ khóa đã chuẩn hóa
  analytics_aichan/{pid}/items/{channel}  lượt AI Tiên Đoán theo kênh
  analytics_visitors/{key}                trạng thái người truy cập (chống đếm trùng)
  analytics_accounts/{key}                tài khoản đã thấy (không chứa mật khẩu/token)
  analytics_meta/aiRecent                 20 video AI phân tích gần nhất
  adminLogs/{id}                          nhật ký quản trị
Ghi được gom trong bộ nhớ và đẩy lên mỗi FLUSH_SECONDS giây (cộng dồn nguyên tử).
"""
from __future__ import annotations

import atexit
import hashlib
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

log = logging.getLogger("vanmusic.analytics")

TZ = timezone(timedelta(hours=float(os.getenv("VM_TZ_OFFSET_HOURS", "7"))))
FLUSH_SECONDS = float(os.getenv("VM_FLUSH_SECONDS", "15"))
ONLINE_TTL = float(os.getenv("VM_ONLINE_TTL_SECONDS", "120"))
GUEST_CONFIRM_SECONDS = 20
ADMIN_USERNAMES = {u.strip().lower() for u in os.getenv("VM_ADMIN_USERNAMES", "bossvan").split(",") if u.strip()}

ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
CID_RE = re.compile(r"^[A-Za-z0-9_:.\-]{1,120}$")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
LONG_DIGITS_RE = re.compile(r"\d{9,}")

COUNTERS = ("sessions", "pageViews", "plays", "searches", "searchHits", "searchMiss",
            "aiUses", "aiOk", "aiFail", "aiMs", "newVisitors", "returningVisitors", "uniqueVisitors", "accounts")


# ----------------------------------------------------------------- tiện ích
def clean_text(v, n):
    if not isinstance(v, str):
        return ""
    return CTRL_RE.sub("", v).strip()[:n]


def clean_id(v):
    return v if isinstance(v, str) and ID_RE.match(v) else ""


def https_url(v, n=300):
    v = clean_text(v, n)
    return v if v.startswith("https://") else ""


def normalize_keyword(raw):
    """Chuẩn hóa từ khóa; trả về '' nếu rỗng hoặc có dấu hiệu dữ liệu nhạy cảm."""
    if not isinstance(raw, str):
        return ""
    q = unicodedata.normalize("NFC", CTRL_RE.sub(" ", raw))
    q = re.sub(r"\s+", " ", q).strip().lower()[:80]
    if len(q) < 2 or EMAIL_RE.search(q) or LONG_DIGITS_RE.search(q.replace(" ", "")):
        return ""
    return q


def now_local(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(), TZ)


def period_ids(dt):
    iso = dt.isocalendar()
    return {
        "day": f"d-{dt:%Y-%m-%d}",
        "week": f"w-{iso[0]}-W{iso[1]:02d}",
        "month": f"m-{dt:%Y-%m}",
        "all": "all",
    }


def prev_period_id(scope, dt):
    if scope == "day":
        return period_ids(dt - timedelta(days=1))["day"]
    if scope == "week":
        return period_ids(dt - timedelta(days=7))["week"]
    if scope == "month":
        first = dt.replace(day=1)
        return period_ids(first - timedelta(days=1))["month"]
    return None


def key_for(prefix, value):
    return prefix + hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


# ------------------------------------------------------------------ collector
class Collector:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.pending: dict[str, dict] = {}
        self.presence: dict[str, dict] = {}
        self.vcache: dict[str, dict | None] = {}
        self.admin_vids: set[str] = set()
        self.recent: dict[tuple, float] = {}
        self.search_seen: set[tuple] = set()
        self.ai_recent: deque = deque(maxlen=20)
        self._ai_recent_loaded = False
        self._ai_dirty = False
        self.started_at = time.time()
        self.flush_ok = 0
        self.flush_err = 0
        self.last_flush = None
        self.last_error = None
        self._thread = None
        self._stop = threading.Event()

    # ---------- vòng đời
    def ensure_started(self):
        if self._thread and self._thread.is_alive():
            return
        with self.lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="vm-analytics-flush", daemon=True)
            self._thread.start()
            atexit.register(self.flush)

    def _loop(self):
        while not self._stop.wait(FLUSH_SECONDS):
            self.flush()
            self._gc()

    def stop(self):
        self._stop.set()
        self.flush()

    # ---------- hàng đợi ghi
    def _inc(self, path, **kv):
        d = self.pending.setdefault(path, {"inc": {}, "set": {}})
        for k, v in kv.items():
            d["inc"][k] = d["inc"].get(k, 0) + v

    def _set(self, path, **kv):
        d = self.pending.setdefault(path, {"inc": {}, "set": {}})
        d["set"].update(kv)

    def flush(self):
        with self.lock:
            pending, self.pending = self.pending, {}
            ai_snapshot = list(self.ai_recent) if self._ai_dirty else None
            self._ai_dirty = False
        if ai_snapshot is not None:
            pending.setdefault("analytics_meta/aiRecent", {"inc": {}, "set": {}})["set"]["items"] = ai_snapshot
        if not pending:
            return True
        ops = [(p, v["inc"], v["set"]) for p, v in pending.items()]
        try:
            self.store.apply(ops)
            self.flush_ok += 1
            self.last_flush = time.time()
            return True
        except Exception as exc:
            self.flush_err += 1
            self.last_error = type(exc).__name__
            log.warning("Đẩy thống kê thất bại (%s), sẽ thử lại", type(exc).__name__)
            with self.lock:  # trả lại hàng đợi để thử lại
                for p, v in pending.items():
                    d = self.pending.setdefault(p, {"inc": {}, "set": {}})
                    for k, n in v["inc"].items():
                        d["inc"][k] = d["inc"].get(k, 0) + n
                    for k, val in v["set"].items():
                        d["set"].setdefault(k, val)
            return False

    def _gc(self):
        now = time.time()
        with self.lock:
            for sid in [s for s, p in self.presence.items() if now - p["lastSeen"] > ONLINE_TTL * 3]:
                del self.presence[sid]
            for k in [k for k, t in self.recent.items() if now - t > 120]:
                del self.recent[k]
            today = period_ids(now_local())["day"]
            if len(self.search_seen) > 50000 or any(k[0] != today and k[0].startswith("d-") for k in list(self.search_seen)[:50]):
                self.search_seen = {k for k in self.search_seen if k[0] in (today, "all") or not k[0].startswith("d-")}
            if len(self.vcache) > 20000:
                self.vcache.clear()

    # ---------- chống ghi trùng
    def _dedupe(self, key, window, now):
        last = self.recent.get(key)
        if last is not None and now - last < window:
            return True
        self.recent[key] = now
        return False

    # ---------- bộ đếm theo kỳ
    def _count(self, pids, **kv):
        for pid in pids.values():
            self._inc(f"analytics_periods/{pid}", **kv)

    # ---------- người truy cập duy nhất
    def _vstate(self, key):
        if key in self.vcache:
            return self.vcache[key]
        st = self.store.get(f"analytics_visitors/{key}")
        self.vcache[key] = st
        return st

    def _visit(self, uid, vid, now, device, count_session=True):
        """Ghi nhận một người truy cập (đăng nhập theo userId, khách theo visitorId)."""
        dt = now_local(now)
        pids = period_ids(dt)
        is_user = bool(uid)
        key = key_for("u", uid.lower()) if is_user else key_for("v", vid)
        st = self._vstate(key)
        inherited = False
        if st is None and is_user:  # khách đã đếm trước đó rồi mới đăng nhập -> không đếm lại
            g = self._vstate(key_for("v", vid))
            if g:
                st = {"firstSeen": g.get("firstSeen"), "lastDay": g.get("lastDay"), "lastWeek": g.get("lastWeek"),
                      "lastMonth": g.get("lastMonth"), "inherited": True}
                inherited = True
        new = st is None
        st = dict(st or {})
        fs = st.get("firstSeen") or int(now * 1000)
        st["firstSeen"] = fs

        if new:
            self._inc(f"analytics_periods/{pids['all']}", uniqueVisitors=1)
        for scope, field in (("day", "lastDay"), ("week", "lastWeek"), ("month", "lastMonth")):
            if st.get(field) != pids[scope]:
                self._inc(f"analytics_periods/{pids[scope]}", uniqueVisitors=1)
                if scope == "day":
                    self._inc(f"analytics_periods/{pids['day']}", **({"newVisitors": 1} if new else {"returningVisitors": 1}))
                st[field] = pids[scope]
        if count_session:
            self._count(pids, sessions=1)
        st["lastSeen"] = int(now * 1000)
        self.vcache[key] = st
        self._set(f"analytics_visitors/{key}", firstSeen=st["firstSeen"], lastSeen=st["lastSeen"], lastDay=st["lastDay"],
                  lastWeek=st["lastWeek"], lastMonth=st["lastMonth"], kind="user" if is_user else "guest")
        if count_session:
            self._inc(f"analytics_visitors/{key}", sessions=1)

        if is_user:
            acc = f"analytics_accounts/{key}"
            if new or (inherited and not st.get("accountMade")):
                self._inc(f"analytics_periods/{pids['all']}", accounts=1)
                self._set(acc, name=clean_text(uid, 40), firstSeen=fs)
                st["accountMade"] = True
            self._set(acc, lastSeen=int(now * 1000), device=device)
            if count_session:
                self._inc(acc, sessions=1)
        return key

    # ---------- xử lý sự kiện
    def handle(self, ev, now=None):
        """Xử lý 1 sự kiện đã parse JSON. Trả về True nếu được ghi nhận."""
        now = now if now is not None else time.time()
        if not isinstance(ev, dict):
            return False
        typ = ev.get("t")
        sid, vid = clean_id(ev.get("sid")), clean_id(ev.get("vid"))
        if not sid or not vid or typ not in ("hello", "beat", "page", "play", "search", "ai", "bye"):
            return False
        uid = clean_text(ev.get("uid"), 40) or None
        with self.lock:
            # Admin/Boss: loại hoàn toàn khỏi mọi thống kê & danh sách online
            if (uid and uid.lower() in ADMIN_USERNAMES) or vid in self.admin_vids or ev.get("adm") is True:
                if len(self.admin_vids) < 5000:
                    self.admin_vids.add(vid)
                self.presence.pop(sid, None)
                return False
            if typ == "bye":
                self.presence.pop(sid, None)
                return True

            device = ev.get("dev") if ev.get("dev") in ("mobile", "tablet", "desktop") else "desktop"
            page = clean_text(ev.get("page"), 40) or "home"
            p = self.presence.get(sid)
            fresh = p is None
            if fresh:
                p = {"sid": sid, "vid": vid, "uid": None, "connectedAt": now, "lastSeen": now, "page": page,
                     "device": device, "counted": typ != "hello",
                     "as": None if typ == "hello" else "restored"}
                self.presence[sid] = p
            p.update(lastSeen=now, page=page, device=device)
            if uid:
                p["uid"] = uid

            # Đếm phiên/người truy cập: đã đăng nhập -> theo userId; khách -> theo visitorId sau khi ở lại đủ lâu
            if uid and p.get("as") != "user":
                self._visit(uid, vid, now, device, count_session=p.get("as") is None)
                p["as"], p["counted"] = "user", True
            elif not uid and not p["counted"] and now - p["connectedAt"] >= GUEST_CONFIRM_SECONDS:
                self._visit(None, vid, now, device, count_session=True)
                p["as"], p["counted"] = "guest", True

            if not p["counted"]:
                return True  # khách chưa xác nhận: chỉ giữ presence
            pids = period_ids(now_local(now))

            if typ == "page":
                self._count(pids, pageViews=1)
            elif typ == "play" and uid:
                return self._on_play(ev, sid, uid, pids, now)
            elif typ == "search" and uid:
                return self._on_search(ev, vid, uid, pids, now)
            elif typ == "ai":
                self._on_ai(ev, pids)
            return True

    def _on_play(self, ev, sid, uid, pids, now):
        cid = ev.get("cid")
        if not isinstance(cid, str) or not CID_RE.match(cid):
            return False
        if self._dedupe(("play", sid, cid), 30, now):
            return False
        kind = "video" if ev.get("kind") == "video" else "audio"
        meta = {"title": clean_text(ev.get("title"), 200) or cid, "artist": clean_text(ev.get("artist"), 120),
                "kind": kind, "thumb": https_url(ev.get("thumb")), "lastAt": int(now * 1000)}
        for pid in pids.values():
            self._inc(f"analytics_content/{pid}/items/{cid}", plays=1)
            self._set(f"analytics_content/{pid}/items/{cid}", **meta)
        self._count(pids, plays=1)
        k = key_for("u", uid.lower())
        self._inc(f"analytics_accounts/{k}", plays=1)
        return True

    def _on_search(self, ev, vid, uid, pids, now):
        q = normalize_keyword(ev.get("q"))
        if not q:
            return False
        if self._dedupe(("search", vid, q), 10, now):
            return False
        res = ev.get("res")
        hit = isinstance(res, (int, float)) and not isinstance(res, bool) and res > 0
        miss = isinstance(res, (int, float)) and not isinstance(res, bool) and res <= 0
        kw = key_for("", q)
        for pid in pids.values():
            path = f"analytics_search/{pid}/items/{kw}"
            inc = {"count": 1}
            if hit:
                inc["hits"] = 1
            if miss:
                inc["miss"] = 1
            seen = (pid, kw, vid)
            if seen not in self.search_seen:
                self.search_seen.add(seen)
                inc["users"] = 1
            self._inc(path, **inc)
            self._set(path, q=q, lastAt=int(now * 1000))
        self._count(pids, searches=1, **({"searchHits": 1} if hit else {}), **({"searchMiss": 1} if miss else {}))
        self._inc(f"analytics_accounts/{key_for('u', uid.lower())}", searches=1)
        return True

    def _on_ai(self, ev, pids):
        ok = ev.get("ok") is True
        ms = ev.get("ms")
        ms = int(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) and 0 <= ms <= 120000 else 0
        self._count(pids, aiUses=1, **({"aiOk": 1, "aiMs": ms} if ok else {"aiFail": 1}))  # chỉ tính thời gian của yêu cầu thành công
        ch = ev.get("ch")
        if isinstance(ch, str) and CID_RE.match(ch):
            for pid in pids.values():
                path = f"analytics_aichan/{pid}/items/{ch}"
                self._inc(path, count=1)
                self._set(path, title=clean_text(ev.get("cht"), 120) or ch)
        vid = ev.get("v")
        if ok and isinstance(vid, str) and VIDEO_RE.match(vid):
            self.ai_recent.appendleft({"video_id": vid, "title": clean_text(ev.get("vt"), 160),
                                       "channel": clean_text(ev.get("cht"), 120), "at": int(time.time() * 1000)})
            self._ai_dirty = True

    # ---------- truy vấn cho Admin
    def online(self, flt="all"):
        now = time.time()
        with self.lock:
            rows = []
            for p in self.presence.values():
                if now - p["lastSeen"] > ONLINE_TTL or not (p["uid"] or p["counted"]):
                    continue
                rows.append({
                    "kind": "user" if p["uid"] else "guest", "name": p["uid"], "page": p["page"], "device": p["device"],
                    "connected_at": int(p["connectedAt"] * 1000), "last_seen": int(p["lastSeen"] * 1000),
                    "duration_s": int(now - p["connectedAt"]),
                })
        users = sum(1 for r in rows if r["kind"] == "user")
        out = [r for r in rows if flt == "all" or (flt == "guest" and r["kind"] == "guest") or (flt == "user" and r["kind"] == "user")]
        out.sort(key=lambda r: r["last_seen"], reverse=True)
        return {"total": len(rows), "users": users, "guests": len(rows) - users, "sessions": out[:200]}

    def _periods(self, ids):
        self.flush()
        docs = self.store.get_many([f"analytics_periods/{i}" for i in ids])
        return [d for d in docs]

    def overview(self):
        pids = period_ids(now_local())
        d, w, m, a = self._periods([pids["day"], pids["week"], pids["month"], "all"])
        g = lambda doc, k: int((doc or {}).get(k) or 0)  # noqa: E731
        return {
            "online": self.online()["total"],
            "visitors_today": g(d, "uniqueVisitors"), "visitors_week": g(w, "uniqueVisitors"),
            "visitors_month": g(m, "uniqueVisitors"), "visitors_total": g(a, "uniqueVisitors"),
            "plays_today": g(d, "plays"), "searches_today": g(d, "searches"), "ai_today": g(d, "aiUses"),
            "accounts_total": g(a, "accounts"), "has_data": bool(a),
        }

    def growth(self, metric, start, end):
        field = {"new": "newVisitors", "returning": "returningVisitors", "sessions": "sessions", "pageviews": "pageViews",
                 "plays": "plays", "searches": "searches", "ai": "aiUses"}.get(metric)
        if not field:
            raise ValueError("metric")
        days = (end - start).days + 1
        if days < 1 or days > 400:
            raise ValueError("range")
        if days > 92:  # gom theo tháng để đọc ít tài liệu
            labels, ids, cur = [], [], start.replace(day=1)
            while cur <= end:
                labels.append(f"{cur:%m/%Y}")
                ids.append(period_ids(cur)["month"])
                cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            bucket = "month"
        else:
            labels = [f"{(start + timedelta(days=i)):%d/%m}" for i in range(days)]
            ids = [period_ids(start + timedelta(days=i))["day"] for i in range(days)]
            bucket = "day"
        docs = self._periods(ids)
        values = [int((x or {}).get(field) or 0) for x in docs]
        return {"metric": metric, "bucket": bucket, "labels": labels, "values": values,
                "has_data": sum(values) > 0, "total": sum(values)}

    def _top(self, coll, pid, order, limit):
        self.flush()
        return self.store.list_docs(f"{coll}/{pid}/items", order, limit)

    def top_content(self, scope):
        dt = now_local()
        pid = period_ids(dt)[scope]
        rows = self._top("analytics_content", pid, "plays", 20)
        prev_id = prev_period_id(scope, dt)
        prev = {}
        if rows and prev_id:
            docs = self.store.get_many([f"analytics_content/{prev_id}/items/{r['_id']}" for r in rows])
            prev = {r["_id"]: d for r, d in zip(rows, docs)}
        items = []
        for i, r in enumerate(rows, 1):
            pv = prev.get(r["_id"])
            items.append({"rank": i, "content_id": r["_id"], "title": r.get("title"), "artist": r.get("artist"),
                          "kind": r.get("kind"), "thumb": r.get("thumb"), "plays": int(r.get("plays") or 0),
                          "change": (int(r.get("plays") or 0) - int(pv.get("plays") or 0)) if pv else None,
                          "is_new": bool(prev_id) and pv is None})
        return {"period": scope, "items": items}

    def keywords(self, scope):
        dt = now_local()
        pid = period_ids(dt)[scope]
        rows = self._top("analytics_search", pid, "count", 30)

        def shape(i, r):
            c = int(r.get("count") or 0)
            known = int(r.get("hits") or 0) + int(r.get("miss") or 0)
            return {"rank": i, "keyword": r.get("q"), "count": c, "users": int(r.get("users") or 0),
                    "hit_rate": round(int(r.get("hits") or 0) / known, 3) if known else None,
                    "miss_rate": round(int(r.get("miss") or 0) / known, 3) if known else None,
                    "last_at": r.get("lastAt")}
        items = [shape(i, r) for i, r in enumerate(rows, 1)]

        today_id, yest_id = period_ids(dt)["day"], prev_period_id("day", dt)
        today_rows = rows if scope == "day" else self._top("analytics_search", today_id, "count", 50)
        docs = self.store.get_many([f"analytics_search/{yest_id}/items/{r['_id']}" for r in today_rows]) if today_rows else []
        rising = []
        for r, yd in zip(today_rows, docs):
            c, y = int(r.get("count") or 0), int((yd or {}).get("count") or 0)
            if c >= 2 and c > y:
                rising.append({"keyword": r.get("q"), "today": c, "yesterday": y, "delta": c - y})
        rising.sort(key=lambda x: x["delta"], reverse=True)
        miss_rows = self._top("analytics_search", today_id, "miss", 1)
        miss = miss_rows[0] if miss_rows and int(miss_rows[0].get("miss") or 0) > 0 else None
        return {"period": scope, "items": items,
                "top_today": items[0]["keyword"] if scope == "day" and items else (today_rows[0].get("q") if today_rows else None),
                "rising": rising[0] if rising else None,
                "most_missed": {"keyword": miss.get("q"), "miss": int(miss.get("miss"))} if miss else None}

    def ai_stats(self):
        pids = period_ids(now_local())
        d, w, m, a = self._periods([pids["day"], pids["week"], pids["month"], "all"])
        g = lambda doc, k: int((doc or {}).get(k) or 0)  # noqa: E731
        top = self._top("analytics_aichan", "all", "count", 1)
        if not self._ai_recent_loaded:
            meta = self.store.get("analytics_meta/aiRecent") or {}
            with self.lock:
                if not self.ai_recent:
                    for it in reversed(meta.get("items") or []):
                        self.ai_recent.appendleft(it)
                self._ai_recent_loaded = True
        done = g(a, "aiOk") + g(a, "aiFail")
        return {"today": g(d, "aiUses"), "week": g(w, "aiUses"), "month": g(m, "aiUses"), "total": g(a, "aiUses"),
                "ok": g(a, "aiOk"), "fail": g(a, "aiFail"),
                "avg_ms": round(g(a, "aiMs") / g(a, "aiOk")) if g(a, "aiOk") else None,
                "top_channel": ({"channel_id": top[0]["_id"], "title": top[0].get("title"), "count": int(top[0].get("count") or 0)}
                                if top else None),
                "recent": list(self.ai_recent), "has_data": done > 0}

    def users(self, limit=100):
        self.flush()
        rows = self.store.list_docs("analytics_accounts", "lastSeen", limit)
        return [{"name": r.get("name"), "first_seen": r.get("firstSeen"), "last_seen": r.get("lastSeen"),
                 "sessions": int(r.get("sessions") or 0), "plays": int(r.get("plays") or 0),
                 "searches": int(r.get("searches") or 0), "device": r.get("device")} for r in rows]

    def system(self):
        return {"store": self.store.kind, "uptime_s": int(time.time() - self.started_at),
                "pending_docs": len(self.pending), "presence_sessions": len(self.presence),
                "flush_ok": self.flush_ok, "flush_err": self.flush_err, "last_flush": int(self.last_flush * 1000) if self.last_flush else None,
                "last_error": self.last_error, "flush_interval_s": FLUSH_SECONDS, "online_ttl_s": ONLINE_TTL,
                "persistent": self.store.kind == "firestore"}

    # ---------- nhật ký quản trị (ghi trực tiếp, ít khi xảy ra)
    def log_admin(self, action, ok, ip_hash, detail=""):
        entry = {"ts": int(time.time() * 1000), "action": clean_text(action, 40), "ok": bool(ok),
                 "ip": ip_hash, "detail": clean_text(detail, 160)}
        try:
            self.store.apply([(f"adminLogs/{uuid.uuid4().hex[:16]}", {}, entry)])
        except Exception as exc:
            log.warning("Không ghi được nhật ký quản trị (%s)", type(exc).__name__)

    def admin_logs(self, limit=100):
        return self.store.list_docs("adminLogs", "ts", limit)
