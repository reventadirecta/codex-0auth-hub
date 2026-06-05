import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .config import read_api_key
from .registry import get_connection
from .youtube_api import _youtube_data_api_get
from .paths import ROOT


REPORTS_DIR = ROOT / "reports"
DISCOVERY_DATA_DIR = ROOT / "data" / "competitor_discovery"
CANDIDATES_DATA_DIR = ROOT / "data" / "video_rewrite_candidates"
CONFIG_DIR = ROOT / "config"

BASE_SEARCH_QUERIES = [
    "Ollama local AI",
    "Hermes Agent Ollama",
    "Codex autonomous agent",
    "ComfyUI video workflow",
    "AI image generation local",
    "GPU for local AI",
    "AI agents tutorial",
    "YouTube automation AI agents",
    "OpenClaw local AI",
    "Agent Zero tutorial",
]

OWN_CHANNEL_EXCLUSIONS = {
    "UCMojQf8oSyk_UwsFwi_EwvA": {
        "label": "Ando en la Nube",
        "reason": "Canal propio/de prueba de la misma cuenta. No usar como competidor ni referencia externa.",
    }
}

TOPIC_PATTERNS = {
    "ia_local": [r"\bollama\b", r"\blocal\b", r"\bqwen\b", r"\bmistral\b", r"\bllm\b", r"\bopenclaw\b"],
    "agentes_autonomos": [r"\bagent\b", r"\bagents\b", r"\bhermes\b", r"\bcodex\b", r"\bautonomous\b", r"\bagente\b"],
    "comfyui_video": [r"\bcomfyui\b", r"\brunway\b", r"\bflux\b", r"\bvideo\b", r"\bimage\b", r"\bimagen\b"],
    "hardware_ia_gpu": [r"\bgpu\b", r"\bvram\b", r"\brtx\b", r"\bcuda\b", r"\bhardware\b", r"\btarjeta\b", r"\bgr[áa]fica\b"],
    "ia_tutorial": [r"\btutorial\b", r"\bgu[ií]a\b", r"\bhow to\b", r"\bpaso a paso\b", r"\bsetup\b", r"\bconfigura\b"],
    "video_ai": [r"\baivideo\b", r"\bvideo ai\b", r"\bgenerative\b", r"\bgeneration\b", r"\bimagen ai\b"],
    "legacy_gaming": [r"\btarkov\b", r"\bgaming\b", r"\bgameplay\b", r"\bdragon ball\b", r"\banime\b"],
}

SPANISH_MARKERS = {"como", "guia", "gratis", "minutos", "tarjetas", "graficas", "sin", "local", "para", "con"}
ENGLISH_MARKERS = {"how", "guide", "free", "setup", "workflow", "local", "with", "tutorial", "best"}


def ensure_output_dirs() -> None:
    DISCOVERY_DATA_DIR.mkdir(parents=True, exist_ok=True)
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
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9áéíóúñ\-\+]+", normalize_text(text)))


def load_candidates_payload(report_date: dt.date | None = None) -> tuple[dict[str, Any], Path]:
    if report_date:
        path = CANDIDATES_DATA_DIR / f"video_rewrite_candidates_{report_date.isoformat()}.json"
        if not path.exists():
            raise FileNotFoundError(f"Candidates JSON not found for {report_date.isoformat()}: {path}")
        return json.loads(path.read_text(encoding="utf-8")), path

    candidates = sorted(CANDIDATES_DATA_DIR.glob("video_rewrite_candidates_*.json"))
    if not candidates:
        raise FileNotFoundError("No video_rewrite_candidates JSON files found in data/video_rewrite_candidates.")
    path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8")), path


def get_public_youtube_api_key(connection_id: str | None = None) -> str:
    _config, _account, _service, entry = get_connection("youtube_data", connection_id)
    return read_api_key(entry["apiKeyFile"])


def get_own_channel_id(connection_id: str | None = None) -> str | None:
    _config, _account, _service, entry = get_connection("youtube_data", connection_id)
    return entry.get("channelId")


def search_videos_public(query: str, api_key: str, max_results: int = 10) -> list[dict[str, Any]]:
    published_after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)).isoformat().replace("+00:00", "Z")
    data = _youtube_data_api_get(
        "search",
        {
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": "date",
            "maxResults": max_results,
            "publishedAfter": published_after,
            "relevanceLanguage": "es",
        },
        api_key,
    )
    return data.get("items", [])


def get_channels_public(channel_ids: list[str], api_key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for start in range(0, len(channel_ids), 50):
        chunk = channel_ids[start : start + 50]
        data = _youtube_data_api_get(
            "channels",
            {
                "id": ",".join(chunk),
                "part": "snippet,statistics,brandingSettings",
                "maxResults": len(chunk),
            },
            api_key,
        )
        items.extend(data.get("items", []))
    return items


def candidate_tokens(candidate: dict[str, Any]) -> set[str]:
    return tokenize(candidate["title"]) | tokenize(candidate["editorialCategory"])


def derive_query_from_candidate(candidate: dict[str, Any]) -> list[str]:
    title = normalize_text(candidate["title"])
    category = candidate["editorialCategory"]
    queries: list[str] = []

    if "ollama" in title:
        queries.append("Ollama local AI tutorial")
    if "hermes" in title:
        queries.append("Hermes Agent Ollama tutorial")
    if "codex" in title:
        queries.append("Codex autonomous agent workflow")
    if "comfy" in title or category == "comfyui_video":
        queries.append("ComfyUI video workflow tutorial")
    if "mistral" in title or "qwen" in title:
        queries.append("Mistral local AI tutorial")
    if "gpu" in title or "tarjetas" in title or category == "hardware_ia_gpu":
        queries.append("GPU for local AI tutorial")
    if category == "ia_local":
        queries.append("local AI models tutorial")
    if category == "agentes_autonomos":
        queries.append("AI agents tutorial")
    if category == "ia_tutorial":
        queries.append("AI tutorial automation")
    if category == "codex_automatizacion":
        queries.append("autonomous coding agent tutorial")

    cleaned_words = [word for word in re.findall(r"[a-z0-9áéíóúñ]+", title) if len(word) > 3]
    if cleaned_words:
        queries.append(" ".join(cleaned_words[:4]))
    return queries


def build_search_queries(candidates_payload: dict[str, Any]) -> list[dict[str, Any]]:
    priority_a = [item for item in candidates_payload["candidates"] if item["priority"] == "A"]
    priority_a.sort(key=lambda item: item["score"], reverse=True)
    selected = priority_a[:15]

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for query in BASE_SEARCH_QUERIES:
        key = normalize_text(query)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"query": query, "source": "base_strategy", "candidateTitle": "", "priority": "A"})

    for candidate in selected:
        for query in derive_query_from_candidate(candidate):
            key = normalize_text(query)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "query": query,
                    "source": "candidate",
                    "candidateTitle": candidate["title"],
                    "priority": candidate["priority"],
                }
            )
    return rows


def detect_topics(*texts: str) -> list[str]:
    merged = " ".join(normalize_text(text) for text in texts)
    topics: list[str] = []
    for topic, patterns in TOPIC_PATTERNS.items():
        if any(re.search(pattern, merged) for pattern in patterns):
            topics.append(topic)
    return topics


def infer_language(*texts: str) -> str:
    words = tokenize(" ".join(texts))
    es_hits = len(words & SPANISH_MARKERS)
    en_hits = len(words & ENGLISH_MARKERS)
    if es_hits > en_hits:
        return "es"
    if en_hits > es_hits:
        return "en"
    return "mixed"


def classify_channel(
    topics: list[str],
    title: str,
    description: str,
    recent_video_titles: list[str],
    appearances: int,
    overlap: int,
) -> tuple[str, str]:
    merged = " ".join([title, description, *recent_video_titles]).lower()
    strategic_hits = len([topic for topic in topics if topic in {"ia_local", "agentes_autonomos", "comfyui_video", "hardware_ia_gpu", "ia_tutorial", "video_ai"}])
    viral_hits = len([topic for topic in topics if topic in {"video_ai"}]) + (1 if "shorts" in merged else 0)
    legacy_hits = len([topic for topic in topics if topic == "legacy_gaming"]) + (1 if "gaming" in merged or "tarkov" in merged else 0)
    tutorial_signal = any(token in merged for token in ["tutorial", "guia", "guide", "how to", "paso a paso", "setup"])

    if strategic_hits >= 2 and tutorial_signal and (appearances >= 2 or overlap >= 2):
        return "direct_competitor", "A"
    if strategic_hits >= 2 and appearances >= 2:
        return "reference_channel", "A"
    if strategic_hits >= 1 and tutorial_signal:
        return "reference_channel", "B"
    if viral_hits >= 1 and legacy_hits == 0 and appearances >= 2:
        return "viral_format_source", "B"
    if legacy_hits >= 1:
        return "weak_match", "C"
    return "weak_match", "B"


def confidence_level(appearances: int, queries: int, classification: str) -> str:
    if classification in {"direct_competitor", "reference_channel"} and appearances >= 3 and queries >= 2:
        return "alta"
    if appearances >= 2:
        return "media"
    return "baja"


def build_public_signal(channel: dict[str, Any], matched_videos: list[dict[str, Any]]) -> str:
    stats = channel.get("statistics", {})
    subs = stats.get("subscriberCount", "hidden")
    videos = len(matched_videos)
    last_date = max((item.get("publishedAt", "") for item in matched_videos), default="")
    return f"{videos} videos recientes encontrados; subscribers={subs}; ultima actividad observada={last_date or 'desconocida'}"


def summarize_reason(classification: str, topics: list[str], matched_queries: list[str], matched_videos: list[dict[str, Any]]) -> str:
    topic_text = ", ".join(topics[:4]) if topics else "sin tema dominante claro"
    query_text = ", ".join(matched_queries[:3])
    video_titles = ", ".join(item["title"] for item in matched_videos[:2])
    if classification == "direct_competitor":
        return f"Aparece repetidamente en consultas estratégicas ({query_text}) y publica sobre {topic_text}. Videos observados: {video_titles}."
    if classification == "reference_channel":
        return f"Cubre temas cercanos al nuevo rumbo ({topic_text}) y apareció en búsquedas útiles como {query_text}. Videos observados: {video_titles}."
    if classification == "viral_format_source":
        return f"Aparece por formatos compatibles y señales públicas de video/shorts sobre {topic_text}. Videos observados: {video_titles}."
    if classification == "weak_match":
        return f"Relacionado de forma parcial con {topic_text}, pero con menor cercanía estratégica. Videos observados: {video_titles}."
    return "Ruido de búsqueda con poca relación editorial."


def build_suggested_local_json(channels: list[dict[str, Any]]) -> dict[str, Any]:
    suggested = []
    for item in channels:
        if item["channelId"] in OWN_CHANNEL_EXCLUSIONS:
            continue
        if item["classification"] not in {"direct_competitor", "reference_channel", "viral_format_source"}:
            continue
        if item["priority"] == "C":
            continue
        suggested.append(
            {
                "id": f"suggested-{item['channelId'][-8:].lower()}",
                "label": item["channelTitle"],
                "channelId": item["channelId"],
                "channelUrl": item["channelUrl"],
                "classification": item["classification"],
                "priority": item["priority"],
                "topics": item["topics"],
                "notes": item["recommendationReason"],
            }
        )
    return {"competitors": suggested}


def build_competitors_example() -> dict[str, Any]:
    return {
        "competitors": [
            {
                "id": "example-ai-local-channel",
                "label": "Example Local AI Channel",
                "channelId": "UCxxxxxxxxxxxxxxxxxxxxxx",
                "channelUrl": "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
                "classification": "direct_competitor",
                "priority": "A",
                "topics": ["ia_local", "agentes_autonomos"],
                "notes": "Example structure only. Copy real channels manually from competitor_discovery output.",
            }
        ]
    }


def discover_competitors(candidates_payload: dict[str, Any], api_key: str, own_channel_id: str | None = None) -> dict[str, Any]:
    queries = build_search_queries(candidates_payload)
    channel_hits: dict[str, dict[str, Any]] = {}

    for query_row in queries:
        results = search_videos_public(query_row["query"], api_key)
        for item in results:
            snippet = item.get("snippet", {})
            channel_id = snippet.get("channelId")
            video_id = item.get("id", {}).get("videoId")
            if not channel_id or not video_id:
                continue
            if own_channel_id and channel_id == own_channel_id:
                continue
            hit = channel_hits.setdefault(
                channel_id,
                {
                    "channelId": channel_id,
                    "channelTitle": snippet.get("channelTitle", ""),
                    "channelDescription": "",
                    "channelUrl": f"https://www.youtube.com/channel/{channel_id}",
                    "matchedQueries": set(),
                    "matchedVideos": [],
                    "topicCounter": Counter(),
                    "querySources": set(),
                },
            )
            hit["matchedQueries"].add(query_row["query"])
            hit["querySources"].add(query_row["source"])
            hit["matchedVideos"].append(
                {
                    "videoId": video_id,
                    "title": snippet.get("title", ""),
                    "publishedAt": snippet.get("publishedAt", ""),
                    "description": snippet.get("description", ""),
                    "query": query_row["query"],
                }
            )
            for topic in detect_topics(snippet.get("title", ""), snippet.get("description", ""), query_row["query"]):
                hit["topicCounter"][topic] += 1

    channel_ids = list(channel_hits.keys())
    channel_items = get_channels_public(channel_ids, api_key) if channel_ids else []
    channel_lookup = {item.get("id"): item for item in channel_items}

    candidates_tokens = set()
    for item in candidates_payload["candidates"]:
        if item["priority"] == "A":
            candidates_tokens |= candidate_tokens(item)

    ranked_channels: list[dict[str, Any]] = []
    for channel_id, entry in channel_hits.items():
        channel = channel_lookup.get(channel_id, {})
        snippet = channel.get("snippet", {})
        branding = channel.get("brandingSettings", {}).get("channel", {})
        stats = channel.get("statistics", {})
        matched_videos = sorted(entry["matchedVideos"], key=lambda item: item["publishedAt"], reverse=True)
        topics = list(entry["topicCounter"].keys())
        if not topics:
            topics = detect_topics(snippet.get("title", ""), snippet.get("description", ""), branding.get("description", ""))

        merged_text = " ".join([snippet.get("title", ""), snippet.get("description", ""), branding.get("description", "")] + [item["title"] for item in matched_videos])
        overlap = len(tokenize(merged_text) & candidates_tokens)
        appearances = len(matched_videos)
        query_count = len(entry["matchedQueries"])
        tutorial_count = sum(
            1 for item in matched_videos
            if any(token in normalize_text(item["title"]) for token in ["tutorial", "guia", "guide", "setup", "how to", "paso a paso"])
        )
        classification, priority = classify_channel(
            topics,
            snippet.get("title", ""),
            branding.get("description", ""),
            [item["title"] for item in matched_videos[:6]],
            appearances,
            overlap,
        )

        excluded_info = OWN_CHANNEL_EXCLUSIONS.get(channel_id)
        if excluded_info:
            classification = "excluded_own_channel"
            priority = "C"

        if classification == "weak_match" and overlap == 0 and appearances == 1:
            classification = "ignore"

        if classification == "ignore":
            priority = "C"

        recommendation_reason = (
            excluded_info["reason"]
            if excluded_info
            else summarize_reason(classification, topics, sorted(entry["matchedQueries"]), matched_videos)
        )

        ranked_channels.append(
            {
                "channelTitle": snippet.get("title", entry["channelTitle"]),
                "channelId": channel_id,
                "channelUrl": f"https://www.youtube.com/channel/{channel_id}",
                "classification": classification,
                "priority": priority,
                "topics": topics,
                "matchedQueries": sorted(entry["matchedQueries"]),
                "matchedVideos": matched_videos[:6],
                "recentActivityDate": matched_videos[0]["publishedAt"] if matched_videos else "",
                "publicSignal": build_public_signal(channel, matched_videos),
                "recommendationReason": recommendation_reason,
                "confidence": confidence_level(appearances, query_count, classification),
                "language": infer_language(snippet.get("title", ""), branding.get("description", ""), *(video["title"] for video in matched_videos[:4])),
                "approxSubscriberCount": stats.get("subscriberCount", "hidden"),
                "matchedQueryCount": query_count,
                "matchedVideoCount": appearances,
                "tutorialVideoCount": tutorial_count,
                "overlapScore": overlap,
            }
        )

    ranked_channels.sort(
        key=lambda item: (
            item["priority"],
            {
                "direct_competitor": 0,
                "reference_channel": 1,
                "viral_format_source": 2,
                "weak_match": 3,
                "ignore": 4,
                "excluded_own_channel": 5,
            }[item["classification"]],
            -item["matchedQueryCount"],
            -item["matchedVideoCount"],
            -item["overlapScore"],
        )
    )
    return {"queries": queries, "channels": ranked_channels}


def _render_channel(channel: dict[str, Any]) -> list[str]:
    matched_video_titles = "; ".join(f"{item['title']} ({item['publishedAt'][:10]})" for item in channel["matchedVideos"][:3])
    return [
        f"- **{channel['channelTitle']}** | `{channel['classification']}` | prioridad `{channel['priority']}` | confianza `{channel['confidence']}`",
        f"  Channel ID: `{channel['channelId']}`",
        f"  URL: {channel['channelUrl']}",
        f"  Temas detectados: {', '.join(channel['topics']) if channel['topics'] else 'sin tema dominante claro'}",
        f"  Consultas donde apareció: {', '.join(channel['matchedQueries'][:5])}",
        f"  Actividad reciente observada: {channel['recentActivityDate'][:10] if channel['recentActivityDate'] else 'desconocida'}",
        f"  Señal pública observada: {channel['publicSignal']}",
        f"  Motivo: {channel['recommendationReason']}",
        f"  Videos que lo hicieron aparecer: {matched_video_titles or 'sin videos destacados guardados'}",
    ]


def generate_markdown_report(report_date: dt.date, candidates_path: Path, result: dict[str, Any], suggested_path: Path) -> str:
    queries = result["queries"]
    channels = result["channels"]
    priority_a = [item for item in channels if item["priority"] == "A" and item["classification"] != "ignore"]
    priority_b = [item for item in channels if item["priority"] == "B" and item["classification"] != "ignore"]
    priority_c = [item for item in channels if item["priority"] == "C" and item["classification"] != "ignore"]
    weak_or_ignore = [item for item in channels if item["classification"] in {"weak_match", "ignore"}]
    recommended = [item for item in channels if item["classification"] in {"direct_competitor", "reference_channel", "viral_format_source"} and item["priority"] != "C"][:12]

    lines = [
        f"# Competitor Discovery - {report_date.isoformat()}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Fuente de candidatos usada: `{candidates_path}`",
        f"- Consultas generadas: {len(queries)}",
        f"- Canales encontrados: {len(channels)}",
        f"- Canales prioridad A: {len(priority_a)}",
        f"- Canales prioridad B: {len(priority_b)}",
        f"- Canales prioridad C: {len(priority_c)}",
        "",
        "## 2. Fuente de candidatos usada.",
        "",
        f"- Archivo principal: `{candidates_path}`",
        "- Este flujo toma como entrada principal los candidatos de `video_rewrite_candidates` y busca canales publicos relacionados en YouTube Data API v3.",
        "",
        "## 3. Consultas generadas.",
        "",
    ]
    for row in queries:
        source_text = row["source"] if row["source"] != "candidate" else f"candidate: {row['candidateTitle']}"
        lines.append(f"- `{row['query']}` | fuente: {source_text}")
    lines.append("")

    lines.append("## 4. Canales encontrados.")
    lines.append("")
    for item in channels[:15]:
        lines.extend(_render_channel(item))
    lines.append("")

    lines.append("## 5. Canales prioridad A.")
    lines.append("")
    for item in priority_a[:12]:
        lines.extend(_render_channel(item))
    lines.append("")

    lines.append("## 6. Canales prioridad B.")
    lines.append("")
    for item in priority_b[:10]:
        lines.extend(_render_channel(item))
    lines.append("")

    lines.append("## 7. Canales prioridad C.")
    lines.append("")
    for item in priority_c[:10]:
        lines.extend(_render_channel(item))
    lines.append("")

    lines.append("## 8. Canales descartados o débiles.")
    lines.append("")
    for item in weak_or_ignore[:12]:
        lines.extend(_render_channel(item))
    lines.append("")

    lines.append("## 9. Por qué cada canal parece competidor o referencia.")
    lines.append("")
    for item in recommended:
        lines.append(f"- **{item['channelTitle']}**: {item['recommendationReason']}")
    lines.append("")

    lines.append("## 10. Qué temas cubre cada canal.")
    lines.append("")
    for item in recommended:
        lines.append(f"- **{item['channelTitle']}** -> {', '.join(item['topics']) if item['topics'] else 'sin tema dominante claro'}")
    lines.append("")

    lines.append("## 11. Qué vídeos recientes hicieron que apareciera.")
    lines.append("")
    for item in recommended:
        video_list = "; ".join(video["title"] for video in item["matchedVideos"][:3])
        lines.append(f"- **{item['channelTitle']}** -> {video_list}")
    lines.append("")

    lines.append("## 12. Recomendación de qué canales meter en competitors.local.json.")
    lines.append("")
    lines.append(f"- Sugerencia local generada en: `{suggested_path}`")
    for item in recommended:
        lines.append(f"- **{item['channelTitle']}** | `{item['classification']}` | prioridad `{item['priority']}` | confianza `{item['confidence']}`")
    lines.append("")

    lines.append("## 13. Limitaciones del análisis.")
    lines.append("")
    lines.append("- Solo se han usado datos publicos de YouTube Data API v3.")
    lines.append("- No se han usado metricas privadas de canales ajenos.")
    lines.append("- Este flujo descubre y prioriza canales; no hace aun un escaneo profundo de contenido competidor.")
    lines.append("- No se ha usado Google Custom Search.")
    lines.append("- No se ha tocado el canal propio ni se ha publicado nada.")
    return "\n".join(lines) + "\n"


def export_channels_csv_rows(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in channels:
        rows.append(
            {
                "channelTitle": item["channelTitle"],
                "channelId": item["channelId"],
                "channelUrl": item["channelUrl"],
                "classification": item["classification"],
                "priority": item["priority"],
                "confidence": item["confidence"],
                "topics": ",".join(item["topics"]),
                "matchedQueryCount": item["matchedQueryCount"],
                "matchedVideoCount": item["matchedVideoCount"],
                "recentActivityDate": item["recentActivityDate"],
                "approxSubscriberCount": item["approxSubscriberCount"],
            }
        )
    return rows


def run_competitor_discovery(report_date: dt.date | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    candidates_payload, candidates_path = load_candidates_payload(report_date)
    api_key = get_public_youtube_api_key()
    own_channel_id = get_own_channel_id()
    result = discover_competitors(candidates_payload, api_key, own_channel_id)

    resolved_date = report_date or dt.date.fromisoformat(candidates_payload["reportDate"])
    stamp = resolved_date.isoformat()
    report_path = REPORTS_DIR / f"competitor_discovery_{stamp}.md"
    json_path = DISCOVERY_DATA_DIR / f"competitor_discovery_{stamp}.json"
    channels_csv_path = DISCOVERY_DATA_DIR / f"discovered_channels_{stamp}.csv"
    queries_csv_path = DISCOVERY_DATA_DIR / f"search_queries_{stamp}.csv"
    suggested_path = DISCOVERY_DATA_DIR / "suggested_competitors.local.example.json"
    config_example_path = CONFIG_DIR / "competitors.example.json"

    payload = {
        "reportDate": stamp,
        "sourceCandidatesJson": str(candidates_path),
        "queries": result["queries"],
        "channels": result["channels"],
    }
    save_json(json_path, payload)
    save_csv(channels_csv_path, export_channels_csv_rows(result["channels"]))
    save_csv(queries_csv_path, result["queries"])
    save_json(suggested_path, build_suggested_local_json(result["channels"]))
    save_json(config_example_path, build_competitors_example())
    report_path.write_text(generate_markdown_report(resolved_date, candidates_path, result, suggested_path), encoding="utf-8")

    return {
        "report": report_path,
        "json": json_path,
        "channels_csv": channels_csv_path,
        "queries_csv": queries_csv_path,
        "suggested_json": suggested_path,
        "config_example": config_example_path,
    }
