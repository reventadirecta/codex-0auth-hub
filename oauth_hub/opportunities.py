import csv
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .paths import ROOT


DIAGNOSIS_DATA_DIR = ROOT / "data" / "channel_diagnosis"
OPPORTUNITIES_DATA_DIR = ROOT / "data" / "channel_opportunities"
REPORTS_DIR = ROOT / "reports"

STRATEGIC_CATEGORIES = {
    "ia_tutorial",
    "ia_local",
    "agentes_autonomos",
    "codex_automatizacion",
    "comfyui_video",
    "hardware_ia_gpu",
}
COMPATIBLE_CATEGORIES = {"short_viral", "experimento_variedad"}
LEGACY_CATEGORIES = {"legacy_gaming", "tarkov_directo"}


def ensure_output_dirs() -> None:
    OPPORTUNITIES_DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def find_diagnosis_paths(report_date: dt.date | None = None) -> dict[str, Path]:
    if report_date:
        stamp = report_date.isoformat()
        json_path = DIAGNOSIS_DATA_DIR / f"channel_diagnosis_{stamp}.json"
        report_path = REPORTS_DIR / f"channel_diagnosis_{stamp}.md"
        if not json_path.exists():
            raise FileNotFoundError(f"Diagnosis JSON not found for {stamp}: {json_path}")
        return {"json": json_path, "report": report_path}

    candidates = sorted(DIAGNOSIS_DATA_DIR.glob("channel_diagnosis_*.json"))
    if not candidates:
        raise FileNotFoundError("No channel_diagnosis JSON files found in data/channel_diagnosis.")
    latest = candidates[-1]
    stamp = latest.stem.replace("channel_diagnosis_", "")
    return {"json": latest, "report": REPORTS_DIR / f"channel_diagnosis_{stamp}.md"}


def load_diagnosis_payload(report_date: dt.date | None = None) -> tuple[dict[str, Any], dict[str, Path]]:
    paths = find_diagnosis_paths(report_date)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    return payload, paths


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


def normalize_text(*parts: str) -> str:
    return " ".join(part.lower() for part in parts if part).replace("\n", " ")


def tokenize_text(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9áéíóúñ]+", text.lower()))


def has_phrase(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def has_token(tokens: set[str], *values: str) -> bool:
    return any(value in tokens for value in values)


def classify_editorial(video: dict[str, Any]) -> tuple[str, str, bool]:
    text = normalize_text(
        video.get("title", ""),
        video.get("description", ""),
        " ".join(video.get("tags", [])),
    )
    tokens = tokenize_text(text)
    duration = int(video.get("durationSeconds", 0) or 0)
    format_name = video.get("format", "")

    if has_token(tokens, "tarkov", "eft", "smugglers", "pve"):
        if duration >= 900 or "🔴" in video.get("title", "") or "directo" in text:
            return "tarkov_directo", "Tarkov PvE y directos heredados", False
        return "legacy_gaming", "Gaming heredado de Tarkov", False
    if has_token(tokens, "7dtd", "survival", "laberynth", "metalgearsolid", "mgs", "nms", "gameplay"):
        return "legacy_gaming", "Gaming heredado", False
    if format_name == "short" and (
        has_token(tokens, "anime", "goku", "dragonball", "boss", "illojuan", "xokas")
        or has_phrase(text, "final boss")
    ):
        return "short_viral", "Short viral compatible con el canal", True
    if (
        has_token(tokens, "codex", "automatizacion", "automation", "workflow", "workspace", "extension", "browser")
        or has_phrase(text, "agent workspace", "workspace")
    ) and has_token(tokens, "agent", "agents", "hermes", "api", "tool", "script", "docker"):
        return "codex_automatizacion", "Codex y automatización aplicada", True
    if has_token(tokens, "hermes", "agent", "agents", "nous", "gateway") or has_phrase(text, "ai agents", "agentes ia"):
        return "agentes_autonomos", "Agentes autónomos y orquestación", True
    if has_token(tokens, "ollama", "local", "mistral", "qwen", "llm", "uncensored", "abliterated", "openclaw"):
        return "ia_local", "IA local y modelos abiertos", True
    if has_token(tokens, "comfyui", "imagen", "image", "animated", "flux", "comfy") and (
        has_token(tokens, "ai", "ia", "anime", "video") or has_phrase(text, "video ia")
    ):
        return "comfyui_video", "ComfyUI y generación visual IA", True
    if (
        has_token(tokens, "gpu", "rtx", "rx6700xt", "rx6700", "vram", "cuda", "ram", "hardware")
        or has_phrase(text, "tarjetas gráficas", "tarjetas graficas", "pc gamer")
    ):
        if has_token(tokens, "ia", "local", "modelo", "ollama", "comfyui", "llm", "gpu", "vram") or has_phrase(
            text, "para ia", "ia local"
        ):
            return "hardware_ia_gpu", "Hardware para IA y GPU", True
    if (
        has_token(tokens, "tutorial", "instala", "configura", "guia", "guía")
        or has_phrase(text, "paso a paso", "cómo ", "como ")
    ) and has_token(tokens, "ia", "ollama", "mistral", "qwen", "llm", "agent", "agents", "hermes", "comfyui", "gpu"):
        return "ia_tutorial", "Tutorial técnico de IA", True
    if has_token(tokens, "gaming", "laberynth", "nms"):
        return "legacy_gaming", "Gaming heredado", False
    if has_token(tokens, "piscina", "gelatina", "mogumogu", "bebida", "botiquin", "botiquín"):
        return "experimento_variedad", "Experimento de variedad", False
    return "otros", "Otros temas del canal", False


def bucket_priority(category: str) -> str:
    if category in STRATEGIC_CATEGORIES:
        return "A"
    if category in COMPATIBLE_CATEGORIES:
        return "B"
    if category in LEGACY_CATEGORIES:
        return "C"
    return "B"


def enrich_video_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    dataset = payload["dataset"]
    insights = payload["insights"]
    catalog = dataset["videos_catalog"]
    catalog_by_id: dict[str, dict[str, Any]] = {}
    for item in catalog:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        catalog_by_id[item.get("id")] = {
            "video": item.get("id"),
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "tags": snippet.get("tags", []),
            "publishedAt": snippet.get("publishedAt", ""),
            "categoryId": snippet.get("categoryId", ""),
            "lifetimeViews": int(stats.get("viewCount", 0) or 0),
            "lifetimeLikes": int(stats.get("likeCount", 0) or 0),
            "lifetimeComments": int(stats.get("commentCount", 0) or 0),
        }

    rows_30 = {row["video"]: row for row in insights.get("video_rows_30", [])}
    rows_90 = {row["video"]: row for row in insights.get("video_rows_90", [])}
    all_video_ids = set(catalog_by_id) | set(rows_30) | set(rows_90)
    enriched: list[dict[str, Any]] = []

    for video_id in all_video_ids:
        base = dict(catalog_by_id.get(video_id, {}))
        base["video"] = video_id
        base.update({f"{key}30": value for key, value in rows_30.get(video_id, {}).items() if key != "video"})
        base.update({f"{key}90": value for key, value in rows_90.get(video_id, {}).items() if key != "video"})

        # Normalize keys used by the opportunities layer.
        base["views30"] = int(base.get("views30", 0) or 0)
        base["views90"] = int(base.get("views90", 0) or 0)
        base["watch30"] = float(base.get("estimatedMinutesWatched30", 0.0) or 0.0)
        base["watch90"] = float(base.get("estimatedMinutesWatched90", 0.0) or 0.0)
        base["retention30"] = float(base.get("averageViewPercentage30", 0.0) or 0.0)
        base["retention90"] = float(base.get("averageViewPercentage90", 0.0) or 0.0)
        base["likes30"] = int(base.get("likes30", 0) or 0)
        base["likes90"] = int(base.get("likes90", 0) or 0)
        base["comments30"] = int(base.get("comments30", 0) or 0)
        base["comments90"] = int(base.get("comments90", 0) or 0)
        base["subs30"] = int(base.get("subscribersGained30", 0) or 0)
        base["subs90"] = int(base.get("subscribersGained90", 0) or 0)
        base["viewsPerDay30"] = float(base.get("viewsPerDay30", 0.0) or 0.0)
        base["viewsPerDay90"] = float(base.get("viewsPerDay90", 0.0) or 0.0)
        base["watchMinutesPerView30"] = float(base.get("watchMinutesPerView30", 0.0) or 0.0)
        base["watchMinutesPerView90"] = float(base.get("watchMinutesPerView90", 0.0) or 0.0)
        base["durationSeconds"] = int(base.get("durationSeconds30", base.get("durationSeconds90", 0)) or 0)
        base["daysSincePublished"] = int(base.get("daysSincePublished30", base.get("daysSincePublished90", 9999)) or 9999)
        base["format"] = base.get("format30") or base.get("format90") or "standard"
        category, theme, aligned = classify_editorial(base)
        base["editorialCategory"] = category
        base["editorialTheme"] = theme
        base["alignedWithNewDirection"] = aligned
        base["priorityBucket"] = bucket_priority(category)
        base["engagement30"] = ((base["likes30"] + base["comments30"]) / base["views30"] * 100) if base["views30"] else 0.0
        base["engagement90"] = ((base["likes90"] + base["comments90"]) / base["views90"] * 100) if base["views90"] else 0.0
        enriched.append(base)

    return enriched


def make_action(
    section: str,
    title: str,
    category: str,
    priority: str,
    reason: str,
    action: str,
    expected: str,
    difficulty: str,
    inferred: bool = False,
) -> dict[str, Any]:
    return {
        "section": section,
        "title": title,
        "editorialCategory": category,
        "priority": priority,
        "reason": reason,
        "recommendedAction": action,
        "expectedResult": expected,
        "difficulty": difficulty,
        "inferred": inferred,
    }


def top_by(rows: list[dict[str, Any]], key: str, limit: int = 5, reverse: bool = True) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: row.get(key, 0), reverse=reverse)[:limit]


def build_actions(payload: dict[str, Any], diagnosis_paths: dict[str, Path], report_date: dt.date) -> dict[str, Any]:
    insights = payload["insights"]
    videos = enrich_video_rows(payload)

    aligned = [row for row in videos if row["editorialCategory"] in STRATEGIC_CATEGORIES and row["views90"] > 0]
    compatible = [row for row in videos if row["editorialCategory"] in COMPATIBLE_CATEGORIES and row["views90"] > 0]
    legacy = [row for row in videos if row["editorialCategory"] in LEGACY_CATEGORIES and row["views90"] > 0]
    recent = [row for row in videos if row["daysSincePublished"] <= 30 and row["views30"] > 0]

    priority_a_rows = top_by(
        sorted(aligned, key=lambda row: (row["viewsPerDay30"], row["retention30"], row["subs30"]), reverse=True),
        "viewsPerDay30",
        limit=6,
    )
    priority_b_rows = top_by(
        sorted(
            [row for row in compatible if row["views30"] >= 100],
            key=lambda row: (row["viewsPerDay30"], row["retention30"]),
            reverse=True,
        ),
        "viewsPerDay30",
        limit=4,
    )
    priority_c_rows = top_by(
        sorted(legacy, key=lambda row: (row["watch90"], row["views90"]), reverse=True),
        "watch90",
        limit=4,
    )

    second_part_rows = [
        row for row in aligned
        if row["comments30"] >= 1 and (row["watch30"] >= 200 or row["subs30"] >= 2)
    ]
    second_part_rows = top_by(second_part_rows, "watch30", limit=5)

    blogger_rows = [
        row for row in aligned
        if row["durationSeconds"] >= 180 and (row["watch30"] >= 150 or row["comments30"] >= 1)
    ]
    blogger_rows = top_by(blogger_rows, "watch30", limit=5)

    long_to_shorts_rows = [
        row for row in aligned + legacy
        if row["durationSeconds"] >= 300 and row["watch90"] >= 200
    ]
    long_to_shorts_rows = top_by(long_to_shorts_rows, "watch90", limit=5)

    shorts_to_long_rows = [
        row for row in videos
        if row["format"] == "short"
        and row["views30"] >= 150
        and row["retention30"] >= 60
        and row["editorialCategory"] in STRATEGIC_CATEGORIES | COMPATIBLE_CATEGORIES
    ]
    shorts_to_long_rows = top_by(shorts_to_long_rows, "views30", limit=5)

    retitle_rows = [
        row for row in aligned + compatible
        if row["views30"] >= 70 and row["retention30"] < 35
    ]
    retitle_rows = top_by(retitle_rows, "views30", limit=5)

    category_retention: dict[str, float] = {}
    for category in {row["editorialCategory"] for row in videos}:
        members = [row for row in videos if row["editorialCategory"] == category and row["views30"] > 0]
        if members:
            category_retention[category] = sum(row["retention30"] for row in members) / len(members)

    thumbnail_rows = [
        row for row in aligned + compatible
        if row["views30"] >= 50
        and row["retention30"] >= category_retention.get(row["editorialCategory"], 0)
        and row["viewsPerDay30"] < 8
    ]
    thumbnail_rows = top_by(thumbnail_rows, "retention30", limit=5)

    theme_groups: dict[str, list[dict[str, Any]]] = {}
    for row in aligned:
        theme_groups.setdefault(row["editorialTheme"], []).append(row)

    repeat_themes = sorted(
        [
            {
                "theme": theme,
                "videos": len(group),
                "avgViews30": sum(item["views30"] for item in group) / len(group),
                "avgWatch30": sum(item["watch30"] for item in group) / len(group),
                "avgRetention30": sum(item["retention30"] for item in group) / len(group),
            }
            for theme, group in theme_groups.items()
            if len(group) >= 1
        ],
        key=lambda item: (item["avgViews30"], item["avgWatch30"], item["avgRetention30"]),
        reverse=True,
    )
    repeat_themes = [
        item for item in repeat_themes
        if item["avgViews30"] >= 100 or item["avgWatch30"] >= 150
    ][:6]

    pause_themes = sorted(
        [
            {
                "theme": row["editorialTheme"],
                "category": row["editorialCategory"],
                "title": row["title"],
                "views30": row["views30"],
                "retention30": row["retention30"],
                "viewsPerDay30": row["viewsPerDay30"],
            }
            for row in recent
            if row["editorialCategory"] in LEGACY_CATEGORIES | {"experimento_variedad", "otros"}
            or (row["editorialCategory"] in STRATEGIC_CATEGORIES and row["views30"] < 80 and row["retention30"] < 30)
        ],
        key=lambda item: (item["views30"], item["retention30"]),
    )[:6]

    actions: list[dict[str, Any]] = []

    for row in priority_a_rows:
        actions.append(
            make_action(
                "1. Prioridad A: acciones alineadas con el nuevo rumbo del canal.",
                row["title"],
                row["editorialCategory"],
                "A",
                (
                    f"{row['views30']} views en 30d, {row['watch30']:.0f} min vistos, "
                    f"{row['retention30']:.1f}% de retención y {row['subs30']} suscriptores ganados."
                ),
                "Crear continuación, tutorial complementario o versión ampliada esta misma semana.",
                "Refuerza el nuevo posicionamiento del canal y acelera suscriptores sobre temas estratégicos.",
                "media",
            )
        )

    for row in priority_b_rows:
        actions.append(
            make_action(
                "2. Prioridad B: acciones virales compatibles que pueden atraer tráfico.",
                row["title"],
                row["editorialCategory"],
                "B",
                (
                    f"{row['views30']} views en 30d con {row['retention30']:.1f}% de retención. "
                    "Funciona como puerta de entrada, aunque no sea el corazón editorial del canal."
                ),
                "Publicar una variante conectada con IA o automatización para arrastrar tráfico hacia el nuevo rumbo.",
                "Aporta descubrimiento sin dejar que el canal vuelva a depender de variedad pura.",
                "baja",
                inferred=True,
            )
        )

    for row in priority_c_rows:
        actions.append(
            make_action(
                "3. Prioridad C: contenido heredado o gaming que funciona, pero no debe dirigir la estrategia.",
                row["title"],
                row["editorialCategory"],
                "C",
                (
                    f"{row['watch90']:.0f} min vistos en 90d y {row['views90']} views. "
                    "Aporta watch time heredado, pero no empuja claramente la nueva línea editorial."
                ),
                "Mantenerlo como soporte táctico o directo puntual, sin convertirlo en eje de calendario.",
                "Protege el watch time heredado mientras el canal gira hacia IA y automatización.",
                "baja",
            )
        )

    for row in second_part_rows:
        actions.append(
            make_action(
                "4. Vídeos que merecen segunda parte.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"{row['watch30']:.0f} min vistos, {row['comments30']} comentarios y "
                    f"{row['subs30']} suscriptores ganados en 30d."
                ),
                "Publicar segunda parte, actualización o caso de uso más avanzado.",
                "Aprovecha interés probado y convierte un vídeo ganador en mini serie.",
                "media",
            )
        )

    for row in blogger_rows:
        actions.append(
            make_action(
                "5. Vídeos que merecen artículo en Blogger.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"{row['durationSeconds']//60} min de duración, {row['watch30']:.0f} min vistos y "
                    f"{row['comments30']} comentarios. Tiene estructura reutilizable como guía."
                ),
                "Convertirlo en artículo paso a paso con comandos, enlaces y notas operativas.",
                "Abre tráfico evergreen y reutiliza contenido técnico ya validado en YouTube.",
                "media",
            )
        )

    for row in long_to_shorts_rows:
        actions.append(
            make_action(
                "6. Vídeos largos que pueden generar shorts.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"{row['watch90']:.0f} min vistos en 90d y duración de {row['durationSeconds']//60} min. "
                    "Hay material suficiente para recortes."
                ),
                "Extraer 2 o 3 clips con gancho claro, resultado visible o error/resolución llamativa.",
                "Recicla watch time largo en piezas de descubrimiento más fáciles de distribuir.",
                "baja",
                inferred=True,
            )
        )

    for row in shorts_to_long_rows:
        actions.append(
            make_action(
                "7. Shorts que pueden convertirse en vídeo largo.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"{row['views30']} views en 30d con {row['retention30']:.1f}% de retención. "
                    "El tema ya demostró interés en formato corto."
                ),
                "Desarrollar versión larga con contexto, setup, herramientas y errores reales.",
                "Convierte curiosidad rápida en vídeo de autoridad y watch time útil.",
                "media",
            )
        )

    for row in retitle_rows:
        actions.append(
            make_action(
                "8. Vídeos que necesitan cambio de título.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"{row['views30']} views y {row['retention30']:.1f}% de retención en 30d. "
                    "Hay señal de interés, pero el empaquetado editorial no está cerrando bien."
                ),
                "Probar un título más específico sobre resultado, promesa o problema resuelto.",
                "Puede mejorar la intención de clic y alinear mejor expectativa con contenido real.",
                "baja",
                inferred=True,
            )
        )

    for row in thumbnail_rows:
        actions.append(
            make_action(
                "9. Vídeos que necesitan cambio de miniatura.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"Retención {row['retention30']:.1f}% y solo {row['viewsPerDay30']:.1f} views/día. "
                    "La retención no es mala para su categoría, así que el freno parece de empaque."
                ),
                "Probar miniatura con una sola promesa visual, menos texto y contraste más claro del resultado.",
                "Puede desbloquear más tracción sin rehacer el vídeo.",
                "media",
                inferred=True,
            )
        )

    for item in repeat_themes:
        actions.append(
            make_action(
                "10. Temas que conviene repetir esta semana.",
                item["theme"],
                "tema_editorial",
                "A",
                (
                    f"{item['videos']} piezas comparables, media de {item['avgViews30']:.0f} views, "
                    f"{item['avgWatch30']:.0f} min vistos y {item['avgRetention30']:.1f}% de retención."
                ),
                "Publicar otra pieza esta semana en la misma línea, subiendo complejidad o utilidad práctica.",
                "Consolida una vertical que ya está funcionando con datos recientes.",
                "media",
            )
        )

    for item in pause_themes:
        actions.append(
            make_action(
                "11. Temas que conviene pausar.",
                item["title"],
                item["category"],
                bucket_priority(item["category"]),
                (
                    f"{item['views30']} views en 30d, {item['retention30']:.1f}% de retención y "
                    f"{item['viewsPerDay30']:.1f} views/día."
                ),
                "Pausar publicaciones similares o replantearlas por completo antes de repetir tema.",
                "Evita gastar calendario en líneas que hoy no empujan el nuevo rumbo del canal.",
                "baja",
            )
        )

    raw_plan_rows = priority_a_rows[:3] + shorts_to_long_rows[:2] + blogger_rows[:1] + retitle_rows[:1]
    seen_plan_titles: set[str] = set()
    plan_rows: list[dict[str, Any]] = []
    for row in raw_plan_rows:
        title = row.get("title", "")
        if title in seen_plan_titles:
            continue
        seen_plan_titles.add(title)
        plan_rows.append(row)
        if len(plan_rows) >= 6:
            break
    for row in plan_rows:
        action_text = "Producir o reciclar pieza prioritaria" if row in priority_a_rows else "Ejecutar mejora editorial"
        actions.append(
            make_action(
                "12. Plan de acción para los próximos 7 días.",
                row["title"],
                row["editorialCategory"],
                row["priorityBucket"],
                (
                    f"{row['views30']} views en 30d, {row['watch30']:.0f} min vistos y "
                    f"{row['retention30']:.1f}% de retención."
                ),
                action_text,
                "Convierte el diagnóstico en una cola semanal con impacto medible.",
                "media",
                inferred=row in retitle_rows,
            )
        )

    return {
        "sourceDiagnosisJson": str(diagnosis_paths["json"]),
        "sourceDiagnosisReport": str(diagnosis_paths["report"]),
        "reportDate": report_date.isoformat(),
        "videos": videos,
        "actions": actions,
    }


def _render_action(action: dict[str, Any]) -> str:
    inferred = " | inferida" if action.get("inferred") else ""
    return (
        f"- **{action['title']}** | categoria `{action['editorialCategory']}` | prioridad `{action['priority']}`"
        f" | motivo: {action['reason']} | accion: {action['recommendedAction']}"
        f" | esperado: {action['expectedResult']} | dificultad: `{action['difficulty']}`{inferred}"
    )


def generate_markdown_report(result: dict[str, Any]) -> str:
    sections_order = [
        "1. Prioridad A: acciones alineadas con el nuevo rumbo del canal.",
        "2. Prioridad B: acciones virales compatibles que pueden atraer tráfico.",
        "3. Prioridad C: contenido heredado o gaming que funciona, pero no debe dirigir la estrategia.",
        "4. Vídeos que merecen segunda parte.",
        "5. Vídeos que merecen artículo en Blogger.",
        "6. Vídeos largos que pueden generar shorts.",
        "7. Shorts que pueden convertirse en vídeo largo.",
        "8. Vídeos que necesitan cambio de título.",
        "9. Vídeos que necesitan cambio de miniatura.",
        "10. Temas que conviene repetir esta semana.",
        "11. Temas que conviene pausar.",
        "12. Plan de acción para los próximos 7 días.",
    ]
    actions = result["actions"]
    by_section: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        by_section.setdefault(action["section"], []).append(action)

    lines = [
        f"# Channel Opportunities - {result['reportDate']}",
        "",
        f"- Fuente principal: `{result['sourceDiagnosisJson']}`",
        f"- Informe base: `{result['sourceDiagnosisReport']}`",
        "- Objetivo: convertir el diagnóstico del canal en una cola editorial accionable, priorizando IA, IA local, agentes, Codex, ComfyUI, hardware IA y tutoriales técnicos.",
        "",
    ]

    for section in sections_order:
        lines.append(f"## {section}")
        lines.append("")
        section_actions = by_section.get(section, [])
        if not section_actions:
            lines.append("- No se detectaron oportunidades sólidas en esta sección con los datos actuales.")
        else:
            lines.extend(_render_action(action) for action in section_actions)
        lines.append("")

    lines.extend(
        [
            "## Notas",
            "",
            "- `legacy_gaming` y `tarkov_directo` se conservan como soporte táctico, no como dirección editorial.",
            "- Las acciones marcadas como `inferida` parten de señales reales de views, retención, watch time o engagement, pero la decisión exacta de título/miniatura no viene directamente de la API.",
            "- No se ha usado Google Custom Search en este flujo.",
        ]
    )
    return "\n".join(lines) + "\n"


def export_actions_csv_rows(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in actions:
        rows.append(
            {
                "section": action["section"],
                "title": action["title"],
                "editorialCategory": action["editorialCategory"],
                "priority": action["priority"],
                "reason": action["reason"],
                "recommendedAction": action["recommendedAction"],
                "expectedResult": action["expectedResult"],
                "difficulty": action["difficulty"],
                "inferred": action["inferred"],
            }
        )
    return rows


def run_channel_opportunities(report_date: dt.date | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    payload, diagnosis_paths = load_diagnosis_payload(report_date)
    resolved_date = report_date or dt.date.fromisoformat(payload["dataset"]["periods"]["30d"]["end"]) + dt.timedelta(days=1)
    result = build_actions(payload, diagnosis_paths, resolved_date)

    stamp = resolved_date.isoformat()
    json_path = OPPORTUNITIES_DATA_DIR / f"channel_opportunities_{stamp}.json"
    csv_path = OPPORTUNITIES_DATA_DIR / f"channel_opportunities_actions_{stamp}.csv"
    report_path = REPORTS_DIR / f"channel_opportunities_{stamp}.md"

    save_json(json_path, result)
    save_csv(csv_path, export_actions_csv_rows(result["actions"]))
    report_path.write_text(generate_markdown_report(result), encoding="utf-8")

    return {"report": report_path, "json": json_path, "csv": csv_path}
