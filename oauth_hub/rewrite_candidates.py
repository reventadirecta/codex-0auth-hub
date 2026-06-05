import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from .opportunities import (
    COMPATIBLE_CATEGORIES,
    LEGACY_CATEGORIES,
    STRATEGIC_CATEGORIES,
    enrich_video_rows,
    find_diagnosis_paths,
    load_diagnosis_payload,
)
from .paths import ROOT


REWRITE_DATA_DIR = ROOT / "data" / "video_rewrite_candidates"
OPPORTUNITIES_DATA_DIR = ROOT / "data" / "channel_opportunities"
REPORTS_DIR = ROOT / "reports"


def ensure_output_dirs() -> None:
    REWRITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def load_opportunities_payload(report_date: dt.date | None = None) -> tuple[dict[str, Any] | None, Path | None]:
    if report_date:
        path = OPPORTUNITIES_DATA_DIR / f"channel_opportunities_{report_date.isoformat()}.json"
        if not path.exists():
            return None, None
        return json.loads(path.read_text(encoding="utf-8")), path

    candidates = sorted(OPPORTUNITIES_DATA_DIR.glob("channel_opportunities_*.json"))
    if not candidates:
        return None, None
    path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8")), path


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


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def title_strength_score(row: dict[str, Any]) -> float:
    title = row.get("title", "")
    score = 0.0
    if len(title) <= 65:
        score += 1.0
    if any(token in title.lower() for token in ["cómo", "como", "guía", "guia", "instala", "configura", "gratis"]):
        score += 1.0
    if title.count("#") >= 3:
        score -= 1.0
    if title.isupper():
        score -= 0.5
    return score


def retention_label(row: dict[str, Any]) -> str:
    retention = row["retention30"]
    if row["format"] == "short" and retention > 100:
        return f"{retention:.1f}% (Short en bucle)"
    return f"{retention:.1f}%"


def action_confidence(row: dict[str, Any], inferred: bool) -> str:
    if row["views30"] >= 400 or row["watch30"] >= 300:
        return "alta" if not inferred else "media"
    if row["views30"] >= 120 or row["watch30"] >= 120 or row["retention30"] >= 45:
        return "media"
    return "baja"


def is_rewrite_candidate(row: dict[str, Any]) -> bool:
    category = row["editorialCategory"]
    strategic = category in STRATEGIC_CATEGORIES
    compatible = category in COMPATIBLE_CATEGORIES
    legacy = category in LEGACY_CATEGORIES

    if row["format"] == "short" and row["views30"] >= 150 and row["retention30"] >= 60:
        return True
    if row["durationSeconds"] >= 300 and row["watch90"] >= 200:
        return True
    if strategic and row["retention30"] >= 45 and row["views30"] < 250:
        return True
    if strategic and row["watch30"] >= 180 and row["retention30"] < 35:
        return True
    if strategic and title_strength_score(row) <= 0 and row["views30"] >= 70:
        return True
    if strategic and row["retention30"] >= 40 and row["viewsPerDay30"] < 8:
        return True
    if strategic and row["durationSeconds"] >= 180 and (row["comments30"] >= 1 or row["watch30"] >= 150):
        return True
    if legacy and row["watch90"] >= 500:
        return True
    if compatible and row["views30"] >= 200:
        return True
    if category == "otros" and row["format"] == "short" and row["views30"] >= 1000 and row["retention30"] >= 120:
        return True
    return False


def problem_and_action(row: dict[str, Any]) -> tuple[str, str, str, str, bool]:
    category = row["editorialCategory"]
    strategic = category in STRATEGIC_CATEGORIES
    legacy = category in LEGACY_CATEGORIES

    if strategic and row["retention30"] >= 45 and row["views30"] < 120:
        return (
            "Buena retención, pocas views",
            f"Retención {retention_label(row)} con solo {row['views30']} views en 30d.",
            "cambiar miniatura" if title_strength_score(row) > 0 else "cambiar título",
            "media",
            True,
        )
    if strategic and row["watch30"] >= 180 and row["retention30"] < 35:
        return (
            "Buen watch time, mal empaquetado probable",
            f"{row['watch30']:.0f} min vistos en 30d pero retención de {retention_label(row)}.",
            "cambiar título",
            "media",
            True,
        )
    if strategic and title_strength_score(row) <= 0 and row["views30"] >= 70:
        return (
            "Vídeo alineado con la nueva estrategia pero con título flojo",
            f"{row['views30']} views en 30d con una categoría estratégica y título poco específico.",
            "cambiar título",
            "baja",
            True,
        )
    if strategic and row["retention30"] >= 40 and row["viewsPerDay30"] < 8:
        return (
            "Vídeo alineado con la nueva estrategia pero con miniatura mejorable",
            f"Retención {retention_label(row)} y solo {row['viewsPerDay30']:.1f} views/día.",
            "cambiar miniatura",
            "media",
            True,
        )
    if row["format"] == "short" and row["views30"] >= 150 and row["retention30"] >= 60:
        return (
            "Short que podría convertirse en vídeo largo",
            f"{row['views30']} views en 30d y retención {retention_label(row)} en formato corto.",
            "convertir en vídeo largo",
            "media",
            False,
        )
    if row["durationSeconds"] >= 300 and row["watch90"] >= 200:
        return (
            "Vídeo largo que podría generar shorts",
            f"{row['watch90']:.0f} min vistos en 90d y duración de {row['durationSeconds']//60} min.",
            "convertir en short",
            "baja",
            True,
        )
    if strategic and row["durationSeconds"] >= 180 and (row["comments30"] >= 1 or row["watch30"] >= 150):
        return (
            "Tutorial que podría convertirse en artículo o serie",
            f"{row['watch30']:.0f} min vistos y {row['comments30']} comentarios en 30d.",
            "hacer segunda parte",
            "media",
            False,
        )
    if legacy and row["watch90"] >= 500:
        return (
            "Vídeo heredado que funciona, pero no debe dirigir la estrategia",
            f"{row['watch90']:.0f} min vistos en 90d dentro de una categoría heredada.",
            "pausar/no tocar",
            "baja",
            False,
        )
    return (
        "Vídeo que merece relanzamiento con nuevo enfoque",
        f"{row['views30']} views en 30d, retención {retention_label(row)} y categoría {category}.",
        "cambiar descripción",
        "media",
        True,
    )


def candidate_priority(row: dict[str, Any]) -> str:
    if row["editorialCategory"] in STRATEGIC_CATEGORIES:
        return "A"
    if row["editorialCategory"] in COMPATIBLE_CATEGORIES:
        return "B"
    if row["editorialCategory"] in LEGACY_CATEGORIES:
        return "C"
    return "B"


def candidate_score(row: dict[str, Any]) -> float:
    base = row["views30"] * 0.3 + row["watch30"] * 0.2 + row["retention30"] * 4 + row["subs30"] * 12
    if row["editorialCategory"] in STRATEGIC_CATEGORIES:
        base += 150
    elif row["editorialCategory"] in COMPATIBLE_CATEGORIES:
        base += 80
    elif row["editorialCategory"] in LEGACY_CATEGORIES:
        base -= 40
    return base


def build_candidates(diagnosis_payload: dict[str, Any], opportunities_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    videos = enrich_video_rows(diagnosis_payload)
    candidates: list[dict[str, Any]] = []

    for row in videos:
        if row["views30"] <= 0 and row["views90"] <= 0:
            continue
        if not is_rewrite_candidate(row):
            continue

        problem, metrics_reason, action_type, difficulty, inferred = problem_and_action(row)
        candidate = {
            "title": row["title"],
            "videoId": row["video"],
            "videoUrl": video_url(row["video"]),
            "editorialCategory": row["editorialCategory"],
            "priority": candidate_priority(row),
            "problemDetected": problem,
            "metricsReason": metrics_reason,
            "recommendedActionType": action_type,
            "confidence": action_confidence(row, inferred),
            "difficulty": difficulty,
            "inferred": inferred,
            "score": candidate_score(row),
            "format": row["format"],
            "daysSincePublished": row["daysSincePublished"],
            "metrics": {
                "views30": row["views30"],
                "watch30": row["watch30"],
                "retention30": row["retention30"],
                "viewsPerDay30": row["viewsPerDay30"],
                "subs30": row["subs30"],
                "comments30": row["comments30"],
                "views90": row["views90"],
                "watch90": row["watch90"],
                "durationSeconds": row["durationSeconds"],
            },
            "analysisSummary": (
                f"{row['views30']} views en 30d, {row['watch30']:.0f} min vistos, "
                f"retención {retention_label(row)}, views/día {row['viewsPerDay30']:.1f}."
            ),
        }
        candidates.append(candidate)

    by_video: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        by_video.setdefault(candidate["videoId"], candidate)

    final_candidates = list(by_video.values())
    final_candidates.sort(key=lambda item: (item["priority"], -item["score"]))

    if opportunities_payload:
        existing_titles = {action["title"] for action in opportunities_payload.get("actions", [])}
        for candidate in final_candidates:
            candidate["mentionedInOpportunities"] = candidate["title"] in existing_titles

    return final_candidates


def _section_pick(candidates: list[dict[str, Any]], predicate, limit: int = 6) -> list[dict[str, Any]]:
    chosen = [item for item in candidates if predicate(item)]
    chosen.sort(key=lambda item: item["score"], reverse=True)
    return chosen[:limit]


def _render_candidate(candidate: dict[str, Any]) -> list[str]:
    inferred = "inferida" if candidate["inferred"] else "directa"
    return [
        f"- **{candidate['title']}** | `{candidate['editorialCategory']}` | prioridad `{candidate['priority']}`",
        f"  URL: {candidate['videoUrl']}",
        f"  Problema: {candidate['problemDetected']}",
        f"  Métricas: {candidate['analysisSummary']}",
        f"  Justificación: {candidate['metricsReason']}",
        f"  Tipo de acción recomendada: `{candidate['recommendedActionType']}`",
        f"  Confianza: `{candidate['confidence']}`",
        f"  Dificultad: `{candidate['difficulty']}`",
        f"  Origen de la recomendación: `{inferred}`",
    ]


def generate_markdown_report(
    report_date: dt.date,
    diagnosis_json: Path,
    opportunities_json: Path | None,
    candidates: list[dict[str, Any]],
) -> str:
    priority_a = _section_pick(candidates, lambda item: item["priority"] == "A", 8)
    priority_b = _section_pick(candidates, lambda item: item["priority"] == "B", 6)
    priority_c = _section_pick(candidates, lambda item: item["priority"] == "C", 6)
    title_changes = _section_pick(candidates, lambda item: item["recommendedActionType"] == "cambiar título", 6)
    thumbnail_changes = _section_pick(candidates, lambda item: item["recommendedActionType"] == "cambiar miniatura", 6)
    second_part = _section_pick(candidates, lambda item: item["recommendedActionType"] == "hacer segunda parte", 6)
    short_to_long = _section_pick(candidates, lambda item: item["recommendedActionType"] == "convertir en vídeo largo", 6)
    long_to_short = _section_pick(candidates, lambda item: item["recommendedActionType"] == "convertir en short", 6)
    do_not_touch = _section_pick(candidates, lambda item: item["recommendedActionType"] == "pausar/no tocar", 6)
    plan = []
    seen = set()
    for bucket in [priority_a[:3], title_changes[:2], short_to_long[:1], long_to_short[:1]]:
        for item in bucket:
            if item["videoId"] in seen:
                continue
            seen.add(item["videoId"])
            plan.append(item)
    plan = plan[:6]

    lines = [
        f"# Video Rewrite Candidates - {report_date.isoformat()}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Fuente principal: `{diagnosis_json}`",
        f"- Fuente secundaria: `{opportunities_json}`" if opportunities_json else "- Fuente secundaria: no disponible",
        f"- Candidatos detectados: {len(candidates)}",
        f"- Prioridad A: {len([item for item in candidates if item['priority'] == 'A'])}",
        f"- Prioridad B: {len([item for item in candidates if item['priority'] == 'B'])}",
        f"- Prioridad C: {len([item for item in candidates if item['priority'] == 'C'])}",
        "",
        "## 2. Top candidatos prioridad A.",
        "",
    ]
    for item in priority_a:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 3. Top candidatos prioridad B.")
    lines.append("")
    for item in priority_b:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 4. Candidatos prioridad C.")
    lines.append("")
    for item in priority_c:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 5. Cambios rápidos de título.")
    lines.append("")
    for item in title_changes:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 6. Cambios rápidos de miniatura.")
    lines.append("")
    for item in thumbnail_changes:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 7. Vídeos que merecen segunda parte.")
    lines.append("")
    for item in second_part:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 8. Shorts que pueden convertirse en vídeo largo.")
    lines.append("")
    for item in short_to_long:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 9. Vídeos largos que pueden generar shorts.")
    lines.append("")
    for item in long_to_short:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 10. Vídeos que conviene no tocar.")
    lines.append("")
    for item in do_not_touch:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 11. Plan de acción recomendado.")
    lines.append("")
    for item in plan:
        lines.extend(_render_candidate(item))
    lines.append("")
    lines.append("## 12. Limitaciones del análisis.")
    lines.append("")
    lines.append("- Este flujo solo analiza señales y no genera cambios reales sobre YouTube.")
    lines.append("- Si faltan impresiones o CTR, el análisis se apoya en views, watch time, retención, views/día y metadatos.")
    lines.append("- En Shorts, YouTube puede devolver retención superior al 100% cuando el vídeo se reproduce en bucle; aquí se conserva ese dato tal como viene de la fuente.")
    lines.append("- Las recomendaciones marcadas como `inferida` dependen de lectura editorial de título, formato o encaje estratégico, no de una métrica directa.")
    lines.append("- No se ha usado Google Custom Search.")
    return "\n".join(lines) + "\n"


def export_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in candidates:
        rows.append(
            {
                "title": item["title"],
                "videoId": item["videoId"],
                "videoUrl": item["videoUrl"],
                "editorialCategory": item["editorialCategory"],
                "priority": item["priority"],
                "problemDetected": item["problemDetected"],
                "metricsReason": item["metricsReason"],
                "recommendedActionType": item["recommendedActionType"],
                "confidence": item["confidence"],
                "difficulty": item["difficulty"],
                "inferred": item["inferred"],
                "views30": item["metrics"]["views30"],
                "watch30": item["metrics"]["watch30"],
                "retention30": item["metrics"]["retention30"],
                "views90": item["metrics"]["views90"],
                "watch90": item["metrics"]["watch90"],
            }
        )
    return rows


def run_video_rewrite_candidates(report_date: dt.date | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    diagnosis_payload, _ = load_diagnosis_payload(report_date)
    diagnosis_paths = find_diagnosis_paths(report_date)
    opportunities_payload, opportunities_path = load_opportunities_payload(report_date)

    resolved_date = report_date or dt.date.fromisoformat(diagnosis_payload["dataset"]["periods"]["30d"]["end"]) + dt.timedelta(days=1)
    candidates = build_candidates(diagnosis_payload, opportunities_payload)

    stamp = resolved_date.isoformat()
    report_path = REPORTS_DIR / f"video_rewrite_candidates_{stamp}.md"
    json_path = REWRITE_DATA_DIR / f"video_rewrite_candidates_{stamp}.json"
    csv_path = REWRITE_DATA_DIR / f"video_rewrite_candidates_{stamp}.csv"

    payload = {
        "reportDate": stamp,
        "sourceDiagnosisJson": str(diagnosis_paths["json"]),
        "sourceOpportunitiesJson": str(opportunities_path) if opportunities_path else None,
        "candidates": candidates,
    }
    save_json(json_path, payload)
    save_csv(csv_path, export_rows(candidates))
    report_path.write_text(
        generate_markdown_report(resolved_date, diagnosis_paths["json"], opportunities_path, candidates),
        encoding="utf-8",
    )

    return {"report": report_path, "json": json_path, "csv": csv_path}
