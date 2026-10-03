"""Thu thập thông tin kênh (channels.list, tối đa 50 kênh/lần gọi => 1 quota unit)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.data.schemas import RAW_CHANNEL_COLUMNS
from src.logger import get_logger
from src.youtube.client import YouTubeClient, YouTubeNotFoundError

log = get_logger(__name__)
CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_channel_ids(csv_path: str | Path) -> list[str]:
    df = pd.read_csv(csv_path, comment="#", encoding="utf-8")
    if "channel_id" not in df.columns:
        raise ValueError("channels.csv phải có cột channel_id")
    ids = [str(x).strip() for x in df["channel_id"].dropna() if str(x).strip()]
    bad = [i for i in ids if not CHANNEL_ID_RE.match(i)]
    if bad:
        log.warning("Bỏ qua Channel ID sai định dạng: %s", bad)
    return list(dict.fromkeys(i for i in ids if CHANNEL_ID_RE.match(i)))


def parse_channel_item(item: dict, collected_at: str) -> dict:
    sn, st, cd = item.get("snippet", {}), item.get("statistics", {}), item.get("contentDetails", {})
    hidden = bool(st.get("hiddenSubscriberCount", False))
    sub = None if hidden or "subscriberCount" not in st else int(st["subscriberCount"])

    def _int(k):
        return int(st[k]) if k in st else None

    return {
        "channel_id": item["id"], "channel_title": sn.get("title"),
        "channel_published_at": sn.get("publishedAt"), "subscriber_count": sub,
        "hidden_subscriber_count": hidden, "channel_total_views": _int("viewCount"),
        "channel_video_count": _int("videoCount"),
        "uploads_playlist_id": cd.get("relatedPlaylists", {}).get("uploads"),
        "collected_at": collected_at,
    }


def fetch_channels(client: YouTubeClient, channel_ids: list[str], collected_at: str | None = None) -> list[dict]:
    collected_at = collected_at or utc_now_iso()
    out: list[dict] = []
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i:i + 50]
        resp = client.channels_list(part="snippet,statistics,contentDetails", id=",".join(batch), maxResults=50)
        found = {it["id"]: it for it in resp.get("items", [])}
        for cid in batch:
            if cid in found:
                out.append(parse_channel_item(found[cid], collected_at))
            else:
                log.warning("Không tìm thấy kênh %s", cid)
    return out


def channels_to_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=RAW_CHANNEL_COLUMNS)


def resolve_channel_input(client: YouTubeClient, text: str) -> str:
    """Nhận Channel ID, URL /channel/UC..., URL @handle hoặc @handle => trả về Channel ID (UC...)."""
    s = (text or "").strip()
    if CHANNEL_ID_RE.match(s):
        return s
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", s)
    if m:
        return m.group(1)
    m = re.search(r"(?:youtube\.com/)?(@[\w.\-]+)", s)
    if m:
        resp = client.channels_list(part="id", forHandle=m.group(1), maxResults=1)
        items = resp.get("items", [])
        if items:
            return items[0]["id"]
        raise YouTubeNotFoundError(f"Không tìm thấy kênh với handle {m.group(1)}")
    raise ValueError("Định dạng kênh không hợp lệ. Dùng Channel ID (UC...), URL kênh hoặc @handle.")
