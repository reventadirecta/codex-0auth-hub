import csv
import datetime as dt
import json
import math
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import read_api_key
from .google_auth import get_existing_credentials
from .paths import ROOT
from .registry import get_connection
from .youtube_api import _youtube_data_api_get, analytics_query


REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data" / "youtube_tag_intelligence"
CONFIG_DIR = ROOT / "config"
SEEDS_LOCAL_PATH = CONFIG_DIR / "tag_seeds.local.json"
SEEDS_EXAMPLE_PATH = CONFIG_DIR / "tag_seeds.example.json"
COMPETITORS_LOCAL_PATH = CONFIG_DIR / "competitors.local.json"

DEFAULT_GENERIC_PENALTIES = ["ai", "ia", "tech", "tutorial", "shorts", "viral", "tools", "gratis"]
DEFAULT_NEGATIVE_TERMS = ["crypto", "trading", "casino", "betting"]
STRATEGIC_TOKENS = {
    "ollama",
    "lm",
    "studio",
    "local",
    "llm",
    "hermes",
    "agent",
    "agents",
    "zero",
    "openclaw",
    "codex",
    "comfyui",
    "ltx",
    "runway",
    "gpu",
    "vram",
    "hardware",
    "video",
    "imagen",
    "image",
    "windows",
    "autonomos",
    "autonomous",
}
YOUTUBE_TAG_USAGE = "youtube_tags"
HASHTAG_USAGE = "hashtags"
SEARCH_PHRASE_USAGE = "description"
TOPIC_USAGE = "title_support"
BROAD_TAG_USAGE = "article_support"
NEGATIVE_USAGE = "avoid"


def ensure_output_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9áéíóúñ\-\+]+", normalize_text(text))


def slug_tag(text: str) -> str:
    words = [word for word in re.findall(r"[A-Za-z0-9ÁÉÍÓÚÑáéíóúñ]+", text or "") if word]
    if not words:
        return ""
    return "#" + "".join(word[:1].upper() + word[1:] for word in words[:4])


def score_band(score100: int) -> str:
    if score100 <= 20:
        return "mala o ruido"
    if score100 <= 40:
        return "floja"
    if score100 <= 60:
        return "usable"
    if score100 <= 75:
        return "buena"
    if score100 <= 89:
        return "muy buena"
    return "excelente"


def confidence_from_sources(
    sources: list[str],
    own_signal: float,
    competitor_signal: float,
    channel_fit: float,
    entity_strength: float,
    term_type: str,
) -> str:
    unique_sources = set(sources)
    external_sources = unique_sources - {"seed_config"}
    if own_signal >= 8:
        return "alta"
    if competitor_signal >= 8 and external_sources:
        return "alta"
    if entity_strength >= 14 and channel_fit >= 14 and external_sources:
        return "alta"
    if external_sources:
        return "media"
    if channel_fit >= 14 and term_type in {"youtube_tag", "topic_entity", "search_phrase"}:
        return "media"
    return "baja"


def load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed_config(seed_filter: str | None = None) -> tuple[dict[str, Any], Path, bool, str | None]:
    if SEEDS_LOCAL_PATH.exists():
        payload = load_json_file(SEEDS_LOCAL_PATH)
        source_path = SEEDS_LOCAL_PATH
        example_used = False
        warning = None
    else:
        payload = load_json_file(SEEDS_EXAMPLE_PATH)
        source_path = SEEDS_EXAMPLE_PATH
        example_used = True
        warning = "config/tag_seeds.local.json was not found. Example seeds were used as fallback."

    groups = payload.get("seedGroups", [])
    if seed_filter:
        seed_filter_norm = normalize_text(seed_filter)
        groups = [
            group
            for group in groups
            if seed_filter_norm in normalize_text(group.get("label", ""))
            or any(seed_filter_norm in normalize_text(term) for term in group.get("terms", []))
        ]
    payload = dict(payload)
    payload["seedGroups"] = groups
    return payload, source_path, example_used, warning


def source_status(
    available: bool,
    mode: str,
    reason: str = "",
    details: dict[str, Any] | None = None,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "available": available,
        "mode": mode,
        "reason": reason,
        "details": details or {},
        "blocking": blocking,
    }


def get_youtube_data_api_key() -> tuple[str | None, str]:
    try:
        _config, _account, _service, entry = get_connection("youtube_data")
        return read_api_key(entry["apiKeyFile"]), entry.get("id", "")
    except Exception as exc:
        return None, str(exc)


def load_competitors_local() -> tuple[list[dict[str, Any]], str]:
    if not COMPETITORS_LOCAL_PATH.exists():
        return [], "config/competitors.local.json not found."
    payload = load_json_file(COMPETITORS_LOCAL_PATH)
    competitors = payload.get("competitors", [])
    normalized: list[dict[str, Any]] = []
    for item in competitors:
        normalized.append(
            {
                "id": item.get("id", ""),
                "name": item.get("name") or item.get("label", ""),
                "youtubeChannelId": item.get("youtubeChannelId") or item.get("channelId", ""),
                "url": item.get("url") or item.get("channelUrl", ""),
                "category": item.get("category") or item.get("classification", ""),
                "priority": item.get("priority", "B"),
                "notes": item.get("notes", ""),
            }
        )
    normalized = [item for item in normalized if item["youtubeChannelId"]]
    return normalized, ""


def try_analytics_search_terms(report_date: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start_date = report_date - dt.timedelta(days=89)
    end_date = report_date - dt.timedelta(days=1)
    try:
        payload = analytics_query(
            start_date,
            end_date,
            metrics=["views", "estimatedMinutesWatched"],
            dimensions=["insightTrafficSourceDetail"],
            filters={"insightTrafficSourceType": "YT_SEARCH"},
            sort=["-views"],
            max_results=50,
        )
    except Exception as exc:
        message = str(exc)
        if "HTTP Error 500" in message:
            return [], source_status(False, "skipped", "HTTP 500 from YouTube Analytics search terms endpoint.")
        return [], source_status(False, "skipped", f"YouTube Analytics search terms not available: {message}")

    columns = [item["name"] for item in payload.get("columnHeaders", [])]
    rows = [dict(zip(columns, row)) for row in payload.get("rows", [])]
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        term = str(row.get("insightTrafficSourceDetail", "")).strip()
        if not term:
            continue
        normalized_rows.append(
            {
                "term": term,
                "views": safe_float(row.get("views")),
                "estimatedMinutesWatched": safe_float(row.get("estimatedMinutesWatched")),
            }
        )
    return normalized_rows, source_status(True, "used", details={"rows": len(normalized_rows)})


def try_search_console_queries(report_date: dt.date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        config, _account, service, entry = get_connection("search_console")
        token_id = entry.get("tokenId", entry["id"])
        scopes = entry.get("scopes", [])
        creds = get_existing_credentials(config, f"{service}.{token_id}", scopes)
        if not creds:
            return [], source_status(False, "skipped", "No valid Search Console OAuth token.")
        site_url = entry.get("siteUrl", "").strip()
        if not site_url:
            return [], source_status(False, "skipped", "Search Console siteUrl is empty in local config.")
        start_date = report_date - dt.timedelta(days=89)
        end_date = report_date - dt.timedelta(days=1)
        body = json.dumps(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["query"],
                "rowLimit": 100,
            }
        ).encode("utf-8")
        encoded_site = urllib.parse.quote(site_url, safe="")
        request = urllib.request.Request(
            f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query",
            data=body,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [], source_status(False, "skipped", f"Search Console not available: {exc}")

    rows = payload.get("rows", [])
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        keys = row.get("keys", [])
        query = keys[0] if keys else ""
        if not query:
            continue
        normalized_rows.append(
            {
                "term": query,
                "clicks": safe_float(row.get("clicks")),
                "impressions": safe_float(row.get("impressions")),
                "ctr": safe_float(row.get("ctr")) * 100.0,
                "position": safe_float(row.get("position")),
            }
        )
    return normalized_rows, source_status(True, "used", details={"rows": len(normalized_rows)})


def try_custom_search_status() -> dict[str, Any]:
    try:
        _config, _account, _service, entry = get_connection("search")
        if not entry.get("engineId"):
            return source_status(False, "skipped", "Google Custom Search engineId/CX missing.")
        _api_key = read_api_key(entry["apiKeyFile"])
        return source_status(True, "available_not_used", "Configured but not required for v1 scoring.")
    except Exception as exc:
        return source_status(False, "skipped", f"Google Custom Search not available: {exc}")


def build_seed_queries(seed_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in seed_payload.get("seedGroups", []):
        for term in group.get("terms", []):
            rows.append(
                {
                    "seedGroup": group.get("id", ""),
                    "seedLabel": group.get("label", ""),
                    "term": term,
                    "language": group.get("language", seed_payload.get("defaultLanguage", "es")),
                    "region": group.get("region", seed_payload.get("defaultRegion", "ES")),
                    "priority": group.get("priority", "B"),
                }
            )
    return rows


def youtube_public_search(seed_queries: list[dict[str, Any]], api_key: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not api_key:
        return [], source_status(False, "skipped", "YouTube Data API v3 public key not available.")

    rows: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()
    for row in seed_queries:
        try:
            search_payload = _youtube_data_api_get(
                "search",
                {
                    "q": row["term"],
                    "part": "snippet",
                    "type": "video",
                    "order": "relevance",
                    "maxResults": 8,
                    "relevanceLanguage": row["language"],
                    "regionCode": row["region"],
                },
                api_key,
            )
        except Exception:
            continue
        video_ids = []
        for item in search_payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if video_id and video_id not in seen_video_ids:
                seen_video_ids.add(video_id)
                video_ids.append(video_id)
        if not video_ids:
            continue
        try:
            videos_payload = _youtube_data_api_get(
                "videos",
                {
                    "id": ",".join(video_ids),
                    "part": "snippet,statistics,contentDetails",
                    "maxResults": len(video_ids),
                },
                api_key,
            )
        except Exception:
            continue
        for item in videos_payload.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            rows.append(
                {
                    "seedTerm": row["term"],
                    "seedGroup": row["seedGroup"],
                    "priority": row["priority"],
                    "videoId": item.get("id", ""),
                    "videoTitle": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "channelTitle": snippet.get("channelTitle", ""),
                    "publishedAt": snippet.get("publishedAt", ""),
                    "viewsPublic": safe_float(stats.get("viewCount")),
                    "likesPublic": safe_float(stats.get("likeCount")),
                    "commentsPublic": safe_float(stats.get("commentCount")),
                    "videoUrl": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                }
            )
    return rows, source_status(True, "used", details={"rows": len(rows)})


def fetch_competitor_public_videos(api_key: str | None, competitors: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not api_key:
        return [], source_status(False, "skipped", "YouTube Data API v3 public key not available.")
    if not competitors:
        return [], source_status(False, "skipped", "No local competitors config available.")

    rows: list[dict[str, Any]] = []
    for competitor in competitors[:20]:
        try:
            channels_payload = _youtube_data_api_get(
                "channels",
                {
                    "id": competitor["youtubeChannelId"],
                    "part": "contentDetails,snippet",
                    "maxResults": 1,
                },
                api_key,
            )
            items = channels_payload.get("items", [])
            if not items:
                continue
            uploads = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if not uploads:
                continue
            playlist_payload = _youtube_data_api_get(
                "playlistItems",
                {
                    "playlistId": uploads,
                    "part": "contentDetails",
                    "maxResults": 6,
                },
                api_key,
            )
            video_ids = [
                item.get("contentDetails", {}).get("videoId")
                for item in playlist_payload.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            if not video_ids:
                continue
            videos_payload = _youtube_data_api_get(
                "videos",
                {
                    "id": ",".join(video_ids),
                    "part": "snippet,statistics",
                    "maxResults": len(video_ids),
                },
                api_key,
            )
            for item in videos_payload.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                rows.append(
                    {
                        "competitor": competitor["name"],
                        "channelId": competitor["youtubeChannelId"],
                        "priority": competitor["priority"],
                        "videoTitle": snippet.get("title", ""),
                        "description": snippet.get("description", ""),
                        "viewsPublic": safe_float(stats.get("viewCount")),
                        "videoUrl": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                    }
                )
        except Exception:
            continue
    return rows, source_status(True, "used", details={"rows": len(rows), "competitors": len(competitors)})


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def dedupe_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        norm = normalize_text(value)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        ordered.append(value)
    return ordered


def build_generated_terms(seed_payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    default_language = seed_payload.get("defaultLanguage", "es")
    default_region = seed_payload.get("defaultRegion", "ES")
    for group in seed_payload.get("seedGroups", []):
        terms = dedupe_terms(group.get("terms", []))
        seed_group = group.get("id", "")
        label = group.get("label", "")
        language = group.get("language", default_language)
        region = group.get("region", default_region)
        priority = group.get("priority", "B")
        for term in terms:
            norm = normalize_text(term)
            records.append(base_term_record(term, norm, "topic_entity", seed_group, language, region, priority, label))
            records.append(base_term_record(norm, norm, "youtube_tag", seed_group, language, region, priority, label))
            hashtag = slug_tag(term)
            if hashtag:
                records.append(base_term_record(hashtag, normalize_text(hashtag.lstrip("#")), "hashtag", seed_group, language, region, priority, label))
            if len(tokenize(term)) >= 2:
                phrase = f"como usar {norm}"
                records.append(base_term_record(phrase, normalize_text(phrase), "search_phrase", seed_group, language, region, priority, label))
            if "ollama" in norm:
                add_extra_records(records, ["ollama local windows", "como usar ollama en local", "modelos ia local"], seed_group, language, region, priority, label)
            if "hermes" in norm:
                add_extra_records(records, ["hermes agent con ollama", "instalar hermes agent local"], seed_group, language, region, priority, label)
            if "agent zero" in norm or "zero" in norm:
                add_extra_records(records, ["instalar agent zero local", "agent zero local windows"], seed_group, language, region, priority, label)
            if "openclaw" in norm:
                add_extra_records(records, ["openclaw ollama", "openclaw local ai"], seed_group, language, region, priority, label)
            if "codex" in norm:
                add_extra_records(records, ["codex autonomous agent", "codex agent local workflow"], seed_group, language, region, priority, label)
            if "comfyui" in norm:
                add_extra_records(records, ["comfyui workflow video ia", "comfyui video generation"], seed_group, language, region, priority, label)
            if "runway" in norm or "ltx" in norm or "video" in norm:
                add_extra_records(records, ["generacion de video ia", "ai video generation"], seed_group, language, region, priority, label)
            if "gpu" in norm or "vram" in norm or "hardware" in norm or "rtx" in norm:
                add_extra_records(records, ["gpu barata para ia local", "gpu para ia local", "vram ia local"], seed_group, language, region, priority, label)
        broad_terms = [label.lower(), "inteligencia artificial"] if "ai" in normalize_text(label) or "ia" in normalize_text(label) else [label.lower()]
        for broad in dedupe_terms(broad_terms):
            records.append(base_term_record(broad, normalize_text(broad), "broad_tag", seed_group, language, region, priority, label))
    for negative in seed_payload.get("negativeTerms", DEFAULT_NEGATIVE_TERMS):
        records.append(base_term_record(negative, normalize_text(negative), "negative_tag", "negative", default_language, default_region, "C", "Negative terms"))
    return dedupe_records(records)


def add_extra_records(
    records: list[dict[str, Any]],
    phrases: list[str],
    seed_group: str,
    language: str,
    region: str,
    priority: str,
    label: str,
) -> None:
    for phrase in phrases:
        normalized = normalize_text(phrase)
        records.append(base_term_record(phrase, normalized, "search_phrase", seed_group, language, region, priority, label))
        records.append(base_term_record(normalized, normalized, "youtube_tag", seed_group, language, region, priority, label))


def base_term_record(
    term: str,
    normalized_term: str,
    term_type: str,
    seed_group: str,
    language: str,
    region: str,
    priority: str,
    label: str,
) -> dict[str, Any]:
    return {
        "term": term,
        "normalizedTerm": normalized_term,
        "type": term_type,
        "rawScore": 0.0,
        "score100": 0,
        "scoreBand": "",
        "typeRawScore": 0.0,
        "typeScore100": 0,
        "calibratedScore100": 0,
        "typeRank": 0,
        "globalRank": 0,
        "typeScoreBand": "",
        "typeCalibrationReason": "",
        "specificity": 0.0,
        "channelFit": 0.0,
        "searchIntent": 0.0,
        "competitorUsage": 0.0,
        "ownChannelSignal": 0.0,
        "trendSignal": 0.0,
        "longTailBonus": 0.0,
        "entityStrength": 0.0,
        "genericPenalty": 0.0,
        "saturationPenalty": 0.0,
        "mismatchPenalty": 0.0,
        "negativePenalty": 0.0,
        "sources": ["seed_config"],
        "recommendedUsage": recommended_usage(term_type),
        "confidence": "baja",
        "reason": "",
        "seedGroup": seed_group,
        "language": language,
        "region": region,
        "priority": priority,
        "seedLabel": label,
        "relatedTerms": [],
        "exampleVideos": [],
        "notes": "",
    }


def recommended_usage(term_type: str) -> str:
    return {
        "youtube_tag": YOUTUBE_TAG_USAGE,
        "hashtag": HASHTAG_USAGE,
        "search_phrase": SEARCH_PHRASE_USAGE,
        "topic_entity": TOPIC_USAGE,
        "broad_tag": BROAD_TAG_USAGE,
        "negative_tag": NEGATIVE_USAGE,
    }.get(term_type, YOUTUBE_TAG_USAGE)


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (record["type"], record["normalizedTerm"])
        if key not in merged:
            merged[key] = record
            continue
        existing = merged[key]
        if record["seedGroup"] not in existing["seedGroup"]:
            existing["seedGroup"] = existing["seedGroup"] or record["seedGroup"]
        if record["term"] not in existing["relatedTerms"] and record["term"] != existing["term"]:
            existing["relatedTerms"].append(record["term"])
    return list(merged.values())


def group_terms_by_seed(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["seedGroup"]].append(record)
    return grouped


def build_signal_maps(
    records: list[dict[str, Any]],
    youtube_public_rows: list[dict[str, Any]],
    competitor_rows: list[dict[str, Any]],
    analytics_rows: list[dict[str, Any]],
    search_console_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    signals: dict[str, dict[str, Any]] = {}
    for record in records:
        signals[record["normalizedTerm"]] = {
            "youtubeMatches": [],
            "competitorMatches": [],
            "analyticsMatches": [],
            "searchConsoleMatches": [],
        }
    for row in youtube_public_rows:
        haystack = normalize_text(f"{row['videoTitle']} {row['description']} {row['seedTerm']}")
        for record in records:
            if record["normalizedTerm"] and record["normalizedTerm"] in haystack:
                signals[record["normalizedTerm"]]["youtubeMatches"].append(row)
    for row in competitor_rows:
        haystack = normalize_text(f"{row['videoTitle']} {row['description']}")
        for record in records:
            if record["normalizedTerm"] and record["normalizedTerm"] in haystack:
                signals[record["normalizedTerm"]]["competitorMatches"].append(row)
    for row in analytics_rows:
        haystack = normalize_text(row["term"])
        for record in records:
            if record["normalizedTerm"] and (record["normalizedTerm"] in haystack or haystack in record["normalizedTerm"]):
                signals[record["normalizedTerm"]]["analyticsMatches"].append(row)
    for row in search_console_rows:
        haystack = normalize_text(row["term"])
        for record in records:
            if record["normalizedTerm"] and (record["normalizedTerm"] in haystack or haystack in record["normalizedTerm"]):
                signals[record["normalizedTerm"]]["searchConsoleMatches"].append(row)
    return signals


def compute_specificity(term: str, term_type: str) -> float:
    tokens = tokenize(term)
    if not tokens:
        return 5.0
    base = min(22.0, 6.0 + len(tokens) * 3.0)
    if term_type == "search_phrase":
        base += 4.0
    if len(tokens) == 1 and len(tokens[0]) <= 3:
        base -= 6.0
    return max(1.0, base)


def compute_channel_fit(term: str) -> float:
    tokens = set(tokenize(term))
    strategic_hits = len(tokens & STRATEGIC_TOKENS)
    if strategic_hits >= 3:
        return 20.0
    if strategic_hits == 2:
        return 16.0
    if strategic_hits == 1:
        return 11.0
    return 5.0


def compute_search_intent(term: str, term_type: str, analytics_matches: list[dict[str, Any]], search_console_matches: list[dict[str, Any]]) -> float:
    normalized = normalize_text(term)
    score = 4.0 if term_type in {"youtube_tag", "topic_entity"} else 6.0
    if term_type == "search_phrase":
        score += 6.0
    if any(token in normalized for token in ["como", "instalar", "usar", "windows", "local", "workflow", "gpu para"]):
        score += 4.0
    if analytics_matches:
        score += min(6.0, math.log1p(sum(item.get("views", 0.0) for item in analytics_matches)))
    if search_console_matches:
        score += min(6.0, math.log1p(sum(item.get("impressions", 0.0) for item in search_console_matches)))
    return min(20.0, score)


def compute_competitor_usage(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    views = sum(item.get("viewsPublic", 0.0) for item in rows)
    return min(18.0, 4.0 + math.log1p(max(views, 0.0)))


def compute_own_signal(analytics_matches: list[dict[str, Any]], search_console_matches: list[dict[str, Any]]) -> float:
    score = 0.0
    if analytics_matches:
        score += min(10.0, 3.0 + math.log1p(sum(item.get("views", 0.0) for item in analytics_matches)))
    if search_console_matches:
        impressions = sum(item.get("impressions", 0.0) for item in search_console_matches)
        score += min(10.0, 3.0 + math.log1p(impressions))
    return min(20.0, score)


def compute_trend_signal(youtube_matches: list[dict[str, Any]]) -> float:
    if not youtube_matches:
        return 0.0
    views = sum(item.get("viewsPublic", 0.0) for item in youtube_matches[:10])
    recency_bonus = sum(1.0 for item in youtube_matches[:10] if str(item.get("publishedAt", ""))[:4] >= "2025")
    return min(16.0, 3.0 + math.log1p(views) + recency_bonus * 0.5)


def compute_long_tail_bonus(term: str, term_type: str) -> float:
    tokens = tokenize(term)
    if term_type != "search_phrase" and len(tokens) < 3:
        return 0.0
    if 3 <= len(tokens) <= 6:
        return 9.0
    if len(tokens) == 2:
        return 4.0
    if len(tokens) > 6:
        return 2.0
    return 0.0


def compute_entity_strength(term: str, term_type: str) -> float:
    normalized = normalize_text(term)
    score = 0.0
    if term_type == "topic_entity":
        score += 8.0
    if any(token in normalized for token in ["ollama", "hermes", "openclaw", "agent zero", "codex", "comfyui", "runway", "gpu", "vram"]):
        score += 8.0
    return min(18.0, score)


def compute_generic_penalty(term: str, generic_penalties: list[str]) -> float:
    normalized = normalize_text(term)
    tokens = tokenize(term)
    score = 0.0
    if normalized in {normalize_text(item) for item in generic_penalties}:
        score += 14.0
    for penalty in generic_penalties:
        if normalize_text(penalty) in normalized and len(tokens) <= 2:
            score += 4.0
    return min(18.0, score)


def compute_saturation_penalty(youtube_matches: list[dict[str, Any]], specificity: float) -> float:
    if not youtube_matches:
        return 0.0
    if len(youtube_matches) >= 8 and specificity <= 12.0:
        return 8.0
    if len(youtube_matches) >= 5 and specificity <= 15.0:
        return 4.0
    return 0.0


def compute_mismatch_penalty(term: str, negative_terms: list[str]) -> float:
    normalized = normalize_text(term)
    if any(negative in normalized for negative in ["casino", "betting", "trading", "crypto"]):
        return 14.0
    if "gaming" in normalized or "tarkov" in normalized:
        return 5.0
    if any(normalize_text(term) == normalize_text(negative) for negative in negative_terms):
        return 12.0
    return 0.0


def compute_negative_penalty(term: str, negative_terms: list[str], term_type: str) -> float:
    normalized = normalize_text(term)
    if term_type == "negative_tag":
        return 20.0
    if any(normalize_text(item) in normalized for item in negative_terms):
        return 16.0
    return 0.0


def build_reason(record: dict[str, Any]) -> str:
    parts = []
    if record["specificity"] >= 16:
        parts.append("specific")
    if record["channelFit"] >= 15:
        parts.append("strong channel fit")
    if record["ownChannelSignal"] >= 8:
        parts.append("own channel signal")
    if record["competitorUsage"] >= 8:
        parts.append("competitor usage")
    if record["searchIntent"] >= 10:
        parts.append("clear search intent")
    if record["genericPenalty"] >= 8:
        parts.append("generic penalty")
    if record["negativePenalty"] >= 12:
        parts.append("negative term")
    return ", ".join(parts) if parts else "Seed-derived term with limited supporting signals."


def type_calibration_components(record: dict[str, Any], source_count: int) -> tuple[float, str]:
    term_type = record["type"]
    token_count = len(tokenize(record["term"]))
    only_seed = source_count <= 1
    normalized = normalize_text(record["term"])

    if term_type == "negative_tag":
        return 1.0, "Negative tag forced low by design."

    if term_type == "search_phrase":
        value = (
            record["specificity"] * 0.95
            + record["searchIntent"] * 1.2
            + record["longTailBonus"] * 1.25
            + record["channelFit"] * 0.85
            + record["competitorUsage"] * 0.5
            + record["ownChannelSignal"] * 0.8
            + record["trendSignal"] * 0.4
            + record["entityStrength"] * 0.45
            - record["genericPenalty"] * 0.85
            - record["saturationPenalty"] * 0.55
            - record["mismatchPenalty"]
            - record["negativePenalty"]
        )
        if len(record["term"]) > 34:
            value -= 5.0
        if only_seed:
            value -= 5.0
        return value, "Search phrase kept strong for intent and long-tail value, but trimmed if only seed-derived or too description-like."

    if term_type == "youtube_tag":
        value = (
            record["specificity"] * 0.7
            + record["channelFit"] * 1.1
            + record["searchIntent"] * 0.55
            + record["competitorUsage"] * 1.0
            + record["ownChannelSignal"] * 0.7
            + record["trendSignal"] * 0.75
            + record["entityStrength"] * 1.15
            + record["longTailBonus"] * 0.35
            - record["genericPenalty"] * 1.0
            - record["saturationPenalty"] * 0.45
            - record["mismatchPenalty"]
            - record["negativePenalty"]
        )
        if 1 <= token_count <= 4:
            value += 7.0
        if record["entityStrength"] >= 12:
            value += 5.0
        return value, "Compact entity-style YouTube tags get compensated so short technical tags can compete with long search phrases."

    if term_type == "hashtag":
        value = (
            record["specificity"] * 0.55
            + record["channelFit"] * 0.9
            + record["searchIntent"] * 0.35
            + record["competitorUsage"] * 0.95
            + record["ownChannelSignal"] * 0.45
            + record["trendSignal"] * 0.65
            + record["entityStrength"] * 1.0
            - record["genericPenalty"] * 1.2
            - record["saturationPenalty"] * 0.35
            - record["mismatchPenalty"]
            - record["negativePenalty"]
        )
        if record["term"].startswith("#") and len(record["term"]) <= 16:
            value += 7.0
        if len(record["term"]) > 18:
            value -= 7.0
        if normalized in {"#ai", "#ia", "#tech", "#shorts"}:
            value -= 10.0
        return value, "Hashtags are calibrated for visual cleanliness and recognisable entities, not for maximum phrase length."

    if term_type == "topic_entity":
        value = (
            record["specificity"] * 0.65
            + record["channelFit"] * 1.15
            + record["searchIntent"] * 0.45
            + record["competitorUsage"] * 0.9
            + record["ownChannelSignal"] * 0.7
            + record["trendSignal"] * 0.55
            + record["entityStrength"] * 1.35
            + record["longTailBonus"] * 0.2
            - record["genericPenalty"] * 0.75
            - record["saturationPenalty"] * 0.35
            - record["mismatchPenalty"]
            - record["negativePenalty"]
        )
        if token_count <= 3 and record["entityStrength"] >= 12:
            value += 10.0
        return value, "Strong topic entities are protected from being undervalued just because they are shorter than search phrases."

    if term_type == "broad_tag":
        value = (
            record["specificity"] * 0.35
            + record["channelFit"] * 0.7
            + record["searchIntent"] * 0.25
            + record["competitorUsage"] * 0.8
            + record["ownChannelSignal"] * 0.4
            + record["trendSignal"] * 0.35
            + record["entityStrength"] * 0.35
            - record["genericPenalty"] * 1.1
            - record["saturationPenalty"] * 0.8
            - record["mismatchPenalty"]
            - record["negativePenalty"]
        )
        value -= 6.0
        return value, "Broad tags are intentionally moderated unless they get unusually strong external support."

    return record["rawScore"], "No extra calibration applied."


def calibrated_score(record: dict[str, Any]) -> tuple[int, str]:
    term_type = record["type"]
    base = record["score100"] * 0.45 + record["typeScore100"] * 0.55
    delta_reason = "kept close to the global score."

    if term_type == "topic_entity" and record["entityStrength"] >= 12:
        base += 6.0
        delta_reason = "raised because it is a strong entity and should compete better against long phrases."
    elif term_type == "youtube_tag" and record["entityStrength"] >= 8 and record["channelFit"] >= 11:
        base += 5.0
        delta_reason = "raised because it works well as a compact YouTube tag."
    elif term_type == "hashtag" and record["term"].startswith("#") and len(record["term"]) <= 16:
        base += 4.0
        delta_reason = "raised because it is a clean, usable hashtag format."
    elif term_type == "search_phrase" and "seed_config" in record["sources"] and len(record["sources"]) == 1:
        base -= 4.0
        delta_reason = "trimmed because it is a long search phrase with no external support yet."
    elif term_type == "broad_tag":
        base -= 5.0
        delta_reason = "kept lower because broad tags should not dominate unless evidence is strong."
    elif term_type == "negative_tag":
        base = 1.0
        delta_reason = "forced low because negative tags are only for exclusion."

    calibrated = max(1, min(100, int(round(base))))
    return calibrated, delta_reason


def apply_type_calibration(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        source_count = len(record["sources"])
        type_raw, reason = type_calibration_components(record, source_count)
        record["typeRawScore"] = round(max(1.0, type_raw), 2) if record["type"] != "negative_tag" else 1.0
        record["typeScore100"] = max(1, min(100, int(round(record["typeRawScore"]))))
        record["typeScoreBand"] = score_band(record["typeScore100"])
        record["typeCalibrationReason"] = reason
        grouped[record["type"]].append(record)

    for items in grouped.values():
        items.sort(
            key=lambda record: (
                -record["typeScore100"],
                -record["entityStrength"],
                -record["channelFit"],
                record["term"],
            )
        )
        for index, record in enumerate(items, start=1):
            record["typeRank"] = index
            calibrated, delta_reason = calibrated_score(record)
            record["calibratedScore100"] = calibrated
            record["typeCalibrationReason"] = f"{record['typeCalibrationReason']} Final adjustment: {delta_reason}"

    records.sort(
        key=lambda record: (
            -record["calibratedScore100"],
            -record["typeScore100"],
            -record["score100"],
            record["type"],
            record["term"],
        )
    )
    for index, record in enumerate(records, start=1):
        record["globalRank"] = index
    return records


def update_record_scores(
    records: list[dict[str, Any]],
    signals: dict[str, Any],
    seed_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    generic_penalties = seed_payload.get("genericPenaltyTerms", DEFAULT_GENERIC_PENALTIES)
    negative_terms = seed_payload.get("negativeTerms", DEFAULT_NEGATIVE_TERMS)
    grouped = group_terms_by_seed(records)
    for record in records:
        signal = signals.get(record["normalizedTerm"], {})
        youtube_matches = signal.get("youtubeMatches", [])
        competitor_matches = signal.get("competitorMatches", [])
        analytics_matches = signal.get("analyticsMatches", [])
        search_console_matches = signal.get("searchConsoleMatches", [])

        record["specificity"] = round(compute_specificity(record["term"], record["type"]), 2)
        record["channelFit"] = round(compute_channel_fit(record["term"]), 2)
        record["searchIntent"] = round(compute_search_intent(record["term"], record["type"], analytics_matches, search_console_matches), 2)
        record["competitorUsage"] = round(compute_competitor_usage(competitor_matches), 2)
        record["ownChannelSignal"] = round(compute_own_signal(analytics_matches, search_console_matches), 2)
        record["trendSignal"] = round(compute_trend_signal(youtube_matches), 2)
        record["longTailBonus"] = round(compute_long_tail_bonus(record["term"], record["type"]), 2)
        record["entityStrength"] = round(compute_entity_strength(record["term"], record["type"]), 2)
        record["genericPenalty"] = round(compute_generic_penalty(record["term"], generic_penalties), 2)
        record["saturationPenalty"] = round(compute_saturation_penalty(youtube_matches, record["specificity"]), 2)
        record["mismatchPenalty"] = round(compute_mismatch_penalty(record["term"], negative_terms), 2)
        record["negativePenalty"] = round(compute_negative_penalty(record["term"], negative_terms, record["type"]), 2)

        raw = (
            record["specificity"]
            + record["channelFit"]
            + record["searchIntent"]
            + record["competitorUsage"]
            + record["ownChannelSignal"]
            + record["trendSignal"]
            + record["longTailBonus"]
            + record["entityStrength"]
            - record["genericPenalty"]
            - record["saturationPenalty"]
            - record["mismatchPenalty"]
            - record["negativePenalty"]
        )
        record["rawScore"] = round(raw, 2)
        record["score100"] = max(1, min(100, int(round(raw))))
        record["scoreBand"] = score_band(record["score100"])
        record["sources"] = build_sources_list(record["sources"], youtube_matches, competitor_matches, analytics_matches, search_console_matches)
        record["confidence"] = confidence_from_sources(
            record["sources"],
            record["ownChannelSignal"],
            record["competitorUsage"],
            record["channelFit"],
            record["entityStrength"],
            record["type"],
        )
        record["relatedTerms"] = sorted({item["term"] for item in grouped.get(record["seedGroup"], []) if item["term"] != record["term"]})[:8]
        record["exampleVideos"] = build_example_videos(youtube_matches, competitor_matches)
        record["reason"] = build_reason(record)
        record["notes"] = build_notes(record, search_console_matches)
    return records


def build_sources_list(
    base_sources: list[str],
    youtube_matches: list[dict[str, Any]],
    competitor_matches: list[dict[str, Any]],
    analytics_matches: list[dict[str, Any]],
    search_console_matches: list[dict[str, Any]],
) -> list[str]:
    sources = list(base_sources)
    if youtube_matches:
        sources.append("youtube_data_public")
    if competitor_matches:
        sources.append("competitor_public")
    if analytics_matches:
        sources.append("youtube_analytics")
    if search_console_matches:
        sources.append("search_console")
    deduped = []
    seen = set()
    for item in sources:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def build_example_videos(youtube_matches: list[dict[str, Any]], competitor_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in youtube_matches[:2]:
        examples.append({"title": row["videoTitle"], "url": row["videoUrl"], "source": "youtube_data_public"})
    for row in competitor_matches[:2]:
        examples.append({"title": row["videoTitle"], "url": row["videoUrl"], "source": "competitor_public"})
    return examples[:3]


def build_notes(record: dict[str, Any], search_console_matches: list[dict[str, Any]]) -> str:
    if search_console_matches:
        impressions = sum(item.get("impressions", 0.0) for item in search_console_matches)
        ctr_values = [item.get("ctr", 0.0) for item in search_console_matches if item.get("ctr", 0.0) > 0]
        avg_ctr = sum(ctr_values) / len(ctr_values) if ctr_values else 0.0
        if impressions >= 20 and avg_ctr < 3.0:
            return "Opportunity: impressions exist but CTR is weak."
    if record["type"] == "negative_tag":
        return "Avoid using this term in YouTube tags or visible packaging."
    if record["genericPenalty"] >= 8:
        return "Generic term penalized."
    return ""


def filter_and_sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [record for record in records if record["score100"] >= 1]
    return apply_type_calibration(records)


def build_source_availability(
    seed_path: Path,
    example_used: bool,
    seed_warning: str | None,
    youtube_status: dict[str, Any],
    competitor_status: dict[str, Any],
    analytics_status: dict[str, Any],
    search_console_status: dict[str, Any],
    custom_search_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "seedSource": {
            "path": str(seed_path),
            "available": True,
            "example_seeds_used": example_used,
            "warning": seed_warning or "",
            "blocking": False,
        },
        "youtubeDataPublic": youtube_status,
        "competitorPublic": competitor_status,
        "youtubeAnalyticsOwn": analytics_status,
        "searchConsoleOwn": search_console_status,
        "googleCustomSearch": custom_search_status,
        "pytrends": source_status(False, "skipped", "Not implemented in v1."),
        "autocompleteSuggest": source_status(False, "skipped", "Not implemented in v1."),
    }


def rows_by_type(records: list[dict[str, Any]], term_type: str) -> list[dict[str, Any]]:
    return [record for record in records if record["type"] == term_type]


def top_records(records: list[dict[str, Any]], term_type: str, limit: int = 20) -> list[dict[str, Any]]:
    return rows_by_type(records, term_type)[:limit]


def records_by_priority(records: list[dict[str, Any]], priority: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get("priority") == priority]


def generate_markdown_report(
    report_date: dt.date,
    records: list[dict[str, Any]],
    seed_path: Path,
    availability: dict[str, Any],
    external_sources_used: list[str],
    skipped_sources: list[str],
) -> str:
    top_global = records[:20]
    youtube_tags = top_records(records, "youtube_tag", 15)
    hashtags = top_records(records, "hashtag", 15)
    search_phrases = top_records(records, "search_phrase", 15)
    topic_entities = top_records(records, "topic_entity", 15)
    negatives = [record for record in records if record["type"] == "negative_tag" or record["calibratedScore100"] <= 40][:12]
    generic_penalized = sorted(
        [record for record in records if record["genericPenalty"] >= 8],
        key=lambda record: (-record["genericPenalty"], record["calibratedScore100"], record["term"]),
    )[:20]
    raised = sorted(
        [record for record in records if record["calibratedScore100"] - record["score100"] >= 4],
        key=lambda record: (-(record["calibratedScore100"] - record["score100"]), -record["calibratedScore100"]),
    )[:20]
    lowered = sorted(
        [record for record in records if record["score100"] - record["calibratedScore100"] >= 4],
        key=lambda record: (-(record["score100"] - record["calibratedScore100"]), -record["score100"]),
    )[:20]

    lines = [
        f"# YouTube Tag Intelligence - {report_date.isoformat()}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Total de terminos detectados: {len(records)}",
        f"- YouTube tags: {len(rows_by_type(records, 'youtube_tag'))}",
        f"- Hashtags: {len(rows_by_type(records, 'hashtag'))}",
        f"- Search phrases: {len(rows_by_type(records, 'search_phrase'))}",
        f"- Topic/entities: {len(rows_by_type(records, 'topic_entity'))}",
        f"- Seeds usados desde: `{seed_path}`",
        "",
        "## 2. Fuente de seeds usada.",
        "",
        f"- Archivo: `{seed_path}`",
    ]
    if availability["seedSource"]["example_seeds_used"]:
        lines.append(f"- Aviso: {availability['seedSource']['warning']}")
    else:
        lines.append("- Se usaron seeds locales reales.")
    lines.extend([
        "",
        "## 3. Fuentes usadas.",
        "",
    ])
    if external_sources_used:
        for item in external_sources_used:
            lines.append(f"- {item}")
    else:
        lines.append("- Solo seeds locales de ejemplo o locales reales.")
    lines.extend([
        "",
        "## 4. Fuentes no disponibles y motivo.",
        "",
    ])
    for label, payload in availability.items():
        if label == "seedSource":
            continue
        if payload["mode"] in {"used", "available_not_used"}:
            continue
        lines.append(f"- {label}: {payload['reason']}")
    lines.extend([
        "",
        "## 5. Top global calibrado.",
        "",
    ])
    lines.extend(render_term_list(top_global, calibrated=True))
    lines.extend([
        "",
        "## 6. Top YouTube tags calibrados.",
        "",
    ])
    lines.extend(render_term_list(youtube_tags, calibrated=True))
    lines.extend([
        "",
        "## 7. Top hashtags calibrados.",
        "",
    ])
    lines.extend(render_term_list(hashtags, calibrated=True))
    lines.extend([
        "",
        "## 8. Top search phrases calibradas.",
        "",
    ])
    lines.extend(render_term_list(search_phrases, calibrated=True))
    lines.extend([
        "",
        "## 9. Top topic/entities calibradas.",
        "",
    ])
    lines.extend(render_term_list(topic_entities, calibrated=True))
    lines.extend([
        "",
        "## 10. Comparacion antes/despues de calibracion.",
        "",
    ])
    for record in top_global[:12]:
        lines.append(
            f"- **{record['term']}** | `{record['type']}` | antes {record['score100']} | type {record['typeScore100']} | final {record['calibratedScore100']} | {record['typeCalibrationReason']}"
        )
    lines.extend([
        "",
        "## 11. Terminos que subieron por calibracion de tipo.",
        "",
    ])
    lines.extend(render_term_list(raised, calibrated=True) if raised else ["- No hubo subidas claras por calibracion en esta pasada."])
    lines.extend([
        "",
        "## 12. Terminos que bajaron por calibracion de tipo.",
        "",
    ])
    lines.extend(render_term_list(lowered, calibrated=True) if lowered else ["- No hubo bajadas claras por calibracion en esta pasada."])
    lines.extend([
        "",
        "## 13. Terminos demasiado genericos penalizados.",
        "",
    ])
    lines.extend(render_term_list(generic_penalized, calibrated=True))
    lines.extend([
        "",
        "## 14. Negative tags.",
        "",
    ])
    lines.extend(render_term_list([record for record in records if record["type"] == "negative_tag"], calibrated=True))
    lines.extend([
        "",
        "## 15. Limitaciones reales.",
        "",
    ])
    for item in skipped_sources:
        lines.append(f"- {item}")
    lines.extend([
        "- No se inventan volumenes ni datos de herramientas externas como vidIQ o TubeBuddy.",
        "- Las recomendaciones de tags siguen necesitando revision humana antes de usarse en un flujo futuro.",
        "- Este flujo no modifica YouTube ni escribe tags reales en videos.",
        "",
        "## 16. Como usar estos datos en futuros workflows.",
        "",
        "- Reutilizar `youtube_tag` en futuros flujos de empaquetado o apoyo de descripcion.",
        "- Reutilizar `hashtag` para piezas visibles o shorts cuando tenga sentido.",
        "- Reutilizar `search_phrase` como apoyo de descripcion, articulo o expansion SEO.",
        "- Reutilizar `topic_entity` para clasificacion editorial y prompts.",
        "- Reutilizar `negative_tag` como lista de exclusion.",
    ])
    return "\n".join(lines) + "\n"


def render_term_list(records: list[dict[str, Any]], calibrated: bool = False) -> list[str]:
    if not records:
        return ["- No hay terminos suficientes para esta seccion."]
    lines: list[str] = []
    for record in records:
        if calibrated:
            lines.append(
                f"- **{record['term']}** | `{record['type']}` | calibrated {record['calibratedScore100']} | anterior {record['score100']} | "
                f"type {record['typeScore100']} | fuentes {', '.join(record['sources'])} | uso `{record['recommendedUsage']}` | "
                f"confianza `{record['confidence']}` | motivo: {record['reason']} | calibracion: {record['typeCalibrationReason']}"
            )
        else:
            lines.append(
                f"- **{record['term']}** | `{record['type']}` | score100 {record['score100']} | raw {record['rawScore']} | "
                f"fuentes {', '.join(record['sources'])} | uso `{record['recommendedUsage']}` | confianza `{record['confidence']}` | motivo: {record['reason']}"
            )
    return lines


def export_type_rows(records: list[dict[str, Any]], allowed_types: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if record["type"] not in allowed_types:
            continue
        rows.append(
            {
                "term": record["term"],
                "normalizedTerm": record["normalizedTerm"],
                "type": record["type"],
                "rawScore": record["rawScore"],
                "score100": record["score100"],
                "scoreBand": record["scoreBand"],
                "typeRawScore": record["typeRawScore"],
                "typeScore100": record["typeScore100"],
                "calibratedScore100": record["calibratedScore100"],
                "typeRank": record["typeRank"],
                "globalRank": record["globalRank"],
                "typeScoreBand": record["typeScoreBand"],
                "typeCalibrationReason": record["typeCalibrationReason"],
                "specificity": record["specificity"],
                "channelFit": record["channelFit"],
                "searchIntent": record["searchIntent"],
                "competitorUsage": record["competitorUsage"],
                "ownChannelSignal": record["ownChannelSignal"],
                "trendSignal": record["trendSignal"],
                "longTailBonus": record["longTailBonus"],
                "entityStrength": record["entityStrength"],
                "genericPenalty": record["genericPenalty"],
                "saturationPenalty": record["saturationPenalty"],
                "mismatchPenalty": record["mismatchPenalty"],
                "negativePenalty": record["negativePenalty"],
                "sources": ",".join(record["sources"]),
                "recommendedUsage": record["recommendedUsage"],
                "confidence": record["confidence"],
                "reason": record["reason"],
                "seedGroup": record["seedGroup"],
                "language": record["language"],
                "region": record["region"],
                "relatedTerms": ", ".join(record["relatedTerms"]),
                "notes": record["notes"],
            }
        )
    return rows


def build_external_source_lists(availability: dict[str, Any]) -> tuple[list[str], list[str]]:
    used = []
    skipped = []
    mapping = {
        "youtubeDataPublic": "YouTube Data API v3 public search/read endpoints",
        "competitorPublic": "Curated competitor public videos",
        "youtubeAnalyticsOwn": "YouTube Analytics own search terms",
        "searchConsoleOwn": "Search Console real queries",
        "googleCustomSearch": "Google Custom Search",
        "pytrends": "Pytrends / Google Trends",
        "autocompleteSuggest": "Autocomplete / Suggest",
    }
    for key, label in mapping.items():
        payload = availability[key]
        if payload["mode"] in {"used", "available_not_used"} and payload["available"]:
            used.append(label if payload["mode"] == "used" else f"{label} (available but not used)")
        else:
            skipped.append(f"{label}: {payload['reason']}")
    return used, skipped


def run_youtube_tag_intelligence(report_date: dt.date | None = None, seed_filter: str | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    current_date = report_date or dt.date.today()
    seed_payload, seed_path, example_used, seed_warning = load_seed_config(seed_filter)
    generated_records = build_generated_terms(seed_payload)

    youtube_api_key, youtube_connection_note = get_youtube_data_api_key()
    seed_queries = build_seed_queries(seed_payload)
    youtube_public_rows, youtube_status = youtube_public_search(seed_queries, youtube_api_key)
    if not youtube_status["available"] and youtube_connection_note:
        youtube_status["reason"] = youtube_connection_note

    competitors, competitor_reason = load_competitors_local()
    competitor_rows, competitor_status = fetch_competitor_public_videos(youtube_api_key, competitors)
    if not competitor_status["available"] and competitor_reason:
        competitor_status["reason"] = competitor_reason

    analytics_rows, analytics_status = try_analytics_search_terms(current_date)
    search_console_rows, search_console_status = try_search_console_queries(current_date)
    custom_search_status = try_custom_search_status()

    signals = build_signal_maps(generated_records, youtube_public_rows, competitor_rows, analytics_rows, search_console_rows)
    scored_records = filter_and_sort_records(update_record_scores(generated_records, signals, seed_payload))

    availability = build_source_availability(
        seed_path,
        example_used,
        seed_warning,
        youtube_status,
        competitor_status,
        analytics_status,
        search_console_status,
        custom_search_status,
    )
    external_sources_used, skipped_sources = build_external_source_lists(availability)

    stamp = current_date.isoformat()
    report_path = REPORTS_DIR / f"youtube_tag_intelligence_{stamp}.md"
    json_path = DATA_DIR / f"youtube_tag_intelligence_{stamp}.json"
    tags_csv_path = DATA_DIR / f"tag_scores_{stamp}.csv"
    hashtags_csv_path = DATA_DIR / f"hashtag_scores_{stamp}.csv"
    phrases_csv_path = DATA_DIR / f"search_phrase_scores_{stamp}.csv"
    entities_csv_path = DATA_DIR / f"topic_entity_scores_{stamp}.csv"
    calibrated_global_csv_path = DATA_DIR / f"calibrated_global_scores_{stamp}.csv"
    availability_path = DATA_DIR / f"source_availability_{stamp}.json"

    payload = {
        "reportDate": stamp,
        "seedSourcePath": str(seed_path),
        "sourceAvailability": availability,
        "records": scored_records,
        "youtubePublicRows": youtube_public_rows,
        "competitorRows": competitor_rows,
        "analyticsRows": analytics_rows,
        "searchConsoleRows": search_console_rows,
        "seedFilter": seed_filter,
    }
    save_json(json_path, payload)
    save_csv(tags_csv_path, export_type_rows(scored_records, {"youtube_tag", "broad_tag", "negative_tag"}))
    save_csv(hashtags_csv_path, export_type_rows(scored_records, {"hashtag"}))
    save_csv(phrases_csv_path, export_type_rows(scored_records, {"search_phrase"}))
    save_csv(entities_csv_path, export_type_rows(scored_records, {"topic_entity"}))
    save_csv(
        calibrated_global_csv_path,
        export_type_rows(scored_records, {"youtube_tag", "hashtag", "search_phrase", "topic_entity", "broad_tag", "negative_tag"}),
    )
    save_json(availability_path, availability)
    report_path.write_text(
        generate_markdown_report(current_date, scored_records, seed_path, availability, external_sources_used, skipped_sources),
        encoding="utf-8",
    )

    return {
        "report": report_path,
        "json": json_path,
        "tag_csv": tags_csv_path,
        "hashtag_csv": hashtags_csv_path,
        "search_phrase_csv": phrases_csv_path,
        "topic_entity_csv": entities_csv_path,
        "calibrated_global_csv": calibrated_global_csv_path,
        "availability_json": availability_path,
    }
