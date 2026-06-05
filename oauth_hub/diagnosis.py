import csv
import datetime as dt
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .paths import ROOT
from .youtube_api import analytics_query, get_channel_details, get_video_details, list_upload_video_ids


DATA_DIR = ROOT / "data" / "channel_diagnosis"
REPORTS_DIR = ROOT / "reports"

SPANISH_STOPWORDS = {
    "a", "al", "algo", "como", "con", "de", "del", "el", "en", "es", "esta", "este", "esto",
    "hay", "la", "las", "lo", "los", "mi", "para", "por", "que", "se", "sin", "sobre", "su",
    "te", "tu", "un", "una", "uno", "y",
    "http", "https", "www", "com", "ando", "tv",
}


def ensure_output_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def parse_iso8601_duration(value: str) -> int:
    pattern = re.compile(
        r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
    )
    match = pattern.match(value)
    if not match:
        return 0
    parts = {key: int(val or 0) for key, val in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def infer_format(title: str, duration_seconds: int) -> str:
    normalized = normalize_text(title)
    if "#shorts" in normalized or "shorts" in normalized or duration_seconds <= 60:
        return "short"
    if any(token in normalized for token in ["tutorial", "como ", "cómo ", "guia", "guía", "paso a paso"]):
        return "tutorial"
    if duration_seconds >= 600:
        return "long"
    return "standard"


def infer_topics(title: str, description: str) -> list[str]:
    cleaned_description = re.sub(r"https?://\S+", " ", description.lower())
    combined = f"{title} {cleaned_description}".lower()
    words = re.findall(r"[a-zA-Záéíóúñ0-9]{3,}", combined)
    filtered = [word for word in words if word not in SPANISH_STOPWORDS]
    counts = Counter(filtered)
    return [word for word, _count in counts.most_common(5)]


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def days_since_published(published_at: str, today: dt.date) -> int:
    published_date = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00")).date()
    return max((today - published_date).days, 1)


def analytics_rows_to_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    columns = [item["name"] for item in payload.get("columnHeaders", [])]
    rows = payload.get("rows", [])
    return [dict(zip(columns, row)) for row in rows]


def fetch_all_datasets(today: dt.date) -> dict[str, Any]:
    end_date = today - dt.timedelta(days=1)
    start_30 = end_date - dt.timedelta(days=29)
    start_90 = end_date - dt.timedelta(days=89)

    channel = get_channel_details()
    upload_ids = list_upload_video_ids(max_results=300)
    videos = get_video_details(upload_ids)

    overview_30 = analytics_query(
        start_30,
        end_date,
        metrics=[
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "subscribersGained",
            "subscribersLost",
            "likes",
            "comments",
        ],
    )
    overview_90 = analytics_query(
        start_90,
        end_date,
        metrics=[
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "subscribersGained",
            "subscribersLost",
            "likes",
            "comments",
        ],
    )
    daily_30 = analytics_query(
        start_30,
        end_date,
        metrics=["views", "estimatedMinutesWatched", "averageViewDuration"],
        dimensions=["day"],
        sort=["day"],
        max_results=30,
    )
    daily_90 = analytics_query(
        start_90,
        end_date,
        metrics=["views", "estimatedMinutesWatched", "averageViewDuration"],
        dimensions=["day"],
        sort=["day"],
        max_results=90,
    )
    videos_90 = analytics_query(
        start_90,
        end_date,
        metrics=[
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "likes",
            "comments",
            "subscribersGained",
        ],
        dimensions=["video"],
        sort=["-views"],
        max_results=200,
    )
    videos_30 = analytics_query(
        start_30,
        end_date,
        metrics=[
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "likes",
            "comments",
            "subscribersGained",
        ],
        dimensions=["video"],
        sort=["-views"],
        max_results=200,
    )

    known_video_ids = {item.get("id") for item in videos}
    analytics_video_ids = {
        row.get("video")
        for row in analytics_rows_to_dicts(videos_30) + analytics_rows_to_dicts(videos_90)
        if row.get("video")
    }
    missing_video_ids = sorted(video_id for video_id in analytics_video_ids if video_id not in known_video_ids)
    if missing_video_ids:
        videos.extend(get_video_details(missing_video_ids))

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "periods": {
            "30d": {"start": start_30.isoformat(), "end": end_date.isoformat()},
            "90d": {"start": start_90.isoformat(), "end": end_date.isoformat()},
        },
        "channel": channel,
        "videos_catalog": videos,
        "overview_30": overview_30,
        "overview_90": overview_90,
        "daily_30": daily_30,
        "daily_90": daily_90,
        "videos_30": videos_30,
        "videos_90": videos_90,
    }


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


def flatten_video_catalog(videos: list[dict[str, Any]], today: dt.date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in videos:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        duration_seconds = parse_iso8601_duration(item.get("contentDetails", {}).get("duration", "PT0S"))
        rows.append(
            {
                "video": item.get("id"),
                "title": snippet.get("title", ""),
                "publishedAt": snippet.get("publishedAt", ""),
                "daysSincePublished": days_since_published(snippet.get("publishedAt", dt.datetime.now().isoformat()), today),
                "durationSeconds": duration_seconds,
                "format": infer_format(snippet.get("title", ""), duration_seconds),
                "lifetimeViews": safe_int(stats.get("viewCount")),
                "lifetimeLikes": safe_int(stats.get("likeCount")),
                "lifetimeComments": safe_int(stats.get("commentCount")),
                "topics": ", ".join(infer_topics(snippet.get("title", ""), snippet.get("description", ""))),
            }
        )
    return rows


def merge_metrics(catalog_rows: list[dict[str, Any]], analytics_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_video = {row["video"]: dict(row) for row in catalog_rows}
    for row in analytics_rows:
        video_id = row.get("video")
        if not video_id:
            continue
        target = by_video.setdefault(video_id, {"video": video_id})
        for key, value in row.items():
            if key == "video":
                continue
            target[key] = value
    return list(by_video.values())


def score_video(row: dict[str, Any]) -> float:
    views = safe_float(row.get("views"))
    watch = safe_float(row.get("estimatedMinutesWatched"))
    retention = safe_float(row.get("averageViewPercentage"))
    subs = safe_float(row.get("subscribersGained"))
    return views * 0.35 + watch * 0.2 + retention * 3 + subs * 10


def build_insights(dataset: dict[str, Any], today: dt.date) -> dict[str, Any]:
    channel = dataset["channel"]
    catalog_rows = flatten_video_catalog(dataset["videos_catalog"], today)
    video_rows_30 = merge_metrics(catalog_rows, analytics_rows_to_dicts(dataset["videos_30"]))
    video_rows_90 = merge_metrics(catalog_rows, analytics_rows_to_dicts(dataset["videos_90"]))

    for row in video_rows_30 + video_rows_90:
        row["views"] = safe_int(row.get("views"))
        row["estimatedMinutesWatched"] = safe_float(row.get("estimatedMinutesWatched"))
        row["averageViewDuration"] = safe_float(row.get("averageViewDuration"))
        row["averageViewPercentage"] = safe_float(row.get("averageViewPercentage"))
        row["likes"] = safe_int(row.get("likes"))
        row["comments"] = safe_int(row.get("comments"))
        row["subscribersGained"] = safe_int(row.get("subscribersGained"))
        row["score"] = score_video(row)
        row["viewsPerDay"] = row["views"] / max(row.get("daysSincePublished", 1), 1)
        row["watchMinutesPerView"] = (
            row["estimatedMinutesWatched"] / row["views"] if row["views"] else 0.0
        )

    rows_30_active = [row for row in video_rows_30 if row.get("views", 0) > 0]
    rows_90_active = [row for row in video_rows_90 if row.get("views", 0) > 0]
    recent_rows = [row for row in rows_90_active if row.get("daysSincePublished", 999) <= 30]

    top_views = sorted(rows_90_active, key=lambda row: row["views"], reverse=True)[:10]
    top_watch = sorted(rows_90_active, key=lambda row: row["estimatedMinutesWatched"], reverse=True)[:10]
    top_retention = sorted(
        [row for row in rows_90_active if row["averageViewPercentage"] > 0 and row["views"] >= 50],
        key=lambda row: row["averageViewPercentage"],
        reverse=True,
    )[:10]
    weak_30 = sorted(rows_30_active, key=lambda row: row["score"])[:10]
    potential = sorted(
        [
            row for row in rows_90_active
            if row["views"] >= 100 and row["averageViewPercentage"] < 35 and row["watchMinutesPerView"] < 1.5
        ],
        key=lambda row: (row["views"], -row["averageViewPercentage"]),
        reverse=True,
    )[:10]
    promising_recent = sorted(
        [
            row for row in recent_rows
            if row["viewsPerDay"] >= 10 and row["averageViewPercentage"] >= 35
        ],
        key=lambda row: (row["viewsPerDay"], row["averageViewPercentage"]),
        reverse=True,
    )[:10]
    died_fast = sorted(
        [
            row for row in recent_rows
            if row["viewsPerDay"] < 5 and row["averageViewPercentage"] < 35
        ],
        key=lambda row: (row["viewsPerDay"], row["averageViewPercentage"]),
    )[:10]

    format_summary: dict[str, dict[str, float]] = {}
    for group_name in ["short", "tutorial", "long", "standard"]:
        group = [row for row in rows_90_active if row.get("format") == group_name]
        if not group:
            continue
        format_summary[group_name] = {
            "videos": len(group),
            "avgViews": sum(row["views"] for row in group) / len(group),
            "avgWatchMinutes": sum(row["estimatedMinutesWatched"] for row in group) / len(group),
            "avgRetention": sum(row["averageViewPercentage"] for row in group) / len(group),
        }

    topic_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"videos": 0, "views": 0, "watch": 0, "retention": 0})
    for row in rows_90_active:
        topics = [topic.strip() for topic in row.get("topics", "").split(",") if topic.strip()]
        for topic in topics[:3]:
            topic_stats[topic]["videos"] += 1
            topic_stats[topic]["views"] += row["views"]
            topic_stats[topic]["watch"] += row["estimatedMinutesWatched"]
            topic_stats[topic]["retention"] += row["averageViewPercentage"]

    normalized_topics: list[dict[str, Any]] = []
    for topic, values in topic_stats.items():
        if values["videos"] == 0:
            continue
        normalized_topics.append(
            {
                "topic": topic,
                "videos": values["videos"],
                "avgViews": values["views"] / values["videos"],
                "avgWatch": values["watch"] / values["videos"],
                "avgRetention": values["retention"] / values["videos"],
            }
        )

    good_topics = sorted(
        [item for item in normalized_topics if item["videos"] >= 2],
        key=lambda item: (item["avgViews"], item["avgWatch"], item["avgRetention"]),
        reverse=True,
    )[:8]
    weak_topics = sorted(
        [item for item in normalized_topics if item["videos"] >= 2],
        key=lambda item: (item["avgViews"], item["avgWatch"], item["avgRetention"]),
    )[:8]

    overview_30 = analytics_rows_to_dicts(dataset["overview_30"])
    overview_90 = analytics_rows_to_dicts(dataset["overview_90"])
    overview_30_row = overview_30[0] if overview_30 else {}
    overview_90_row = overview_90[0] if overview_90 else {}

    executive = {
        "channelTitle": channel.get("snippet", {}).get("title"),
        "subscribers": safe_int(channel.get("statistics", {}).get("subscriberCount")),
        "views30": safe_int(overview_30_row.get("views")),
        "views90": safe_int(overview_90_row.get("views")),
        "watchMinutes30": safe_float(overview_30_row.get("estimatedMinutesWatched")),
        "watchMinutes90": safe_float(overview_90_row.get("estimatedMinutesWatched")),
        "avgRetention30": safe_float(overview_30_row.get("averageViewPercentage")),
        "avgRetention90": safe_float(overview_90_row.get("averageViewPercentage")),
        "subsNet30": safe_int(overview_30_row.get("subscribersGained")) - safe_int(overview_30_row.get("subscribersLost")),
        "subsNet90": safe_int(overview_90_row.get("subscribersGained")) - safe_int(overview_90_row.get("subscribersLost")),
    }

    second_part_candidates = [
        row for row in top_watch[:10]
        if row["averageViewPercentage"] >= executive["avgRetention90"] and row["comments"] >= 1
    ][:5]
    retitle_candidates = [
        row for row in potential
        if row["views"] >= 100
    ][:5]

    return {
        "executive": executive,
        "video_rows_30": rows_30_active,
        "video_rows_90": rows_90_active,
        "top_views": top_views,
        "top_watch": top_watch,
        "top_retention": top_retention,
        "weak_30": weak_30,
        "potential": potential,
        "promising_recent": promising_recent,
        "died_fast": died_fast,
        "format_summary": format_summary,
        "good_topics": good_topics,
        "weak_topics": weak_topics,
        "second_part_candidates": second_part_candidates,
        "retitle_candidates": retitle_candidates,
    }


def _fmt_int(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def _fmt_float(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def bullet_video(row: dict[str, Any], include_ctr: bool = False) -> str:
    bits = [
        f"**{row.get('title', row.get('video'))}**",
        f"views {_fmt_int(row.get('views', 0))}",
        f"watch {_fmt_int(row.get('estimatedMinutesWatched', 0))} min",
        f"retention {_fmt_float(row.get('averageViewPercentage', 0.0))}%",
    ]
    if include_ctr:
        bits.append(f"views/dia {_fmt_float(row.get('viewsPerDay', 0.0), 1)}")
    return " | ".join(bits)


def generate_markdown_report(insights: dict[str, Any], dataset: dict[str, Any], today: dt.date) -> str:
    executive = insights["executive"]
    periods = dataset["periods"]

    format_lines = []
    for fmt, values in insights["format_summary"].items():
        format_lines.append(
            f"- `{fmt}`: {values['videos']} videos, media {_fmt_int(values['avgViews'])} views, "
            f"{_fmt_int(values['avgWatchMinutes'])} min de watch time, retención {_fmt_float(values['avgRetention'])}%."
        )
    if not format_lines:
        format_lines.append("- No hay masa suficiente para comparar formatos con confianza.")

    good_topics = insights["good_topics"]
    weak_topics = insights["weak_topics"]
    top_views = insights["top_views"][:5]
    weak_30 = insights["weak_30"][:5]
    potential = insights["potential"][:5]
    promising_recent = insights["promising_recent"][:5]
    died_fast = insights["died_fast"][:5]
    second_part = insights["second_part_candidates"][:5]
    retitle = insights["retitle_candidates"][:5]
    top_watch = insights["top_watch"][:5]
    top_retention = insights["top_retention"][:5]

    lines = [
        f"# Channel Diagnosis - {today.isoformat()}",
        "",
        "## 1. Resumen ejecutivo del canal",
        "",
        f"- Canal analizado: **{executive['channelTitle']}**",
        f"- Ventana 30 días: {periods['30d']['start']} a {periods['30d']['end']}",
        f"- Ventana 90 días: {periods['90d']['start']} a {periods['90d']['end']}",
        f"- Últimos 30 días: {_fmt_int(executive['views30'])} views, {_fmt_int(executive['watchMinutes30'])} minutos vistos, retención media {_fmt_float(executive['avgRetention30'])}%, neto de suscriptores {executive['subsNet30']}.",
        f"- Últimos 90 días: {_fmt_int(executive['views90'])} views, {_fmt_int(executive['watchMinutes90'])} minutos vistos, retención media {_fmt_float(executive['avgRetention90'])}%, neto de suscriptores {executive['subsNet90']}.",
        "",
        "## 2. Qué está funcionando",
        "",
    ]

    if top_views:
        lines.extend([f"- {bullet_video(row)}" for row in top_views[:3]])
    if top_watch:
        lines.append(f"- El watch time más fuerte se concentra en piezas como {top_watch[0].get('title', top_watch[0].get('video'))}.")
    if good_topics:
        topic_text = ", ".join(
            f"`{item['topic']}` ({_fmt_int(item['avgViews'])} views medias)"
            for item in good_topics[:5]
        )
        lines.append(f"- Los temas que mejor se repiten por métricas reales son: {topic_text}.")
    lines.extend(format_lines)
    lines.extend([
        "",
        "## 3. Qué no está funcionando",
        "",
    ])
    if weak_30:
        lines.extend([f"- {bullet_video(row)}" for row in weak_30[:3]])
    if weak_topics:
        topic_text = ", ".join(
            f"`{item['topic']}` ({_fmt_int(item['avgViews'])} views medias)"
            for item in weak_topics[:5]
        )
        lines.append(f"- Los temas con peor señal dentro de los vídeos comparables son: {topic_text}.")
    if died_fast:
        lines.append("- Algunos vídeos recientes se frenan pronto por mezcla de baja tracción inicial y retención floja.")
    lines.extend([
        "",
        "## 4. Mejores vídeos del periodo",
        "",
        "### Por vistas",
        "",
    ])
    lines.extend([f"- {bullet_video(row)}" for row in top_views])
    lines.extend([
        "",
        "### Por tiempo de visualización",
        "",
    ])
    lines.extend([f"- {bullet_video(row)}" for row in top_watch])
    lines.extend([
        "",
        "### Por retención",
        "",
    ])
    if top_retention:
        lines.extend([f"- {bullet_video(row)}" for row in top_retention])
        lines.append("- En shorts, la retención media puede superar el 100% cuando hay repeticiones automáticas.")
    else:
        lines.append("- La API no devolvió suficiente masa de retención comparable para destacar vídeos con confianza.")
    lines.extend([
        "",
        "## 5. Peores vídeos del periodo",
        "",
    ])
    if weak_30:
        lines.extend([f"- {bullet_video(row)}" for row in weak_30])
    else:
        lines.append("- No hay suficientes vídeos activos en 30 días para listar peores piezas con confianza.")
    lines.extend([
        "",
        "## 6. Vídeos con potencial desaprovechado",
        "",
    ])
    if potential:
        lines.extend([f"- {bullet_video(row, include_ctr=True)}" for row in potential])
        lines.append("- Estos casos piden revisar gancho, título o miniatura porque sí lograron algo de tráfico, pero la retención media no acompaña.")
    else:
        lines.append("- No apareció una bolsa clara de vídeos con señal suficiente de alcance y retención floja en la muestra actual.")
    lines.extend([
        "",
        "## 7. Temas recomendados",
        "",
    ])
    if good_topics:
        for item in good_topics[:6]:
            lines.append(
                f"- Repetir o escalar `{item['topic']}`: {_fmt_int(item['avgViews'])} views medias, "
                f"{_fmt_int(item['avgWatch'])} min medios, retención {_fmt_float(item['avgRetention'])}%."
            )
    else:
        lines.append("- No hay suficiente repetición temática para recomendar líneas fuertes con confianza.")
    if second_part:
        lines.append("- Vídeos con pinta de merecer segunda parte:")
        lines.extend([f"- {bullet_video(row)}" for row in second_part])
    lines.extend([
        "",
        "## 8. Temas a evitar o pausar",
        "",
    ])
    if weak_topics:
        for item in weak_topics[:6]:
            lines.append(
                f"- Pausar o replantear `{item['topic']}`: {_fmt_int(item['avgViews'])} views medias, "
                f"{_fmt_int(item['avgWatch'])} min medios, retención {_fmt_float(item['avgRetention'])}%."
            )
    else:
        lines.append("- No hay suficiente repetición temática floja para pausar temas con seguridad.")
    if died_fast:
        lines.append("- Vídeos recientes que se han muerto rápido:")
        lines.extend([f"- {bullet_video(row)}" for row in died_fast])
    lines.extend([
        "",
        "## 9. Acciones concretas para los próximos 7 días",
        "",
    ])
    if promising_recent:
        lines.append("- Doblar la apuesta en vídeos recientes que ya están enseñando tracción:")
        lines.extend([f"- {bullet_video(row)}" for row in promising_recent[:3]])
    if retitle:
        lines.append("- Revisar título, portada y primer minuto en estos vídeos con algo de tracción pero retención floja:")
        lines.extend([f"- {bullet_video(row, include_ctr=True)}" for row in retitle])
    if good_topics:
        lines.append(
            "- Preparar al menos 2 nuevas piezas derivadas de los mejores temas detectados: "
            + ", ".join(f"`{item['topic']}`" for item in good_topics[:3])
            + "."
        )
    if top_retention:
        lines.append("- Reutilizar estructura narrativa de los vídeos con mejor retención para las próximas publicaciones.")
    lines.extend([
        "",
        "## 10. Limitaciones del análisis",
        "",
        "- El diagnóstico usa métricas reales de YouTube Data API v3 y YouTube Analytics API.",
        "- No se ha usado Google Custom Search en este flujo.",
        "- La retención analizada es `averageViewPercentage`, no curva completa segundo a segundo. En shorts puede superar el 100% por repeticiones.",
        "- La API no ha devuelto una señal de impresiones utilizable en esta consulta, así que la detección de potencial desaprovechado se apoya en vistas, watch time y retención.",
        "- La detección de shorts, tutoriales y vídeos largos es inferida por duración y texto del título, no por una etiqueta oficial del canal.",
        "- Los temas se infieren por tokens repetidos en título y descripción; sirven como señal operativa, no como taxonomía editorial perfecta.",
    ])

    return "\n".join(lines) + "\n"


def run_channel_diagnosis(today: dt.date | None = None) -> dict[str, Path]:
    report_date = today or dt.date.today()
    ensure_output_dirs()

    dataset = fetch_all_datasets(report_date)
    insights = build_insights(dataset, report_date)

    stamp = report_date.isoformat()
    json_path = DATA_DIR / f"channel_diagnosis_{stamp}.json"
    csv_catalog_path = DATA_DIR / f"channel_diagnosis_videos_catalog_{stamp}.csv"
    csv_30_path = DATA_DIR / f"channel_diagnosis_videos_30d_{stamp}.csv"
    csv_90_path = DATA_DIR / f"channel_diagnosis_videos_90d_{stamp}.csv"
    report_path = REPORTS_DIR / f"channel_diagnosis_{stamp}.md"

    save_json(json_path, {"dataset": dataset, "insights": insights})
    save_csv(csv_catalog_path, flatten_video_catalog(dataset["videos_catalog"], report_date))
    save_csv(csv_30_path, insights["video_rows_30"])
    save_csv(csv_90_path, insights["video_rows_90"])
    report_path.write_text(generate_markdown_report(insights, dataset, report_date), encoding="utf-8")

    return {
        "report": report_path,
        "json": json_path,
        "csv_catalog": csv_catalog_path,
        "csv_30": csv_30_path,
        "csv_90": csv_90_path,
    }
