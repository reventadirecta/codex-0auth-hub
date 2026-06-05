import datetime as dt
import json
import urllib.parse
import urllib.request
from typing import Any

from googleapiclient.discovery import build

from .config import read_api_key
from .google_auth import get_existing_credentials
from .registry import get_connection


def get_youtube_data_connection(connection_id: str | None = None):
    return get_connection("youtube_data", connection_id)


def get_youtube_analytics_connection(connection_id: str | None = None):
    return get_connection("youtube_analytics", connection_id)


def _youtube_data_api_get(path: str, params: dict[str, Any], api_key: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"key": api_key, **params})
    url = f"https://www.googleapis.com/youtube/v3/{path}?{query}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _youtube_analytics_get(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def get_channel_details(connection_id: str | None = None) -> dict[str, Any]:
    _config, _account, _service, entry = get_youtube_data_connection(connection_id)
    api_key = read_api_key(entry["apiKeyFile"])
    channel_id = entry["channelId"]
    data = _youtube_data_api_get(
        "channels",
        {"id": channel_id, "part": "snippet,contentDetails,statistics"},
        api_key,
    )
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"Channel {channel_id} was not found in YouTube Data API.")
    return items[0]


def list_upload_video_ids(connection_id: str | None = None, max_results: int = 200) -> list[str]:
    channel = get_channel_details(connection_id)
    uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_playlist:
        return []

    _config, _account, _service, entry = get_youtube_data_connection(connection_id)
    api_key = read_api_key(entry["apiKeyFile"])

    video_ids: list[str] = []
    page_token = None
    while len(video_ids) < max_results:
        params: dict[str, Any] = {
            "playlistId": uploads_playlist,
            "part": "contentDetails",
            "maxResults": min(50, max_results - len(video_ids)),
        }
        if page_token:
            params["pageToken"] = page_token

        data = _youtube_data_api_get("playlistItems", params, api_key)
        for item in data.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return video_ids


def get_video_details(video_ids: list[str], connection_id: str | None = None) -> list[dict[str, Any]]:
    if not video_ids:
        return []

    _config, _account, _service, entry = get_youtube_data_connection(connection_id)
    api_key = read_api_key(entry["apiKeyFile"])

    items: list[dict[str, Any]] = []
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        data = _youtube_data_api_get(
            "videos",
            {
                "id": ",".join(chunk),
                "part": "snippet,contentDetails,statistics,status",
                "maxResults": len(chunk),
            },
            api_key,
        )
        items.extend(data.get("items", []))

    found_ids = {item.get("id") for item in items}
    missing_ids = [video_id for video_id in video_ids if video_id not in found_ids]
    if missing_ids:
        youtube = get_youtube_service(connection_id)
        for start in range(0, len(missing_ids), 50):
            chunk = missing_ids[start : start + 50]
            response = youtube.videos().list(
                part="snippet,contentDetails,statistics,status",
                id=",".join(chunk),
                maxResults=len(chunk),
            ).execute()
            items.extend(response.get("items", []))

    return items


def get_youtube_service(connection_id: str | None = None):
    config, _account, service, entry = get_connection("youtube", connection_id)
    token_id = entry.get("tokenId", entry["id"])
    creds = get_existing_credentials(config, f"{service}.{token_id}", entry.get("scopes", []))
    if not creds:
        raise RuntimeError("No valid YouTube OAuth token found.")
    return build("youtube", "v3", credentials=creds)


def analytics_query(
    start_date: dt.date,
    end_date: dt.date,
    metrics: list[str],
    dimensions: list[str] | None = None,
    sort: list[str] | None = None,
    filters: dict[str, str] | None = None,
    max_results: int | None = None,
    connection_id: str | None = None,
) -> dict[str, Any]:
    config, _account, service, entry = get_youtube_analytics_connection(connection_id)
    token_id = entry.get("tokenId", entry["id"])
    scopes = entry.get("scopes", [])
    creds = get_existing_credentials(config, f"{service}.{token_id}", scopes)
    if not creds:
        raise RuntimeError(
            "No valid YouTube Analytics OAuth token with required scopes. "
            "Run: python -m scripts.auth_google youtube_analytics"
        )

    params: dict[str, Any] = {
        "ids": entry.get("ids", "channel==MINE"),
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "metrics": ",".join(metrics),
    }
    if dimensions:
        params["dimensions"] = ",".join(dimensions)
    if sort:
        params["sort"] = ",".join(sort)
    if filters:
        params["filters"] = ";".join(f"{key}=={value}" for key, value in filters.items())
    if max_results:
        params["maxResults"] = max_results

    query = urllib.parse.urlencode(params)
    url = f"https://youtubeanalytics.googleapis.com/v2/reports?{query}"
    return _youtube_analytics_get(url, creds.token)
