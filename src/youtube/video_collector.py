"""Lấy video qua uploads playlist (1 unit/trang) rồi videos.list theo batch 50 (1 unit/batch)."""
from __future__ import annotations

import json

import pandas as pd

from src.data.feature_engineering import parse_duration_seconds
from src.data.schemas import RAW_VIDEO_COLUMNS
from src.logger import get_logger
from src.youtube.client import YouTubeClient

log = get_logger(__name__)


def fetch_upload_video_ids(client: YouTubeClient, uploads_playlist_id: str, max_videos: int) -> list[str]:
    ids: list[str] = []
    token = None
    while len(ids) < max_videos:
        kw = dict(part="contentDetails", playlistId=uploads_playlist_id, maxResults=min(50, max_videos - len(ids)))
        if token:
            kw["pageToken"] = token
        resp = client.playlist_items_list(**kw)
        ids += [it["contentDetails"]["videoId"] for it in resp.get("items", [])]
        token = resp.get("nextPageToken")
        if not token:
            break
    return ids[:max_videos]


def _opt_int(d: dict, key: str):
    return int(d[key]) if key in d else None


def parse_video_item(item: dict, collected_at: str) -> dict:
    sn, cd, st = item.get("snippet", {}), item.get("contentDetails", {}), item.get("statistics", {})
    duration = cd.get("duration")
    caption = cd.get("caption")
    return {
        "video_id": item["id"], "channel_id": sn.get("channelId"), "title": sn.get("title", ""),
        "description": sn.get("description", ""), "published_at": sn.get("publishedAt"),
        "tags": json.dumps(sn.get("tags", []), ensure_ascii=False),
        "category_id": sn.get("categoryId"), "duration": duration,
        "duration_seconds": parse_duration_seconds(duration),
        "definition": cd.get("definition"),
        "caption": None if caption is None else str(caption).lower() == "true",
        "view_count": _opt_int(st, "viewCount"), "like_count": _opt_int(st, "likeCount"),
        "comment_count": _opt_int(st, "commentCount"),
        "has_live_streaming_details": "liveStreamingDetails" in item,
        "live_broadcast_content": sn.get("liveBroadcastContent"),
        "collected_at": collected_at,
    }


def fetch_video_details(client: YouTubeClient, video_ids: list[str], collected_at: str) -> list[dict]:
    rows: list[dict] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = client.videos_list(part="snippet,contentDetails,statistics,liveStreamingDetails",
                                  id=",".join(batch), maxResults=50)
        rows += [parse_video_item(it, collected_at) for it in resp.get("items", [])]
    return rows


def videos_to_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=RAW_VIDEO_COLUMNS)
