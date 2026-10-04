"""Lớp lưu trữ cho thống kê VanMusic.

- MemoryStore    : dùng khi chạy local / kiểm thử (mất dữ liệu khi tắt).
- FirestoreStore : dùng firebase-admin (bỏ qua Security Rules, chỉ backend được ghi/đọc).

Cả hai cùng giao diện nên logic thống kê không phụ thuộc loại lưu trữ.
Mỗi thao tác ghi là một "op" = (path, incs, sets):
  incs : {field: số} -> cộng dồn nguyên tử (FieldValue.increment)
  sets : {field: giá trị} -> ghi đè các trường đó (merge)
"""
from __future__ import annotations

import copy
import logging
import os
import threading

log = logging.getLogger("vanmusic.store")


class MemoryStore:
    kind = "memory"

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, path):
        with self._lock:
            d = self.docs.get(path)
            return copy.deepcopy(d) if d is not None else None

    def get_many(self, paths):
        return [self.get(p) for p in paths]

    def apply(self, ops):
        with self._lock:
            for path, incs, sets in ops:
                d = self.docs.setdefault(path, {})
                for k, v in (sets or {}).items():
                    d[k] = v
                for k, v in (incs or {}).items():
                    d[k] = (d.get(k) or 0) + v

    def list_docs(self, coll, order_field, limit, desc=True):
        prefix = coll.rstrip("/") + "/"
        with self._lock:
            rows = []
            for p, d in self.docs.items():
                if p.startswith(prefix) and "/" not in p[len(prefix):]:
                    rows.append((p[len(prefix):], copy.deepcopy(d)))
        rows.sort(key=lambda r: (r[1].get(order_field) or 0), reverse=desc)
        return [dict(r[1], _id=r[0]) for r in rows[:limit]]


class FirestoreStore:
    kind = "firestore"

    def __init__(self, client):
        from google.cloud import firestore  # noqa: WPS433

        self._fs = firestore
        self.client = client

    def get(self, path):
        snap = self.client.document(path).get()
        return snap.to_dict() if snap.exists else None

    def get_many(self, paths):
        if not paths:
            return []
        refs = [self.client.document(p) for p in paths]
        by_path = {s.reference.path: (s.to_dict() if s.exists else None)
                   for s in self.client.get_all(refs)}
        return [by_path.get(r.path) for r in refs]

    def apply(self, ops):
        inc = self._fs.Increment
        for i in range(0, len(ops), 400):
            batch = self.client.batch()
            for path, incs, sets in ops[i:i + 400]:
                data = dict(sets or {})
                for k, v in (incs or {}).items():
                    data[k] = inc(v)
                batch.set(self.client.document(path), data, merge=True)
            batch.commit()

    def list_docs(self, coll, order_field, limit, desc=True):
        direction = self._fs.Query.DESCENDING if desc else self._fs.Query.ASCENDING
        q = self.client.collection(coll).order_by(order_field, direction=direction).limit(limit)
        out = []
        for s in q.stream():
            d = s.to_dict() or {}
            d["_id"] = s.id
            out.append(d)
        return out


def build_store():
    """Chọn lưu trữ theo biến môi trường.

    FIREBASE_CREDENTIALS_JSON : nội dung JSON service account (khuyến nghị trên Render)
    GOOGLE_APPLICATION_CREDENTIALS : đường dẫn file service account
    VM_STORE=memory           : ép dùng bộ nhớ (local/test)
    """
    if os.getenv("VM_STORE", "").lower() == "memory":
        return MemoryStore()
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            raw = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
            if raw:
                import json
                cred = credentials.Certificate(json.loads(raw))
            elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                cred = credentials.ApplicationDefault()
            else:
                raise RuntimeError("Chưa cấu hình thông tin Firebase service account")
            firebase_admin.initialize_app(cred)
        return FirestoreStore(firestore.client())
    except Exception as exc:  # không để lỗi cấu hình làm sập backend AI hiện có
        log.warning("Không khởi tạo được Firestore (%s) -> dùng bộ nhớ tạm", type(exc).__name__)
        return MemoryStore()
