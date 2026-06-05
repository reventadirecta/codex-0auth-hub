import csv
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .config import read_api_key
from .registry import get_connection
from .youtube_api import _youtube_data_api_get
from .paths import ROOT


REPORTS_DIR = ROOT / "reports"
SCAN_DATA_DIR = ROOT / "data" / "competitor_content_scan"
CANDIDATES_DATA_DIR = ROOT / "data" / "video_rewrite_candidates"
DIAGNOSIS_DATA_DIR = ROOT / "data" / "channel_diagnosis"
OPPORTUNITIES_DATA_DIR = ROOT / "data" / "channel_opportunities"
COMPETITORS_LOCAL_PATH = ROOT / "config" / "competitors.local.json"

SPANISH_STOPWORDS = {
    "a", "al", "algo", "como", "con", "de", "del", "el", "en", "es", "esta", "este", "esto",
    "hay", "la", "las", "lo", "los", "mi", "para", "por", "que", "se", "sin", "sobre", "su",
    "te", "tu", "un", "una", "uno", "y", "the", "this", "that", "your", "from", "into", "with",
}


def ensure_output_dirs() -> None:
    SCAN_DATA_DIR.mkdir(parents=True, exist_ok=True)
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
    return {
        token
        for token in re.findall(r"[a-z0-9áéíóúñ\-\+]+", normalize_text(text))
        if len(token) > 2 and token not in SPANISH_STOPWORDS
    }


def parse_iso8601_duration(value: str) -> int:
    pattern = re.compile(
        r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
    )
    match = pattern.match(value or "")
    if not match:
        return 0
    parts = {key: int(val or 0) for key, val in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def infer_format(title: str, duration_seconds: int) -> str:
    title_norm = normalize_text(title)
    if "#shorts" in title_norm or " short" in f" {title_norm}" or duration_seconds <= 60:
        return "short"
    if duration_seconds >= 600:
        return "long"
    if any(token in title_norm for token in ["tutorial", "guia", "guide", "how to", "setup", "paso a paso"]):
        return "tutorial"
    return "standard"


def infer_intentions(title: str, description: str, editorial_category: str = "", action_type: str = "", fmt: str = "") -> list[str]:
    text = normalize_text(f"{title} {description} {editorial_category} {action_type}")
    intentions: list[str] = []
    if any(token in text for token in ["tutorial", "guia", "guide", "how to", "paso a paso"]):
        intentions.append("tutorial")
    if any(token in text for token in ["instala", "instalar", "configura", "setup", "ubuntu", "ollama install"]):
        intentions.append("instalacion")
    if any(token in text for token in ["vs", "compar", "mejor", "best", "caro", "barato"]):
        intentions.append("comparativa")
    if any(token in text for token in ["review", "merece la pena", "worth", "analisis"]):
        intentions.append("review")
    if any(token in text for token in ["problema", "error", "solucion", "fix", "why"]):
        intentions.append("problema_solucion")
    if any(token in text for token in ["workflow", "caso", "real", "practico", "practical", "use case"]):
        intentions.append("caso_practico")
    if fmt == "short":
        intentions.append("short_viral")
    if editorial_category == "hardware_ia_gpu" or any(token in text for token in ["gpu", "vram", "ram", "hardware"]):
        intentions.append("hardware_ia")
    if editorial_category == "agentes_autonomos" or any(token in text for token in ["agent", "agents", "hermes", "codex"]):
        intentions.append("agentes_autonomos")
    if editorial_category == "comfyui_video" or any(token in text for token in ["comfyui", "runway", "image", "imagen", "video ai", "aivideo"]):
        intentions.append("comfyui_generacion")
    if not intentions:
        intentions.append("caso_practico")
    return list(dict.fromkeys(intentions))


def infer_main_theme(title: str, editorial_category: str, description: str = "") -> str:
    text = normalize_text(f"{title} {description} {editorial_category}")
    if "ollama" in text or editorial_category == "ia_local":
        return "ollama_ia_local"
    if any(token in text for token in ["hermes", "agent", "agents", "codex", "autonomous"]):
        return "agentes_autonomos"
    if "comfyui" in text or editorial_category == "comfyui_video":
        return "comfyui_video_workflow"
    if any(token in text for token in ["gpu", "vram", "ram", "hardware", "tarjetas"]):
        return "hardware_ia_gpu"
    if any(token in text for token in ["mistral", "qwen", "llm", "modelos"]):
        return "modelos_locales"
    return editorial_category or "otros"


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def load_candidates_payload(report_date: dt.date | None = None) -> tuple[dict[str, Any], Path]:
    if report_date:
        path = CANDIDATES_DATA_DIR / f"video_rewrite_candidates_{report_date.isoformat()}.json"
        if not path.exists():
            raise FileNotFoundError(f"Candidates JSON not found for {report_date.isoformat()}: {path}")
        return json.loads(path.read_text(encoding="utf-8")), path

    candidates = sorted(CANDIDATES_DATA_DIR.glob("video_rewrite_candidates_*.json"))
    if not candidates:
        raise FileNotFoundError("No video_rewrite_candidates JSON files found.")
    path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8")), path


def load_competitors_local() -> tuple[dict[str, Any], Path]:
    if not COMPETITORS_LOCAL_PATH.exists():
        raise FileNotFoundError(f"Competitors local config not found: {COMPETITORS_LOCAL_PATH}")
    return json.loads(COMPETITORS_LOCAL_PATH.read_text(encoding="utf-8")), COMPETITORS_LOCAL_PATH


def get_public_youtube_api_key(connection_id: str | None = None) -> str:
    _config, _account, _service, entry = get_connection("youtube_data", connection_id)
    return read_api_key(entry["apiKeyFile"])


def get_channels_catalog(channel_ids: list[str], api_key: str) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for start in range(0, len(channel_ids), 50):
        chunk = channel_ids[start : start + 50]
        data = _youtube_data_api_get(
            "channels",
            {"id": ",".join(chunk), "part": "snippet,contentDetails,statistics", "maxResults": len(chunk)},
            api_key,
        )
        for item in data.get("items", []):
            catalog[item.get("id")] = item
    return catalog


def list_recent_playlist_video_ids(playlist_id: str, api_key: str, max_results: int = 12) -> list[str]:
    video_ids: list[str] = []
    page_token = None
    while len(video_ids) < max_results:
        params: dict[str, Any] = {
            "playlistId": playlist_id,
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


def get_video_details_public(video_ids: list[str], api_key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        data = _youtube_data_api_get(
            "videos",
            {"id": ",".join(chunk), "part": "snippet,contentDetails,statistics", "maxResults": len(chunk)},
            api_key,
        )
        items.extend(data.get("items", []))
    return items


def fetch_competitor_recent_videos(competitors: list[dict[str, Any]], api_key: str, max_per_channel: int = 12) -> list[dict[str, Any]]:
    channel_ids = [item["youtubeChannelId"] for item in competitors]
    channel_catalog = get_channels_catalog(channel_ids, api_key)
    rows: list[dict[str, Any]] = []
    for competitor in competitors:
        channel_id = competitor["youtubeChannelId"]
        channel = channel_catalog.get(channel_id, {})
        uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads_playlist:
            continue
        video_ids = list_recent_playlist_video_ids(uploads_playlist, api_key, max_results=max_per_channel)
        video_items = get_video_details_public(video_ids, api_key)
        for item in video_items:
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            duration_seconds = parse_iso8601_duration(item.get("contentDetails", {}).get("duration", "PT0S"))
            fmt = infer_format(snippet.get("title", ""), duration_seconds)
            rows.append(
                {
                    "competitorId": competitor["id"],
                    "competitorName": competitor["name"],
                    "competitorCategory": competitor["category"],
                    "competitorPriority": competitor["priority"],
                    "channelId": channel_id,
                    "videoId": item.get("id"),
                    "videoTitle": snippet.get("title", ""),
                    "videoUrl": f"https://www.youtube.com/watch?v={item.get('id')}",
                    "publishedAt": snippet.get("publishedAt", ""),
                    "description": snippet.get("description", ""),
                    "durationSeconds": duration_seconds,
                    "format": fmt,
                    "viewsPublic": safe_int(stats.get("viewCount")),
                    "likesPublic": safe_int(stats.get("likeCount")),
                    "commentsPublic": safe_int(stats.get("commentCount")),
                    "thumbnailUrl": (((snippet.get("thumbnails") or {}).get("high") or {}).get("url") or ""),
                    "mainTheme": infer_main_theme(snippet.get("title", ""), competitor["category"], snippet.get("description", "")),
                    "intentions": infer_intentions(snippet.get("title", ""), snippet.get("description", ""), competitor["category"], "", fmt),
                    "tokens": sorted(tokenize(f"{snippet.get('title', '')} {snippet.get('description', '')}")),
                }
            )
    return rows


def enrich_my_candidates(candidates_payload: dict[str, Any]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in candidates_payload["candidates"]:
        if item["priority"] != "A":
            continue
        enriched.append(
            {
                **item,
                "mainTheme": infer_main_theme(item["title"], item["editorialCategory"]),
                "intentions": infer_intentions(
                    item["title"],
                    item.get("metricsReason", ""),
                    item["editorialCategory"],
                    item["recommendedActionType"],
                    item["format"],
                ),
                "tokens": sorted(tokenize(f"{item['title']} {item['editorialCategory']} {item['problemDetected']}")),
            }
        )
    return enriched


def compare_format_label(fmt: str) -> str:
    return {
        "short": "short",
        "tutorial": "tutorial",
        "long": "video_largo",
        "standard": "standard",
    }.get(fmt, fmt or "desconocido")


def similarity_score(my_video: dict[str, Any], competitor_video: dict[str, Any]) -> float:
    my_tokens = set(my_video["tokens"])
    comp_tokens = set(competitor_video["tokens"])
    overlap = len(my_tokens & comp_tokens)
    theme_bonus = 3 if my_video["mainTheme"] == competitor_video["mainTheme"] else 0
    intent_bonus = len(set(my_video["intentions"]) & set(competitor_video["intentions"])) * 2
    format_bonus = 1 if my_video["format"] == competitor_video["format"] else 0
    return overlap + theme_bonus + intent_bonus + format_bonus


def describe_similarity(my_video: dict[str, Any], competitor_video: dict[str, Any]) -> str:
    common_intents = set(my_video["intentions"]) & set(competitor_video["intentions"])
    if my_video["mainTheme"] == competitor_video["mainTheme"] and common_intents:
        return f"Mismo tema base ({my_video['mainTheme']}) y misma intención {', '.join(sorted(common_intents))}."
    if my_video["mainTheme"] == competitor_video["mainTheme"]:
        return f"Mismo tema base ({my_video['mainTheme']})."
    if common_intents:
        return f"Comparten intención {', '.join(sorted(common_intents))}."
    return "Coincidencia parcial por palabras clave y contexto editorial."


def describe_difference(my_video: dict[str, Any], competitor_video: dict[str, Any]) -> str:
    if my_video["format"] != competitor_video["format"]:
        return f"Formato distinto: tu vídeo es {compare_format_label(my_video['format'])} y el competidor es {compare_format_label(competitor_video['format'])}."
    if len(competitor_video["videoTitle"]) > len(my_video["title"]) + 10:
        return "El competidor usa un título más específico y desarrollado."
    if competitor_video["viewsPublic"] > my_video["metrics"]["views30"]:
        return "El competidor tiene más tracción pública visible sobre un tema parecido."
    return "La diferencia principal está en el ángulo y la promesa editorial."


def what_they_do_better(my_video: dict[str, Any], competitor_video: dict[str, Any]) -> str:
    title = normalize_text(competitor_video["videoTitle"])
    if any(token in title for token in ["tutorial", "guide", "guia", "how to", "setup"]):
        return "Título más claro y enfoque tutorial más explícito."
    if competitor_video["format"] == "long" and my_video["format"] == "short":
        return "Desarrollan el tema con más contexto y profundidad."
    if competitor_video["viewsPublic"] > my_video["metrics"]["views30"] * 2:
        return "La promesa parece más fuerte o más buscable por el público."
    return "El ángulo del tema está más aterrizado y resulta más fácil de entender."


def how_to_differentiate(my_video: dict[str, Any], competitor_video: dict[str, Any]) -> str:
    if my_video["mainTheme"] == "agentes_autonomos":
        return "Diferenciarte con caso real en español, coste cero/local y pasos exactos desde tu setup."
    if my_video["mainTheme"] == "comfyui_video_workflow":
        return "Diferenciarte mostrando workflow completo, errores reales y resultado final comparado."
    if my_video["mainTheme"] == "hardware_ia_gpu":
        return "Diferenciarte con números prácticos, presupuesto real y criterio de compra para IA local."
    if my_video["mainTheme"] == "ollama_ia_local":
        return "Diferenciarte con prueba local concreta, límites reales y cuándo usar cloud frente a local."
    return "Diferenciarte con más contexto práctico, ejemplo real y una promesa más específica."


def recommendation_for_rewrite(my_video: dict[str, Any], competitor_video: dict[str, Any]) -> str:
    action = my_video["recommendedActionType"]
    better = what_they_do_better(my_video, competitor_video)
    if action == "cambiar título":
        return f"Reescribir el título para acercarlo a una promesa más concreta. Referencia: {better}"
    if action == "cambiar miniatura":
        return f"Reforzar beneficio visual y resultado final. Referencia: {better}"
    if action == "convertir en vídeo largo":
        return f"Ampliar a tutorial o caso práctico largo y atacar el hueco de profundidad. Referencia: {better}"
    if action == "hacer segunda parte":
        return f"Construir continuación más específica apoyada en lo que el competidor deja implícito. Referencia: {better}"
    return f"Usar la comparación para afinar empaque y enfoque. Referencia: {better}"


def comparison_confidence(score: float, competitor_video: dict[str, Any]) -> str:
    if score >= 8 and competitor_video["viewsPublic"] >= 100:
        return "alta"
    if score >= 5:
        return "media"
    return "baja"


def build_matches(my_candidates: list[dict[str, Any]], competitor_videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for my_video in my_candidates:
        scored = []
        for comp_video in competitor_videos:
            score = similarity_score(my_video, comp_video)
            if score < 4:
                continue
            scored.append((score, comp_video))
        scored.sort(key=lambda item: (item[0], item[1]["viewsPublic"]), reverse=True)
        for score, comp_video in scored[:4]:
            matches.append(
                {
                    "myVideoTitle": my_video["title"],
                    "myVideoUrl": my_video["videoUrl"],
                    "priority": my_video["priority"],
                    "problemDetected": my_video["problemDetected"],
                    "mainTheme": my_video["mainTheme"],
                    "competitor": comp_video["competitorName"],
                    "competitorVideoTitle": comp_video["videoTitle"],
                    "competitorVideoUrl": comp_video["videoUrl"],
                    "competitorVideoDate": comp_video["publishedAt"],
                    "competitorViewsPublic": comp_video["viewsPublic"],
                    "competitorFormat": comp_video["format"],
                    "similarityDetected": describe_similarity(my_video, comp_video),
                    "keyDifference": describe_difference(my_video, comp_video),
                    "theyDoBetter": what_they_do_better(my_video, comp_video),
                    "differentiateBy": how_to_differentiate(my_video, comp_video),
                    "rewriteRecommendation": recommendation_for_rewrite(my_video, comp_video),
                    "confidence": comparison_confidence(score, comp_video),
                    "similarityScore": score,
                }
            )
    matches.sort(key=lambda item: (item["priority"], {"alta": 0, "media": 1, "baja": 2}[item["confidence"]], -item["similarityScore"]))
    return matches


def build_topic_gaps(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in matches:
        grouped.setdefault(item["mainTheme"], []).append(item)
    rows: list[dict[str, Any]] = []
    for theme, theme_matches in grouped.items():
        top = theme_matches[0]
        rows.append(
            {
                "mainTheme": theme,
                "competitorCount": len({item["competitor"] for item in theme_matches}),
                "myVideosAffected": len({item["myVideoTitle"] for item in theme_matches}),
                "commonBetterSignal": top["theyDoBetter"],
                "differentiationAngle": top["differentiateBy"],
                "rewriteNote": top["rewriteRecommendation"],
            }
        )
    rows.sort(key=lambda item: (item["competitorCount"], item["myVideosAffected"]), reverse=True)
    return rows


def _render_match(match: dict[str, Any]) -> list[str]:
    return [
        f"- **Mi vídeo:** {match['myVideoTitle']} | prioridad `{match['priority']}`",
        f"  URL: {match['myVideoUrl']}",
        f"  Problema detectado: {match['problemDetected']}",
        f"  Tema principal: `{match['mainTheme']}`",
        f"  **Competidor:** {match['competitor']}",
        f"  Vídeo competidor: {match['competitorVideoTitle']}",
        f"  URL competidor: {match['competitorVideoUrl']}",
        f"  Fecha: {match['competitorVideoDate'][:10] if match['competitorVideoDate'] else 'desconocida'} | vistas públicas: {match['competitorViewsPublic']} | formato: `{match['competitorFormat']}`",
        f"  Similitud detectada: {match['similarityDetected']}",
        f"  Diferencia clave: {match['keyDifference']}",
        f"  Qué hacen mejor: {match['theyDoBetter']}",
        f"  Qué puedo hacer diferente: {match['differentiateBy']}",
        f"  Recomendación para video_rewrite_proposals: {match['rewriteRecommendation']}",
        f"  Confianza: `{match['confidence']}`",
    ]


def generate_markdown_report(
    report_date: dt.date,
    candidates_path: Path,
    competitors_path: Path,
    diagnosis_path: Path | None,
    opportunities_path: Path | None,
    my_candidates: list[dict[str, Any]],
    competitor_videos: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    topic_gaps: list[dict[str, Any]],
) -> str:
    top_matches = matches[:12]
    unique_competitors = sorted({item["competitor"] for item in matches})
    compared_titles = sorted({item["myVideoTitle"] for item in matches})
    similarity_notes = [f"- **{item['myVideoTitle']}** y **{item['competitorVideoTitle']}**: {item['similarityDetected']}" for item in top_matches[:8]]
    difference_notes = [f"- **{item['myVideoTitle']}**: {item['keyDifference']}" for item in top_matches[:8]]
    better_notes = [f"- **{item['competitor']}**: {item['theyDoBetter']}" for item in top_matches[:8]]
    gap_notes = [
        f"- `{gap['mainTheme']}`: {gap['commonBetterSignal']} | diferenciación: {gap['differentiationAngle']}"
        for gap in topic_gaps[:8]
    ]
    rewrite_notes = [f"- **{item['myVideoTitle']}** -> {item['rewriteRecommendation']}" for item in top_matches[:8]]

    lines = [
        f"# Competitor Content Scan - {report_date.isoformat()}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Fuente de candidatos usada: `{candidates_path}`",
        f"- Competidores analizados: `{competitors_path}`",
        f"- Contexto adicional diagnosis: `{diagnosis_path}`" if diagnosis_path else "- Contexto adicional diagnosis: no disponible",
        f"- Contexto adicional opportunities: `{opportunities_path}`" if opportunities_path else "- Contexto adicional opportunities: no disponible",
        f"- Vídeos míos comparados: {len(my_candidates)}",
        f"- Vídeos competidores cargados: {len(competitor_videos)}",
        f"- Comparaciones útiles generadas: {len(matches)}",
        "",
        "## 2. Fuente de candidatos usada.",
        "",
        f"- Archivo principal: `{candidates_path}`",
        "- Se priorizan los vídeos A de `video_rewrite_candidates` para comparar tema, formato e intención.",
        "",
        "## 3. Competidores analizados.",
        "",
    ]
    for name in sorted({item['competitorName'] for item in competitor_videos}):
        lines.append(f"- {name}")
    lines.append("")
    lines.append("## 4. Vídeos míos prioridad A comparados.")
    lines.append("")
    for item in my_candidates[:12]:
        lines.append(f"- **{item['title']}** | `{item['editorialCategory']}` | acción `{item['recommendedActionType']}` | tema `{item['mainTheme']}`")
    lines.append("")
    lines.append("## 5. Vídeos competidores relacionados.")
    lines.append("")
    for item in top_matches:
        lines.extend(_render_match(item))
    lines.append("")
    lines.append("## 6. Similitudes detectadas.")
    lines.append("")
    lines.extend(similarity_notes or ["- No se detectaron similitudes útiles con suficiente confianza."])
    lines.append("")
    lines.append("## 7. Diferencias importantes.")
    lines.append("")
    lines.extend(difference_notes or ["- No se detectaron diferencias suficientemente claras."])
    lines.append("")
    lines.append("## 8. Qué hace mejor la competencia.")
    lines.append("")
    lines.extend(better_notes or ["- No apareció una ventaja externa clara y repetida."])
    lines.append("")
    lines.append("## 9. Huecos de contenido.")
    lines.append("")
    lines.extend(gap_notes or ["- No se consolidaron huecos temáticos repetidos con la muestra actual."])
    lines.append("")
    lines.append("## 10. Oportunidades para mejorar mis vídeos.")
    lines.append("")
    for item in top_matches[:10]:
        lines.append(f"- **{item['myVideoTitle']}**: {item['differentiateBy']}")
    lines.append("")
    lines.append("## 11. Notas para video_rewrite_proposals.")
    lines.append("")
    lines.extend(rewrite_notes or ["- No se generaron notas accionables suficientes."])
    lines.append("")
    lines.append("## 12. Temas que no merece copiar.")
    lines.append("")
    lines.append("- No conviene copiar tal cual formatos o promesas genéricas de hype si no añaden caso real, contexto local o diferenciación práctica.")
    lines.append("- Tampoco conviene perseguir piezas que solo ganan por shock title sin conexión clara con IA local, agentes, ComfyUI o hardware IA.")
    lines.append("")
    lines.append("## 13. Plan de acción recomendado.")
    lines.append("")
    for item in top_matches[:6]:
        lines.append(f"- **{item['myVideoTitle']}** -> {item['rewriteRecommendation']}")
    lines.append("")
    lines.append("## 14. Limitaciones del análisis.")
    lines.append("")
    lines.append("- Solo se usan datos públicos de competidores: título, descripción, fecha, duración y métricas visibles si YouTube las devuelve.")
    lines.append("- No se usa Analytics de canales ajenos.")
    lines.append("- El matching es editorial y semántico por tokens, tema, intención y formato; no sustituye revisión humana.")
    lines.append("- No se ha usado Google Custom Search.")
    lines.append("- No se ha tocado el canal propio ni se ha modificado ningún vídeo real.")
    return "\n".join(lines) + "\n"


def run_competitor_content_scan(report_date: dt.date | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    candidates_payload, candidates_path = load_candidates_payload(report_date)
    competitors_payload, competitors_path = load_competitors_local()
    api_key = get_public_youtube_api_key()

    my_candidates = enrich_my_candidates(candidates_payload)
    competitors = competitors_payload["competitors"]
    competitor_videos = fetch_competitor_recent_videos(competitors, api_key, max_per_channel=10)
    matches = build_matches(my_candidates, competitor_videos)
    topic_gaps = build_topic_gaps(matches)

    resolved_date = report_date or dt.date.fromisoformat(candidates_payload["reportDate"])
    stamp = resolved_date.isoformat()

    diagnosis_path = DIAGNOSIS_DATA_DIR / f"channel_diagnosis_{stamp}.json"
    opportunities_path = OPPORTUNITIES_DATA_DIR / f"channel_opportunities_{stamp}.json"
    diagnosis_path = diagnosis_path if diagnosis_path.exists() else None
    opportunities_path = opportunities_path if opportunities_path.exists() else None

    report_path = REPORTS_DIR / f"competitor_content_scan_{stamp}.md"
    json_path = SCAN_DATA_DIR / f"competitor_content_scan_{stamp}.json"
    matches_csv_path = SCAN_DATA_DIR / f"competitor_matches_{stamp}.csv"
    gaps_csv_path = SCAN_DATA_DIR / f"topic_gaps_{stamp}.csv"

    payload = {
        "reportDate": stamp,
        "sourceCandidatesJson": str(candidates_path),
        "sourceCompetitorsLocalJson": str(competitors_path),
        "sourceDiagnosisJson": str(diagnosis_path) if diagnosis_path else None,
        "sourceOpportunitiesJson": str(opportunities_path) if opportunities_path else None,
        "myCandidates": my_candidates,
        "competitorVideos": competitor_videos,
        "matches": matches,
        "topicGaps": topic_gaps,
    }
    save_json(json_path, payload)
    save_csv(matches_csv_path, matches)
    save_csv(gaps_csv_path, topic_gaps)
    report_path.write_text(
        generate_markdown_report(
            resolved_date,
            candidates_path,
            competitors_path,
            diagnosis_path,
            opportunities_path,
            my_candidates,
            competitor_videos,
            matches,
            topic_gaps,
        ),
        encoding="utf-8",
    )

    return {"report": report_path, "json": json_path, "matches_csv": matches_csv_path, "gaps_csv": gaps_csv_path}
