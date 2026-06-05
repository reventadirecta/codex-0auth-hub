import csv
import datetime as dt
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .diagnosis import parse_iso8601_duration
from .opportunities import enrich_video_rows, load_diagnosis_payload
from .paths import ROOT
from .youtube_api import analytics_query, get_video_details, get_youtube_service


ARCHIVE_DATA_DIR = ROOT / "data" / "content_archive_miner"
DIAGNOSIS_DATA_DIR = ROOT / "data" / "channel_diagnosis"
OPPORTUNITIES_DATA_DIR = ROOT / "data" / "channel_opportunities"
REWRITE_CANDIDATES_DATA_DIR = ROOT / "data" / "video_rewrite_candidates"
REWRITE_PROPOSALS_DATA_DIR = ROOT / "data" / "video_rewrite_proposals"
TAG_INTELLIGENCE_DATA_DIR = ROOT / "data" / "youtube_tag_intelligence"
REPORTS_DIR = ROOT / "reports"

STRATEGIC_KEYWORDS = {
    "ia",
    "ai",
    "ia local",
    "local ai",
    "ollama",
    "codex",
    "hermes",
    "openclaw",
    "agent zero",
    "agents",
    "agente",
    "agentes",
    "comfyui",
    "gpu",
    "vram",
    "hardware",
    "tutorial",
    "tutorials",
    "automatizacion",
    "automatización",
    "workflow",
    "llm",
    "mistral",
    "qwen",
}

LEGACY_KEYWORDS = {
    "tarkov",
    "eft",
    "gaming",
    "gameplay",
    "directo",
    "stream",
    "live",
    "resubido",
    "vod",
    "clip",
}

SENSITIVE_KEYWORDS = {
    "privado",
    "personal",
    "familia",
    "salud",
    "hospital",
    "dinero",
    "deuda",
    "telefono",
    "teléfono",
    "correo",
    "whatsapp",
    "direccion",
    "dirección",
    "documento",
}

CRYPTO_KEYWORDS = {
    "crypto",
    "criptomoneda",
    "criptomonedas",
    "mineria",
    "minería",
    "minar",
    "zcash",
    "bitcoin",
    "ethereum",
    "asic",
    "trading",
    "exchange",
    "wallet",
    "blockchain",
    "btc",
    "eth",
}

AI_HARDWARE_KEYWORDS = {
    "ia local",
    "local ai",
    "ollama",
    "codex",
    "hermes",
    "openclaw",
    "agent zero",
    "agents",
    "agente",
    "agentes",
    "comfyui",
    "llm",
    "mistral",
    "qwen",
}


def ensure_output_dirs() -> None:
    ARCHIVE_DATA_DIR.mkdir(parents=True, exist_ok=True)
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


def normalize_text(*parts: str) -> str:
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip().lower()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9áéíóúñ\-\+]+", text.lower())


def has_any_phrase(text: str, phrases: set[str]) -> bool:
    lower = normalize_text(text)
    return any(phrase in lower for phrase in phrases)


def has_crypto_legacy_signals(text: str) -> bool:
    return has_any_phrase(text, CRYPTO_KEYWORDS)


def has_explicit_ai_hardware_signals(text: str) -> bool:
    lower = normalize_text(text)
    return any(keyword in lower for keyword in AI_HARDWARE_KEYWORDS) and any(
        keyword in lower for keyword in {"hardware", "gpu", "vram", "rtx", "rx", "cuda", "ram", "tarjetas graficas", "tarjetas gráficas"}
    )


def clamp(value: float, low: int = 1, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def load_latest_json(data_dir: Path, prefix: str, report_date: dt.date | None = None) -> tuple[dict[str, Any] | None, Path | None]:
    if report_date:
        path = data_dir / f"{prefix}_{report_date.isoformat()}.json"
        if not path.exists():
            return None, None
        return json.loads(path.read_text(encoding="utf-8")), path

    candidates = sorted(data_dir.glob(f"{prefix}_*.json"))
    if not candidates:
        return None, None
    path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8")), path


def load_related_context(report_date: dt.date | None) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for key, directory, prefix in [
        ("channelOpportunities", OPPORTUNITIES_DATA_DIR, "channel_opportunities"),
        ("videoRewriteCandidates", REWRITE_CANDIDATES_DATA_DIR, "video_rewrite_candidates"),
        ("videoRewriteProposals", REWRITE_PROPOSALS_DATA_DIR, "video_rewrite_proposals"),
        ("youtubeTagIntelligence", TAG_INTELLIGENCE_DATA_DIR, "youtube_tag_intelligence"),
    ]:
        payload, path = load_latest_json(directory, prefix, report_date)
        payloads[key] = {"payload": payload, "path": path}
    return payloads


def load_live_analytics(diagnosis_payload: dict[str, Any]) -> dict[str, Any]:
    periods = diagnosis_payload["dataset"]["periods"]
    start_30 = dt.date.fromisoformat(periods["30d"]["start"])
    end_30 = dt.date.fromisoformat(periods["30d"]["end"])
    start_90 = dt.date.fromisoformat(periods["90d"]["start"])
    end_90 = dt.date.fromisoformat(periods["90d"]["end"])

    metrics = [
        "views",
        "estimatedMinutesWatched",
        "averageViewDuration",
        "averageViewPercentage",
        "likes",
        "comments",
        "subscribersGained",
    ]
    result: dict[str, Any] = {
        "available": False,
        "reason": "",
        "rows30": {},
        "rows90": {},
    }
    try:
        rows_30 = analytics_query(
            start_30,
            end_30,
            metrics=metrics,
            dimensions=["video"],
            sort=["-views"],
            max_results=200,
        )
        rows_90 = analytics_query(
            start_90,
            end_90,
            metrics=metrics,
            dimensions=["video"],
            sort=["-views"],
            max_results=200,
        )
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result

    def _rows_to_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        headers = [item["name"] for item in payload.get("columnHeaders", [])]
        out: dict[str, dict[str, Any]] = {}
        for row in payload.get("rows", []):
            data = dict(zip(headers, row))
            video_id = data.get("video")
            if video_id:
                out[video_id] = data
        return out

    result["available"] = True
    result["rows30"] = _rows_to_map(rows_30)
    result["rows90"] = _rows_to_map(rows_90)
    return result


def load_current_video_details(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    try:
        chunks = [video_ids[idx : idx + 50] for idx in range(0, len(video_ids), 50)]
        for chunk in chunks:
            for item in get_video_details(chunk):
                details[item.get("id", "")] = item
    except Exception:
        return {}
    return details


def build_tag_bank(tag_payload: dict[str, Any] | None) -> set[str]:
    if not tag_payload:
        return set()
    records = tag_payload.get("records", [])
    bank: set[str] = set()
    for record in records:
        if record.get("calibratedScore100", 0) < 60:
            continue
        if record.get("type") not in {"topic_entity", "youtube_tag", "hashtag", "search_phrase"}:
            continue
        term = normalize_text(str(record.get("term", ""))).replace("#", "")
        if term:
            bank.add(term)
    return bank


def infer_content_type(title: str, description: str, duration_seconds: int, format_name: str) -> tuple[str, str]:
    text = normalize_text(title, description)
    if has_crypto_legacy_signals(text) and not has_explicit_ai_hardware_signals(text):
        return "otro", "Contenido crypto/minería heredado; no debe confundirse con hardware IA actual."
    if any(token in text for token in ["resubido", "vod", "replay", "retransmision", "retransmisión"]):
        return "directo resubido", "Se detectan marcas de directo resubido o replay en título/descripcion."
    if any(token in text for token in ["directo", "stream", "live", "en vivo", "direct live"]) or duration_seconds >= 3600:
        return "directo", "El título/descripcion o la duracion apuntan a directo o emision larga."
    if format_name == "short" or duration_seconds <= 60:
        return "short", "Formato corto o duracion igual/superior al umbral de short."
    if any(token in text for token in ["clip", "corte", "fragmento", "momento", "highlight", "highlights"]):
        return "clip", "El texto sugiere un corte o fragmento reutilizable."
    if any(token in text for token in ["tutorial", "guia", "guía", "paso a paso", "instala", "instalar", "configura", "configurar", "setup", "como ", "cómo "]):
        return "tutorial", "El texto apunta a tutorial o guia tecnica."
    if any(token in text for token in ["tarkov", "eft", "gaming", "gameplay", "boss", "pve", "stream"]):
        return "gaming", "Contenido de gaming o Tarkov heredado."
    if any(token in text for token in ["gpu", "vram", "hardware", "rtx", "rx", "ram", "cuda", "cpu", "placa", "grafica", "gráfica"]):
        return "hardware", "El texto menciona hardware, GPU o VRAM."
    if any(
        token in text
        for token in [
            "ia local",
            "local ai",
            "ia",
            "ai",
            "ollama",
            "codex",
            "hermes",
            "openclaw",
            "agent zero",
            "comfyui",
            "llm",
            "mistral",
            "qwen",
        ]
    ):
        return "IA", "El contenido encaja con la nueva linea de IA y agentes."
    return "otro", "No hay una pista clara suficiente para clasificarlo mejor."


def infer_topic_family(text: str) -> str:
    lower = normalize_text(text)
    if has_crypto_legacy_signals(lower) and not has_explicit_ai_hardware_signals(lower):
        return "crypto_legacy"
    if "hermes" in lower:
        return "hermes_agent"
    if "openclaw" in lower:
        return "openclaw"
    if "codex" in lower:
        return "codex"
    if "agent zero" in lower:
        return "agent_zero"
    if "ollama" in lower:
        return "ollama"
    if "comfyui" in lower:
        return "comfyui"
    if any(token in lower for token in ["gpu", "vram", "hardware", "rtx", "rx", "ram", "cuda"]):
        return "hardware_ia"
    if any(token in lower for token in ["tarkov", "eft"]):
        return "tarkov"
    if any(token in lower for token in ["gaming", "gameplay"]):
        return "gaming"
    if any(token in lower for token in ["tutorial", "guia", "guía", "setup", "instala", "configura"]):
        return "tutorial"
    return "other"


def count_keyword_hits(text: str, keywords: set[str]) -> int:
    lower = normalize_text(text)
    return sum(1 for keyword in keywords if keyword in lower)


def build_signal_maps(
    opportunities_payload: dict[str, Any] | None,
    candidates_payload: dict[str, Any] | None,
    proposals_payload: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    maps: dict[str, dict[str, Any]] = {
        "opportunity_by_title": {},
        "candidate_by_id": {},
        "candidate_by_title": {},
        "proposal_by_id": {},
        "proposal_by_title": {},
    }

    if opportunities_payload:
        for action in opportunities_payload.get("actions", []):
            title = action.get("title")
            if title:
                maps["opportunity_by_title"][title] = action

    if candidates_payload:
        for item in candidates_payload.get("candidates", []):
            video_id = item.get("videoId")
            title = item.get("title")
            if video_id:
                maps["candidate_by_id"][video_id] = item
            if title:
                maps["candidate_by_title"][title] = item

    if proposals_payload:
        for analysis in proposals_payload.get("analyses", []):
            candidate = analysis.get("candidate", {})
            video_id = candidate.get("video") or candidate.get("videoId")
            title = candidate.get("title")
            if video_id:
                maps["proposal_by_id"][video_id] = analysis
            if title:
                maps["proposal_by_title"][title] = analysis

    return maps


def source_status(available: bool, mode: str, reason: str = "", details: dict[str, Any] | None = None, blocking: bool = False) -> dict[str, Any]:
    return {
        "available": available,
        "mode": mode,
        "reason": reason,
        "details": details or {},
        "blocking": blocking,
    }


def title_strength(title: str) -> int:
    score = 0
    lower = normalize_text(title)
    if len(title) <= 72:
        score += 2
    if any(token in lower for token in ["como ", "cómo ", "guia", "guía", "tutorial", "paso a paso", "instala", "configura"]):
        score += 3
    if any(token in lower for token in ["ia", "ai", "ollama", "codex", "hermes", "comfyui", "gpu", "vram", "agent"]):
        score += 2
    if title.count("#") >= 3:
        score -= 2
    if title.isupper():
        score -= 1
    return score


def performance_score(row: dict[str, Any]) -> int:
    views30 = float(row.get("views30", 0) or 0)
    views90 = float(row.get("views90", 0) or 0)
    watch30 = float(row.get("watch30", 0) or 0)
    watch90 = float(row.get("watch90", 0) or 0)
    retention30 = float(row.get("retention30", 0) or 0)
    retention90 = float(row.get("retention90", 0) or 0)
    views_per_day = float(row.get("viewsPerDay30", 0) or 0)
    subs30 = float(row.get("subs30", 0) or 0)
    comments30 = float(row.get("comments30", 0) or 0)
    score = (
        min(30.0, math.log1p(views30) * 6)
        + min(16.0, math.log1p(max(watch30, 0.0)) * 3.5)
        + min(12.0, math.log1p(max(watch90, 0.0)) * 2.5)
        + min(18.0, retention30 * 0.3)
        + min(10.0, retention90 * 0.15)
        + min(8.0, views_per_day * 1.2)
        + min(4.0, subs30 * 2.0)
        + min(2.0, comments30 * 0.75)
    )
    return clamp(score)


def strategic_fit_score(row: dict[str, Any], tag_bank: set[str], signals: dict[str, Any]) -> tuple[int, list[str]]:
    text = normalize_text(row["title"], row.get("description", ""), row.get("editorialCategory", ""))
    hits: list[str] = []
    score = 0.0

    content_type = row["contentType"]
    if content_type in {"tutorial", "IA", "hardware"}:
        score += 30
        hits.append(content_type)
    if content_type == "short" and any(token in text for token in ["ia", "ai", "ollama", "codex", "hermes", "comfyui", "gpu", "agent"]):
        score += 15
        hits.append("short_strategic")
    if count_keyword_hits(text, STRATEGIC_KEYWORDS) >= 2:
        score += 30
        hits.append("strategic_keywords")
    elif count_keyword_hits(text, STRATEGIC_KEYWORDS) == 1:
        score += 18
        hits.append("strategic_keyword")

    if row.get("editorialCategory") in {"ia_tutorial", "ia_local", "agentes_autonomos", "codex_automatizacion", "comfyui_video", "hardware_ia_gpu"}:
        score += 22
        hits.append("editorial_category")
    if row.get("priorityBucket") == "A":
        score += 10
        hits.append("priority_a")

    tag_hits = sorted({term for term in tag_bank if term and term in text})
    if tag_hits:
        score += min(15, len(tag_hits) * 3)
        hits.extend(tag_hits[:5])

    opp = signals.get("opportunity")
    if opp and opp.get("priority") == "A":
        score += 12
        hits.append("opportunity_a")
    if signals.get("candidate"):
        score += 8
        hits.append("rewrite_candidate")
    if signals.get("proposal"):
        score += 10
        hits.append("rewrite_proposal")

    if row["privacyStatus"] == "public":
        score += 4
    elif row["privacyStatus"] in {"unlisted", "private"}:
        score -= 4

    return clamp(score), hits[:8]


def historical_value_score(row: dict[str, Any]) -> int:
    age_days = int(row.get("daysSincePublished", 0) or 0)
    views90 = float(row.get("views90", 0) or 0)
    views_lifetime = float(row.get("lifetimeViews", 0) or 0)
    content_type = row["contentType"]
    score = 0.0
    if age_days >= 365:
        score += 20
    if age_days >= 730:
        score += 10
    if age_days >= 1200:
        score += 10
    score += min(25.0, math.log1p(max(views_lifetime, 0.0)) * 4.0)
    score += min(15.0, math.log1p(max(views90, 0.0)) * 3.0)
    if content_type in {"gaming", "directo", "directo resubido"}:
        score += 12
    if any(token in normalize_text(row["title"], row.get("description", "")) for token in ["viral", "shocking", "top", "rank", "meme"]):
        score += 8
    if row.get("editorialCategory") in {"legacy_gaming", "tarkov_directo"}:
        score += 18
    return clamp(score)


def archive_risk_score(row: dict[str, Any], strategic_fit: int) -> int:
    text = normalize_text(row["title"], row.get("description", ""))
    content_type = row["contentType"]
    age_days = int(row.get("daysSincePublished", 0) or 0)
    views30 = float(row.get("views30", 0) or 0)
    views90 = float(row.get("views90", 0) or 0)
    retention30 = float(row.get("retention30", 0) or 0)
    score = 0.0

    if any(token in text for token in SENSITIVE_KEYWORDS):
        score += 40
    if content_type in {"gaming", "directo", "directo resubido"}:
        score += 22
    if content_type == "otro":
        score += 8
    if age_days >= 365 and views90 < 50 and strategic_fit < 45:
        score += 22
    if age_days >= 730 and views30 < 10:
        score += 10
    if retention30 < 25 and views30 < 100:
        score += 10
    if strategic_fit < 35:
        score += 15
    if row.get("topicFamily") == "crypto_legacy":
        score += 18
    if row["privacyStatus"] == "public":
        score += 10
    if row["privacyStatus"] in {"private", "unlisted"}:
        score -= 12
    if views90 >= 500 and content_type in {"gaming", "directo"}:
        score += 8

    return clamp(score)


def update_potential_score(row: dict[str, Any], signals: dict[str, Any]) -> int:
    views30 = float(row.get("views30", 0) or 0)
    watch30 = float(row.get("watch30", 0) or 0)
    retention30 = float(row.get("retention30", 0) or 0)
    views_per_day = float(row.get("viewsPerDay30", 0) or 0)
    title_score = title_strength(row["title"])
    score = 0.0

    if row["contentType"] in {"IA", "tutorial", "hardware"}:
        score += 18
    if views30 >= 50:
        score += 10
    if watch30 >= 120:
        score += 12
    if retention30 >= 30:
        score += 8
    if views_per_day < 8 and views30 >= 30:
        score += 12
    if title_score <= 1:
        score += 16
    if signals.get("candidate") and signals["candidate"].get("recommendedActionType") in {"cambiar título", "cambiar miniatura"}:
        score += 24
    if signals.get("proposal") and signals["proposal"].get("orchestrator", {}).get("finalAction") in {"cambiar título", "cambiar miniatura"}:
        score += 18
    if row.get("editorialCategory") in {"ia_tutorial", "ia_local", "agentes_autonomos", "codex_automatizacion", "comfyui_video", "hardware_ia_gpu"}:
        score += 20

    return clamp(score)


def recycle_potential_score(row: dict[str, Any], signals: dict[str, Any]) -> int:
    views30 = float(row.get("views30", 0) or 0)
    views90 = float(row.get("views90", 0) or 0)
    watch30 = float(row.get("watch30", 0) or 0)
    watch90 = float(row.get("watch90", 0) or 0)
    retention30 = float(row.get("retention30", 0) or 0)
    duration_seconds = int(row.get("durationSeconds", 0) or 0)
    score = 0.0

    if row["contentType"] == "short" and retention30 >= 60 and views30 >= 50:
        score += 35
    if row["contentType"] in {"directo", "directo resubido"} and watch90 >= 200:
        score += 30
    if duration_seconds >= 300 and watch90 >= 120:
        score += 18
    if row["contentType"] in {"IA", "tutorial", "hardware"}:
        score += 14
    if views90 >= 100:
        score += 8
    if signals.get("candidate") and signals["candidate"].get("recommendedActionType") in {"convertir en vídeo largo", "hacer segunda parte"}:
        score += 25
    if signals.get("proposal") and signals["proposal"].get("orchestrator", {}).get("finalAction") in {"convertir en short", "hacer segunda parte"}:
        score += 20
    if row.get("editorialCategory") in {"ia_tutorial", "ia_local", "agentes_autonomos", "codex_automatizacion", "comfyui_video", "hardware_ia_gpu"}:
        score += 15
    if row["contentType"] == "short" and row.get("editorialCategory") in {"legacy_gaming", "tarkov_directo"}:
        score -= 10

    return clamp(score)


def public_value_score(row: dict[str, Any], strategic_fit: int, historical_value: int, archive_risk: int) -> int:
    performance = performance_score(row)
    score = (
        performance * 0.35
        + strategic_fit * 0.35
        + historical_value * 0.2
        - archive_risk * 0.15
    )
    if row["privacyStatus"] == "public":
        score += 6
    if row["contentType"] in {"IA", "tutorial", "hardware"}:
        score += 8
    return clamp(score)


def hide_candidate_score(archive_risk: int, row: dict[str, Any]) -> int:
    score = archive_risk
    if row["privacyStatus"] == "public":
        score += 10
    if row["privacyStatus"] in {"private", "unlisted"}:
        score -= 10
    return clamp(score)


def confidence_level(row: dict[str, Any], signals: dict[str, Any]) -> str:
    source_count = 1
    if row.get("privacyStatus") != "unknown":
        source_count += 1
    if signals.get("opportunity"):
        source_count += 1
    if signals.get("candidate"):
        source_count += 1
    if signals.get("proposal"):
        source_count += 1
    if row.get("tagMatches"):
        source_count += 1
    if row.get("liveAnalyticsUsed"):
        source_count += 1

    if source_count >= 5 or row["publicValueScore"] >= 70 or row["archiveRiskScore"] >= 70:
        return "alta"
    if source_count >= 3 or row["publicValueScore"] >= 50 or row["archiveRiskScore"] >= 50:
        return "media"
    return "baja"


def recommend_action(row: dict[str, Any], signals: dict[str, Any]) -> tuple[str, str, str]:
    strategic_fit = row["strategicFitScore"]
    public_value = row["publicValueScore"]
    archive_risk = row["archiveRiskScore"]
    recycle = row["recyclePotentialScore"]
    update = row["updatePotentialScore"]
    historical = row["historicalValueScore"]
    privacy = row["privacyStatus"]
    content_type = row["contentType"]
    text = normalize_text(row["title"], row.get("description", ""))

    sensitive = any(token in text for token in SENSITIVE_KEYWORDS)
    conflicting = bool(signals.get("candidate")) and bool(signals.get("proposal")) and signals["candidate"].get("recommendedActionType") != signals["proposal"].get("orchestrator", {}).get("finalAction")

    if sensitive or (privacy == "public" and archive_risk >= 80):
        return "consider_private", "A", "El contenido puede dañar la marca o genera demasiado riesgo si sigue público."
    if privacy == "public" and archive_risk >= 65 and content_type in {"gaming", "directo", "directo resubido"}:
        return "consider_unlisted", "A", "Contenido público heredado que puede confundir la nueva etapa del canal."
    if privacy == "public" and strategic_fit >= 70 and update >= 60:
        return "keep_public_update_packaging", "A", "Tema alineado con la nueva línea pero con empaque mejorable."
    if privacy == "public" and strategic_fit >= 70 and public_value >= 65:
        return "keep_public", "A", "Encaja con IA, agentes o hardware y aporta valor público claro."
    if privacy == "public" and historical >= 70 and archive_risk < 55:
        return "keep_public_historical_value", "B", "Tiene valor de archivo, trayectoria o pieza histórica reconocible."
    if recycle >= 72 and content_type == "short":
        return "recycle_as_longform", "A", "Short con señal suficiente para convertirse en vídeo largo."
    if recycle >= 72 and content_type in {"directo", "directo resubido", "IA", "tutorial", "hardware"}:
        return "recycle_as_short", "A", "Material largo con cortes potenciales para shorts."
    if recycle >= 72 and content_type in {"gaming", "otro"} and historical >= 60:
        return "recycle_as_short", "B", "Hay material reutilizable, aunque no sea el eje estratégico."
    if content_type in {"tutorial", "IA", "hardware"} and update >= 65:
        return "turn_into_article", "A", "Buen candidato para documento evergreen o post técnico."
    if privacy == "public" and archive_risk >= 55:
        return "consider_unlisted", "B", "La pieza puede quedarse accesible por enlace pero no conviene empujarla."
    if privacy == "public" and update >= 55 and strategic_fit >= 55:
        return "keep_public_update_packaging", "B", "Merece una revisión de empaquetado antes de tomar otra decisión."
    if privacy in {"private", "unlisted"} and strategic_fit >= 60 and public_value >= 55:
        return "manual_review", "B", "Hay valor, pero conviene revisar primero el contexto real y el estado actual."
    if conflicting:
        return "manual_review", "B", "Hay señales cruzadas entre fuentes y merece revisión manual."
    if archive_risk < 35 and public_value < 35 and historical < 35:
        return "ignore_do_not_touch", "C", "No hay suficiente señal para invertir tiempo ahora."
    return "manual_review", "B", "La señal es útil, pero no suficiente para una decisión automática."


def build_video_row(
    base_row: dict[str, Any],
    current_details: dict[str, Any] | None,
    analytics_rows30: dict[str, Any],
    analytics_rows90: dict[str, Any],
    signals: dict[str, Any],
    tag_bank: set[str],
) -> dict[str, Any]:
    video_id = base_row["video"]
    detail_snippet = (current_details or {}).get("snippet", {})
    detail_status = (current_details or {}).get("status", {})
    detail_stats = (current_details or {}).get("statistics", {})
    detail_content = (current_details or {}).get("contentDetails", {})

    title = detail_snippet.get("title") or base_row.get("title", "")
    description = detail_snippet.get("description") or base_row.get("description", "")
    published_at = detail_snippet.get("publishedAt") or base_row.get("publishedAt", "")
    duration_seconds = base_row.get("durationSeconds", 0) or 0
    if detail_content.get("duration"):
        duration_match = re.match(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$", detail_content["duration"])
        if duration_match:
            duration_seconds = (
                int(duration_match.group("hours") or 0) * 3600
                + int(duration_match.group("minutes") or 0) * 60
                + int(duration_match.group("seconds") or 0)
            )

    row = dict(base_row)
    row.update(
        {
            "videoId": video_id,
            "videoUrl": f"https://www.youtube.com/watch?v={video_id}",
            "title": title,
            "description": description,
            "publishedAt": published_at,
            "durationSeconds": int(duration_seconds or 0),
            "privacyStatus": detail_status.get("privacyStatus", "unknown"),
            "currentTitle": title,
            "currentDescription": description,
            "currentViews": int(detail_stats.get("viewCount", row.get("lifetimeViews", 0)) or 0),
            "currentLikes": int(detail_stats.get("likeCount", row.get("lifetimeLikes", 0)) or 0),
            "currentComments": int(detail_stats.get("commentCount", row.get("lifetimeComments", 0)) or 0),
            "liveAnalyticsUsed": False,
        }
    )

    row["views30"] = int(analytics_rows30.get(video_id, {}).get("views", row.get("views30", 0)) or 0)
    row["watch30"] = float(analytics_rows30.get(video_id, {}).get("estimatedMinutesWatched", row.get("watch30", 0)) or 0.0)
    row["retention30"] = float(analytics_rows30.get(video_id, {}).get("averageViewPercentage", row.get("retention30", 0)) or 0.0)
    row["likes30"] = int(analytics_rows30.get(video_id, {}).get("likes", row.get("likes30", 0)) or 0)
    row["comments30"] = int(analytics_rows30.get(video_id, {}).get("comments", row.get("comments30", 0)) or 0)
    row["subs30"] = int(analytics_rows30.get(video_id, {}).get("subscribersGained", row.get("subs30", 0)) or 0)
    row["views90"] = int(analytics_rows90.get(video_id, {}).get("views", row.get("views90", 0)) or 0)
    row["watch90"] = float(analytics_rows90.get(video_id, {}).get("estimatedMinutesWatched", row.get("watch90", 0)) or 0.0)
    row["retention90"] = float(analytics_rows90.get(video_id, {}).get("averageViewPercentage", row.get("retention90", 0)) or 0.0)
    row["likes90"] = int(analytics_rows90.get(video_id, {}).get("likes", row.get("likes90", 0)) or 0)
    row["comments90"] = int(analytics_rows90.get(video_id, {}).get("comments", row.get("comments90", 0)) or 0)
    row["subs90"] = int(analytics_rows90.get(video_id, {}).get("subscribersGained", row.get("subs90", 0)) or 0)
    row["viewsPerDay30"] = float(row["views30"]) / max(int(row.get("daysSincePublished", 1) or 1), 1)
    row["viewsPerDay90"] = float(row["views90"]) / max(int(row.get("daysSincePublished", 1) or 1), 1)
    row["watchMinutesPerView30"] = float(row["watch30"]) / max(int(row["views30"] or 0), 1)
    row["watchMinutesPerView90"] = float(row["watch90"]) / max(int(row["views90"] or 0), 1)
    row["format"] = row.get("format") or base_row.get("format") or ("short" if int(row["durationSeconds"]) <= 60 else "standard")
    row["contentType"], row["contentTypeReason"] = infer_content_type(title, description, int(row["durationSeconds"]), row["format"])
    row["topicFamily"] = infer_topic_family(f"{title} {description}")
    row["tagMatches"] = sorted({term for term in tag_bank if term and term in normalize_text(title, description)})
    if row["topicFamily"] == "crypto_legacy":
        row["alignedWithNewDirection"] = False
        if row["contentType"] == "hardware":
            row["contentType"] = "otro"
            row["contentTypeReason"] = "Contenido crypto/minería heredado; no debe clasificarse como hardware IA por defecto."
    elif row["contentType"] == "hardware":
        row["alignedWithNewDirection"] = has_explicit_ai_hardware_signals(f"{title} {description}")

    signals_for_row = {
        "opportunity": signals["opportunity_by_title"].get(title),
        "candidate": signals["candidate_by_id"].get(video_id) or signals["candidate_by_title"].get(title),
        "proposal": signals["proposal_by_id"].get(video_id) or signals["proposal_by_title"].get(title),
    }

    if signals_for_row["proposal"]:
        row["proposalAction"] = signals_for_row["proposal"].get("orchestrator", {}).get("finalAction", "")
        row["proposalTitle"] = signals_for_row["proposal"].get("orchestrator", {}).get("recommendedTitle", "")
        row["globalRepetitionPenalty"] = int(signals_for_row["proposal"].get("orchestrator", {}).get("globalRepetitionPenalty", 0) or 0)
        row["specificityReason"] = signals_for_row["proposal"].get("orchestrator", {}).get("specificityReason", "")
        row["reusedPatternDetected"] = bool(signals_for_row["proposal"].get("orchestrator", {}).get("reusedPatternDetected", False))
    else:
        row["proposalAction"] = ""
        row["proposalTitle"] = ""
        row["globalRepetitionPenalty"] = 0
        row["specificityReason"] = ""
        row["reusedPatternDetected"] = False

    row["strategicFitScore"], row["strategicFitSignals"] = strategic_fit_score(row, tag_bank, signals_for_row)
    row["historicalValueScore"] = historical_value_score(row)
    row["archiveRiskScore"] = archive_risk_score(row, row["strategicFitScore"])
    row["publicValueScore"] = public_value_score(row, row["strategicFitScore"], row["historicalValueScore"], row["archiveRiskScore"])
    row["updatePotentialScore"] = update_potential_score(row, signals_for_row)
    row["recyclePotentialScore"] = recycle_potential_score(row, signals_for_row)
    row["hideCandidateScore"] = hide_candidate_score(row["archiveRiskScore"], row)
    row["recommendation"], row["priority"], row["recommendationReason"] = recommend_action(row, signals_for_row)
    row["confidence"] = confidence_level(row, signals_for_row)
    row["signalsUsed"] = [
        "channel_diagnosis",
        "youtube_data_api" if row["privacyStatus"] != "unknown" else "diagnosis_only",
        "youtube_analytics_api" if row.get("liveAnalyticsUsed") else "diagnosis_metrics",
        "channel_opportunities" if signals_for_row["opportunity"] else "",
        "video_rewrite_candidates" if signals_for_row["candidate"] else "",
        "video_rewrite_proposals" if signals_for_row["proposal"] else "",
        "youtube_tag_intelligence" if row["tagMatches"] else "",
    ]
    row["signalsUsed"] = [item for item in row["signalsUsed"] if item]
    row["currentPrivacyKnown"] = row["privacyStatus"] != "unknown"
    return row


def build_records(report_date: dt.date | None = None) -> dict[str, Any]:
    diagnosis_payload, diagnosis_paths = load_diagnosis_payload(report_date)
    resolved_date = report_date or dt.date.fromisoformat(diagnosis_payload["dataset"]["periods"]["30d"]["end"]) + dt.timedelta(days=1)
    related = load_related_context(report_date or resolved_date)

    opportunities_payload = related["channelOpportunities"]["payload"]
    candidates_payload = related["videoRewriteCandidates"]["payload"]
    proposals_payload = related["videoRewriteProposals"]["payload"]
    tag_payload = related["youtubeTagIntelligence"]["payload"]
    tag_bank = build_tag_bank(tag_payload)

    base_rows = enrich_video_rows(diagnosis_payload)
    current_details = load_current_video_details([row["video"] for row in base_rows])
    analytics = load_live_analytics(diagnosis_payload)

    signals = build_signal_maps(opportunities_payload, candidates_payload, proposals_payload)
    if analytics["available"]:
        analytics_rows30 = analytics["rows30"]
        analytics_rows90 = analytics["rows90"]
    else:
        analytics_rows30 = {}
        analytics_rows90 = {}

    records = [
        build_video_row(row, current_details.get(row["video"]), analytics_rows30, analytics_rows90, signals, tag_bank)
        for row in base_rows
    ]

    if analytics["available"]:
        for record in records:
            record["liveAnalyticsUsed"] = True

    records.sort(key=lambda item: (-item["publicValueScore"], -item["strategicFitScore"], -item["views90"], item["title"].lower()))

    source_availability = {
        "channelDiagnosis": source_status(True, "used", details={"videos": len(base_rows)}, blocking=False),
        "youtubeDataOwn": source_status(
            bool(current_details),
            "used" if current_details else "skipped",
            "" if current_details else "YouTube Data API video details unavailable, falling back to diagnosis metadata.",
            details={"videos": len(current_details)},
            blocking=False,
        ),
        "youtubeAnalyticsOwn": source_status(
            analytics["available"],
            "used" if analytics["available"] else "skipped",
            "" if analytics["available"] else analytics["reason"] or "YouTube Analytics query unavailable, falling back to diagnosis metrics.",
            details={"rows30": len(analytics["rows30"]), "rows90": len(analytics["rows90"])} if analytics["available"] else {},
            blocking=False,
        ),
        "channelOpportunities": source_status(bool(opportunities_payload), "used" if opportunities_payload else "skipped", details={"path": str(related["channelOpportunities"]["path"]) if related["channelOpportunities"]["path"] else ""}, blocking=False),
        "videoRewriteCandidates": source_status(bool(candidates_payload), "used" if candidates_payload else "skipped", details={"path": str(related["videoRewriteCandidates"]["path"]) if related["videoRewriteCandidates"]["path"] else ""}, blocking=False),
        "videoRewriteProposals": source_status(bool(proposals_payload), "used" if proposals_payload else "skipped", details={"path": str(related["videoRewriteProposals"]["path"]) if related["videoRewriteProposals"]["path"] else ""}, blocking=False),
        "youtubeTagIntelligence": source_status(bool(tag_payload), "used" if tag_payload else "skipped", details={"path": str(related["youtubeTagIntelligence"]["path"]) if related["youtubeTagIntelligence"]["path"] else ""}, blocking=False),
    }

    recommendation_counts = Counter(record["recommendation"] for record in records)
    type_counts = Counter(record["contentType"] for record in records)
    priority_counts = Counter(record["priority"] for record in records)

    return {
        "reportDate": resolved_date.isoformat(),
        "sourcePaths": {
            "channelDiagnosisJson": str(diagnosis_paths["json"]),
            "channelDiagnosisReport": str(diagnosis_paths["report"]),
            "channelOpportunitiesJson": str(related["channelOpportunities"]["path"]) if related["channelOpportunities"]["path"] else None,
            "videoRewriteCandidatesJson": str(related["videoRewriteCandidates"]["path"]) if related["videoRewriteCandidates"]["path"] else None,
            "videoRewriteProposalsJson": str(related["videoRewriteProposals"]["path"]) if related["videoRewriteProposals"]["path"] else None,
            "youtubeTagIntelligenceJson": str(related["youtubeTagIntelligence"]["path"]) if related["youtubeTagIntelligence"]["path"] else None,
        },
        "sourceAvailability": source_availability,
        "summary": {
            "totalVideos": len(records),
            "typeCounts": dict(type_counts),
            "recommendationCounts": dict(recommendation_counts),
            "priorityCounts": dict(priority_counts),
            "publicPrivacyCounts": dict(Counter(record["privacyStatus"] for record in records)),
        },
        "records": records,
    }


def record_line(record: dict[str, Any]) -> str:
    scores = (
        f"public {record['publicValueScore']}",
        f"risk {record['archiveRiskScore']}",
        f"fit {record['strategicFitScore']}",
        f"recycle {record['recyclePotentialScore']}",
        f"update {record['updatePotentialScore']}",
        f"historical {record['historicalValueScore']}",
        f"hide {record['hideCandidateScore']}",
    )
    return (
        f"- **{record['title']}** | URL `{record['videoUrl']}` | fecha `{record.get('publishedAt', '')[:10]}` | tipo `{record['contentType']}`"
        f" | privacidad `{record['privacyStatus']}` | recomendacion `{record['recommendation']}` | prioridad `{record['priority']}`"
        f" | scores: {', '.join(scores)} | confianza `{record['confidence']}` | motivo: {record['recommendationReason']}"
        f" | datos: views30 {record['views30']}, watch30 {record['watch30']:.0f}, retention30 {record['retention30']:.1f}%, views90 {record['views90']}, watch90 {record['watch90']:.0f}"
        f" | fuentes: {', '.join(record['signalsUsed'])}"
    )


def section_records(records: list[dict[str, Any]], predicate, sort_key, limit: int = 10) -> list[dict[str, Any]]:
    subset = [record for record in records if predicate(record)]
    subset.sort(key=sort_key, reverse=True)
    return subset[:limit]


def build_manual_batches(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batch1 = section_records(
        records,
        lambda record: record["priority"] == "A" and record["recommendation"] in {"manual_review", "consider_unlisted", "consider_private", "keep_public_update_packaging"},
        lambda record: (record["archiveRiskScore"], record["recyclePotentialScore"], record["publicValueScore"]),
        6,
    )
    batch2 = section_records(
        records,
        lambda record: record["priority"] == "B" and record["recommendation"] in {"manual_review", "consider_unlisted", "consider_private", "keep_public_historical_value"},
        lambda record: (record["historicalValueScore"], record["archiveRiskScore"], record["publicValueScore"]),
        6,
    )
    batch3 = section_records(
        records,
        lambda record: record["priority"] == "C" or record["contentType"] in {"gaming", "directo", "directo resubido"},
        lambda record: (record["archiveRiskScore"], record["historicalValueScore"], record["views90"]),
        6,
    )
    return [
        {"batch": "1", "title": "Vídeos públicos que pueden dañar o redirigir la etapa actual", "items": batch1},
        {"batch": "2", "title": "Vídeos con valor histórico o señales cruzadas", "items": batch2},
        {"batch": "3", "title": "Contenido heredado de bajo valor estratégico", "items": batch3},
    ]


def build_report(result: dict[str, Any]) -> str:
    records = result["records"]
    summary = result["summary"]
    source_availability = result["sourceAvailability"]

    def top(section_records_list: list[dict[str, Any]], headline: str) -> list[str]:
        lines = [headline, ""]
        if not section_records_list:
            lines.append("- No hay suficientes vídeos con esta etiqueta para mostrar un top sólido.")
            lines.append("")
            return lines
        lines.extend(record_line(record) for record in section_records_list)
        lines.append("")
        return lines

    keep_public = section_records(records, lambda record: record["recommendation"] == "keep_public", lambda record: (record["publicValueScore"], record["strategicFitScore"], record["views90"]), 10)
    keep_update = section_records(records, lambda record: record["recommendation"] == "keep_public_update_packaging", lambda record: (record["updatePotentialScore"], record["publicValueScore"], record["views30"]), 10)
    recycle_candidates = section_records(records, lambda record: record["recommendation"] in {"recycle_as_short", "recycle_as_longform"}, lambda record: (record["recyclePotentialScore"], record["views90"], record["watch90"]), 10)
    recycle_shorts = section_records(records, lambda record: record["recommendation"] == "recycle_as_short", lambda record: (record["recyclePotentialScore"], record["watch90"], record["views90"]), 10)
    article_candidates = section_records(records, lambda record: record["recommendation"] == "turn_into_article", lambda record: (record["updatePotentialScore"], record["strategicFitScore"], record["views30"]), 10)
    unlisted_candidates = section_records(records, lambda record: record["recommendation"] == "consider_unlisted", lambda record: (record["hideCandidateScore"], record["archiveRiskScore"], record["views90"]), 10)
    private_or_review = section_records(records, lambda record: record["recommendation"] in {"consider_private", "manual_review"}, lambda record: (record["hideCandidateScore"], record["archiveRiskScore"], record["publicValueScore"]), 10)
    historical_candidates = section_records(records, lambda record: record["historicalValueScore"] >= 50, lambda record: (record["historicalValueScore"], record["publicValueScore"], record["views90"]), 10)
    confusing_candidates = section_records(records, lambda record: record["archiveRiskScore"] >= 55, lambda record: (record["archiveRiskScore"], record["hideCandidateScore"], record["views90"]), 10)
    strategic_candidates = section_records(records, lambda record: record["strategicFitScore"] >= 60, lambda record: (record["strategicFitScore"], record["publicValueScore"], record["views90"]), 10)
    no_touch = section_records(records, lambda record: record["recommendation"] == "ignore_do_not_touch", lambda record: (record["publicValueScore"], -record["archiveRiskScore"], record["views90"]), 10)

    recommendation_order = [
        "keep_public",
        "keep_public_update_packaging",
        "keep_public_historical_value",
        "recycle_as_short",
        "recycle_as_longform",
        "turn_into_article",
        "manual_review",
        "consider_unlisted",
        "consider_private",
        "ignore_do_not_touch",
    ]

    lines = [
        f"# Content Archive Miner - {result['reportDate']}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Total de videos analizados: {summary['totalVideos']}",
        f"- Recomendaciones principales: keep_public {summary['recommendationCounts'].get('keep_public', 0)}, update_packaging {summary['recommendationCounts'].get('keep_public_update_packaging', 0)}, historical {summary['recommendationCounts'].get('keep_public_historical_value', 0)}, recycle_short {summary['recommendationCounts'].get('recycle_as_short', 0)}, recycle_longform {summary['recommendationCounts'].get('recycle_as_longform', 0)}, article {summary['recommendationCounts'].get('turn_into_article', 0)}, manual_review {summary['recommendationCounts'].get('manual_review', 0)}, unlisted {summary['recommendationCounts'].get('consider_unlisted', 0)}, private {summary['recommendationCounts'].get('consider_private', 0)}, ignore {summary['recommendationCounts'].get('ignore_do_not_touch', 0)}.",
        f"- Tipos dominantes: {', '.join(f'`{key}` {value}' for key, value in sorted(summary['typeCounts'].items(), key=lambda item: (-item[1], item[0])))}",
        f"- Estados de privacidad detectados: {', '.join(f'`{key}` {value}' for key, value in sorted(summary['publicPrivacyCounts'].items(), key=lambda item: (-item[1], item[0])))}",
        "",
        "## 2. Fuentes usadas.",
        "",
    ]
    for key, payload in source_availability.items():
        status = "sí" if payload["available"] else "no"
        reason = f" | motivo: {payload['reason']}" if payload["reason"] else ""
        detail_bits = []
        for d_key, d_value in payload.get("details", {}).items():
            detail_bits.append(f"{d_key}={d_value}")
        detail_text = f" | detalles: {', '.join(detail_bits)}" if detail_bits else ""
        lines.append(f"- {key}: `{payload['mode']}` | disponible: {status}{reason}{detail_text}")
    lines.extend([
        "",
        "## 3. Limitaciones.",
        "",
        "- La decisión final siempre debe ser manual; el flujo solo recomienda.",
        "- Si YouTube Analytics no responde, el sistema se apoya en el diagnóstico previo para no bloquear el archivo.",
        "- Las métricas de retención disponibles son medias, no la curva completa segundo a segundo.",
        "- No se usa Google Custom Search en este flujo.",
        "- Las clasificaciones de tipo son inferidas por texto, duración y contexto del vídeo.",
        "",
        "## 4. Total de vídeos analizados.",
        "",
        f"- {summary['totalVideos']} vídeos.",
        "",
        "## 5. Distribución por tipo.",
        "",
    ])
    for key, value in sorted(summary["typeCounts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{key}`: {value}")
    lines.extend([
        "",
        "## 6. Distribución por recomendación.",
        "",
    ])
    for key in recommendation_order:
        if key in summary["recommendationCounts"]:
            lines.append(f"- `{key}`: {summary['recommendationCounts'][key]}")
    lines.extend([
        "",
        "## 7. Top vídeos que conviene mantener públicos.",
        "",
    ])
    lines.extend(record_line(record) for record in keep_public) if keep_public else lines.append("- No hay suficientes candidatos claros para keep_public.")
    lines.extend([
        "",
        "## 8. Top vídeos que conviene actualizar.",
        "",
    ])
    lines.extend(record_line(record) for record in keep_update) if keep_update else lines.append("- No hay suficientes candidatos claros para update_packaging.")
    lines.extend([
        "",
        "## 9. Top vídeos que conviene reciclar.",
        "",
    ])
    lines.extend(record_line(record) for record in recycle_candidates) if recycle_candidates else lines.append("- No hay suficientes candidatos claros para reciclar.")
    lines.extend([
        "",
        "## 10. Top vídeos candidatos a shorts.",
        "",
    ])
    lines.extend(record_line(record) for record in recycle_shorts) if recycle_shorts else lines.append("- No hay suficientes candidatos claros a short.")
    lines.extend([
        "",
        "## 11. Top vídeos candidatos a artículo.",
        "",
    ])
    lines.extend(record_line(record) for record in article_candidates) if article_candidates else lines.append("- No hay suficientes candidatos claros a artículo.")
    lines.extend([
        "",
        "## 12. Top candidatos a no listado.",
        "",
    ])
    lines.extend(record_line(record) for record in unlisted_candidates) if unlisted_candidates else lines.append("- No hay suficientes candidatos claros a no listado.")
    lines.extend([
        "",
        "## 13. Top candidatos a privado o revisión manual.",
        "",
    ])
    lines.extend(record_line(record) for record in private_or_review) if private_or_review else lines.append("- No hay suficientes candidatos claros a privado o revisión.")
    lines.extend([
        "",
        "## 14. Contenido heredado con valor histórico.",
        "",
    ])
    lines.extend(record_line(record) for record in historical_candidates) if historical_candidates else lines.append("- No hay suficiente valor histórico para destacar piezas concretas.")
    lines.extend([
        "",
        "## 15. Contenido que puede confundir la nueva etapa.",
        "",
    ])
    lines.extend(record_line(record) for record in confusing_candidates) if confusing_candidates else lines.append("- No hay suficientes piezas claramente confusas con la nueva etapa.")
    lines.extend([
        "",
        "## 16. Contenido alineado con IA, agentes o hardware.",
        "",
    ])
    lines.extend(record_line(record) for record in strategic_candidates) if strategic_candidates else lines.append("- No hay suficiente masa estratégica para destacar piezas concretas.")
    lines.extend([
        "",
        "## 17. Plan de revisión manual por tandas.",
        "",
    ])
    for batch in build_manual_batches(records):
        lines.append(f"- **Tanda {batch['batch']}**: {batch['title']}")
        if batch["items"]:
            for item in batch["items"]:
                lines.append(f"  - {item['title']} | `{item['recommendation']}` | `{item['contentType']}` | public {item['publicValueScore']} | risk {item['archiveRiskScore']} | fit {item['strategicFitScore']}")
        else:
            lines.append("  - Sin candidatos fuertes en esta tanda.")
    lines.extend([
        "",
        "## 18. Qué NO tocar todavía.",
        "",
    ])
    if no_touch:
        lines.extend(record_line(record) for record in no_touch)
    else:
        lines.append("- No hay suficientes piezas marcadas como `ignore_do_not_touch`.")
    lines.extend([
        "",
        "## 19. Siguiente uso dentro del hub.",
        "",
        "- Reutilizar esta clasificación para decidir qué piezas alimentan `channel_opportunities` y qué piezas deben quedarse solo como archivo histórico.",
        "- Cruzar `consider_unlisted` y `consider_private` con futuras tandas de curado manual antes de tocar nada en YouTube.",
        "- Enlazar los vídeos `keep_public_update_packaging` y `turn_into_article` con `video_rewrite_candidates` y Blogger para reempaquetar sin perder contexto.",
        "- Usar la capa de archivo como filtro previo antes de producir más contenidos de canal o hacer pruning editorial.",
    ])
    return "\n".join(lines) + "\n"


def export_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "videoId": record["videoId"],
                "videoUrl": record["videoUrl"],
                "title": record["title"],
                "publishedAt": record["publishedAt"],
                "durationSeconds": record["durationSeconds"],
                "contentType": record["contentType"],
                "contentTypeReason": record["contentTypeReason"],
                "privacyStatus": record["privacyStatus"],
                "recommendation": record["recommendation"],
                "priority": record["priority"],
                "publicValueScore": record["publicValueScore"],
                "archiveRiskScore": record["archiveRiskScore"],
                "strategicFitScore": record["strategicFitScore"],
                "recyclePotentialScore": record["recyclePotentialScore"],
                "updatePotentialScore": record["updatePotentialScore"],
                "historicalValueScore": record["historicalValueScore"],
                "hideCandidateScore": record["hideCandidateScore"],
                "confidence": record["confidence"],
                "recommendationReason": record["recommendationReason"],
                "views30": record["views30"],
                "watch30": record["watch30"],
                "retention30": record["retention30"],
                "views90": record["views90"],
                "watch90": record["watch90"],
                "retention90": record["retention90"],
                "viewsPerDay30": record["viewsPerDay30"],
                "viewsPerDay90": record["viewsPerDay90"],
                "likes30": record["likes30"],
                "comments30": record["comments30"],
                "subs30": record["subs30"],
                "likes90": record["likes90"],
                "comments90": record["comments90"],
                "subs90": record["subs90"],
                "signalsUsed": " | ".join(record["signalsUsed"]),
                "tagMatches": " | ".join(record["tagMatches"]),
                "globalRepetitionPenalty": record["globalRepetitionPenalty"],
                "specificityReason": record["specificityReason"],
                "reusedPatternDetected": record["reusedPatternDetected"],
                "proposalAction": record["proposalAction"],
                "proposalTitle": record["proposalTitle"],
                "topicFamily": record["topicFamily"],
            }
        )
    return rows


def filter_rows(records: list[dict[str, Any]], recommendations: set[str]) -> list[dict[str, Any]]:
    return [record for record in records if record["recommendation"] in recommendations]


def run_content_archive_miner(report_date: dt.date | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    result = build_records(report_date)
    stamp = result["reportDate"]

    json_path = ARCHIVE_DATA_DIR / f"content_archive_miner_{stamp}.json"
    csv_path = ARCHIVE_DATA_DIR / f"archive_recommendations_{stamp}.csv"
    public_csv_path = ARCHIVE_DATA_DIR / f"public_keep_candidates_{stamp}.csv"
    unlisted_csv_path = ARCHIVE_DATA_DIR / f"unlisted_candidates_{stamp}.csv"
    private_csv_path = ARCHIVE_DATA_DIR / f"private_review_candidates_{stamp}.csv"
    recycle_csv_path = ARCHIVE_DATA_DIR / f"recycle_candidates_{stamp}.csv"
    report_path = REPORTS_DIR / f"content_archive_miner_{stamp}.md"

    save_json(json_path, result)
    save_csv(csv_path, export_rows(result["records"]))
    save_csv(public_csv_path, export_rows(filter_rows(result["records"], {"keep_public", "keep_public_update_packaging", "keep_public_historical_value"})))
    save_csv(unlisted_csv_path, export_rows(filter_rows(result["records"], {"consider_unlisted"})))
    save_csv(private_csv_path, export_rows(filter_rows(result["records"], {"consider_private", "manual_review"})))
    save_csv(recycle_csv_path, export_rows(filter_rows(result["records"], {"recycle_as_short", "recycle_as_longform"})))
    report_path.write_text(build_report(result), encoding="utf-8")

    return {
        "report": report_path,
        "json": json_path,
        "csv": csv_path,
        "public_csv": public_csv_path,
        "unlisted_csv": unlisted_csv_path,
        "private_csv": private_csv_path,
        "recycle_csv": recycle_csv_path,
    }


def load_latest_json_payload(data_dir: Path, prefix: str, report_date: dt.date | None = None) -> tuple[dict[str, Any] | None, Path | None]:
    if report_date:
        path = data_dir / f"{prefix}_{report_date.isoformat()}.json"
        if not path.exists():
            return None, None
        return json.loads(path.read_text(encoding="utf-8")), path

    candidates = sorted(data_dir.glob(f"{prefix}_*.json"))
    if not candidates:
        return None, None
    path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8")), path


def _extract_video_id(item: dict[str, Any]) -> str:
    return str(item.get("videoId") or item.get("video") or item.get("id") or "")


def _merge_video_sources(*sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for video_id, row in source.items():
            if not video_id:
                continue
            target = merged.setdefault(video_id, {})
            target.update({key: value for key, value in row.items() if value not in (None, "", [], {})})
    return merged


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def fetch_api_inventory() -> dict[str, Any]:
    youtube = get_youtube_service()
    channel_response = youtube.channels().list(part="contentDetails,snippet,statistics", mine=True).execute()
    channel_items = channel_response.get("items", [])
    if not channel_items:
        raise RuntimeError("No authenticated YouTube channel returned by API.")
    channel = channel_items[0]
    uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads_playlist:
        raise RuntimeError("Authenticated channel does not expose an uploads playlist.")

    playlist_rows: dict[str, dict[str, Any]] = {}
    page_token = None
    while True:
        params: dict[str, Any] = {
            "part": "contentDetails,snippet,status",
            "playlistId": uploads_playlist,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        response = youtube.playlistItems().list(**params).execute()
        for item in response.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            playlist_rows[video_id] = item
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    metadata_rows: dict[str, dict[str, Any]] = {}
    metadata_errors: list[dict[str, Any]] = []
    ordered_ids = list(playlist_rows.keys())
    for chunk in _chunked(ordered_ids, 50):
        try:
            response = youtube.videos().list(
                part="snippet,contentDetails,statistics,status",
                id=",".join(chunk),
                maxResults=len(chunk),
            ).execute()
            for item in response.get("items", []):
                video_id = item.get("id")
                if video_id:
                    metadata_rows[video_id] = item
        except Exception as exc:
            metadata_errors.append({"videoIds": chunk, "error": f"{type(exc).__name__}: {exc}"})
            for video_id in chunk:
                try:
                    response = youtube.videos().list(
                        part="snippet,contentDetails,statistics,status",
                        id=video_id,
                        maxResults=1,
                    ).execute()
                    for item in response.get("items", []):
                        found_id = item.get("id")
                        if found_id:
                            metadata_rows[found_id] = item
                except Exception as item_exc:
                    metadata_errors.append({"videoIds": [video_id], "error": f"{type(item_exc).__name__}: {item_exc}"})

    inventory_rows: list[dict[str, Any]] = []
    for video_id, playlist_item in playlist_rows.items():
        metadata_item = metadata_rows.get(video_id, {})
        playlist_snippet = playlist_item.get("snippet", {})
        playlist_content = playlist_item.get("contentDetails", {})
        playlist_status = playlist_item.get("status", {})
        snippet = metadata_item.get("snippet", {}) or playlist_snippet
        content_details = metadata_item.get("contentDetails", {}) or playlist_content
        status = metadata_item.get("status", {}) or playlist_status
        statistics = metadata_item.get("statistics", {})
        inventory_rows.append(
            {
                "videoId": video_id,
                "videoUrl": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title", "") or playlist_snippet.get("title", ""),
                "description": snippet.get("description", "") or playlist_snippet.get("description", ""),
                "publishedAt": snippet.get("publishedAt", "") or playlist_snippet.get("publishedAt", ""),
                "privacyStatus": status.get("privacyStatus", "unknown") if metadata_item else "unknown",
                "uploadStatus": status.get("uploadStatus", ""),
                "embeddable": status.get("embeddable", None),
                "license": status.get("license", ""),
                "duration": content_details.get("duration", ""),
                "durationSeconds": parse_iso8601_duration(content_details.get("duration", "PT0S")),
                "viewCount": _safe_int(statistics.get("viewCount")),
                "likeCount": _safe_int(statistics.get("likeCount")),
                "commentCount": _safe_int(statistics.get("commentCount")),
                "liveBroadcastContent": snippet.get("liveBroadcastContent", ""),
                "madeForKids": status.get("madeForKids", None),
                "selfDeclaredMadeForKids": status.get("selfDeclaredMadeForKids", None),
                "tags": snippet.get("tags", []),
                "categoryId": snippet.get("categoryId", ""),
                "thumbnails": snippet.get("thumbnails", {}),
                "playlistItemAvailable": True,
                "apiMetadataAvailable": bool(metadata_item),
                "apiError": "",
                "apiErrorRecovered": False,
            }
        )

    metadata_only_count = len([row for row in inventory_rows if row["apiMetadataAvailable"] and row["viewCount"] == 0 and row["commentCount"] == 0 and row["likeCount"] == 0 and row["durationSeconds"] >= 0])
    return {
        "channel": channel,
        "uploadsPlaylist": uploads_playlist,
        "inventoryRows": inventory_rows,
        "metadataRows": metadata_rows,
        "playlistRows": playlist_rows,
        "metadataErrors": metadata_errors,
        "apiInventoryTotal": len(inventory_rows),
        "apiMetadataAvailableCount": len(metadata_rows),
        "metadataOnlyCount": metadata_only_count,
    }


def _build_source_indices(
    diagnosis_payload: dict[str, Any],
    opportunities_payload: dict[str, Any] | None,
    candidates_payload: dict[str, Any] | None,
    proposals_payload: dict[str, Any] | None,
    v1_payload: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    diagnosis_rows = enrich_video_rows(diagnosis_payload)
    diagnosis_by_id = {row["video"]: row for row in diagnosis_rows}
    v1_by_id = {row["video"]: row for row in v1_payload.get("records", [])}

    opportunity_titles = {item.get("title", "") for item in (opportunities_payload or {}).get("actions", []) if item.get("title")}
    candidate_by_id = {item.get("videoId", ""): item for item in (candidates_payload or {}).get("candidates", []) if item.get("videoId")}
    candidate_by_title = {item.get("title", ""): item for item in (candidates_payload or {}).get("candidates", []) if item.get("title")}
    proposal_by_id: dict[str, dict[str, Any]] = {}
    proposal_by_title: dict[str, dict[str, Any]] = {}
    for item in (proposals_payload or {}).get("analyses", []):
        candidate = item.get("candidate", {})
        video_id = candidate.get("video") or candidate.get("videoId")
        title = candidate.get("title")
        if video_id:
            proposal_by_id[str(video_id)] = item
        if title:
            proposal_by_title[str(title)] = item

    return {
        "diagnosisById": diagnosis_by_id,
        "v1ById": v1_by_id,
        "opportunityTitles": {title for title in opportunity_titles if title},
        "candidateById": candidate_by_id,
        "candidateByTitle": candidate_by_title,
        "proposalById": proposal_by_id,
        "proposalByTitle": proposal_by_title,
    }


def _source_presence(row: dict[str, Any]) -> list[str]:
    presence = []
    if row.get("api_metadata_available"):
        presence.append("api_metadata_available")
    if row.get("analytics_available"):
        presence.append("analytics_available")
    if row.get("diagnosis_available"):
        presence.append("diagnosis_available")
    if row.get("archive_miner_v1_available"):
        presence.append("archive_miner_v1_available")
    if row.get("api_metadata_available") and not row.get("analytics_available"):
        presence.append("metadata_only")
    if row.get("analytics_available") and not row.get("api_metadata_available"):
        presence.append("analytics_only")
    if row.get("diagnosis_available") and not row.get("api_metadata_available"):
        presence.append("diagnosis_only")
    if row.get("api_metadata_available") and not row.get("archive_miner_v1_available"):
        presence.append("missing_from_current_archive_miner")
    if not row.get("api_metadata_available") and (
        row.get("analytics_available") or row.get("diagnosis_available") or row.get("archive_miner_v1_available")
    ):
        presence.append("unavailable_or_deleted_candidate")
    if row.get("apiMetadataMissing"):
        presence.append("metadata_missing")
    return presence


def _reconciliation_status(row: dict[str, Any]) -> str:
    if row.get("apiMetadataMissing"):
        return "metadata_missing"
    if row.get("api_metadata_available") and row.get("analytics_available") and row.get("diagnosis_available"):
        return "api_metadata_available"
    if row.get("api_metadata_available") and not row.get("analytics_available"):
        return "metadata_only"
    if row.get("analytics_available") and not row.get("api_metadata_available"):
        return "analytics_only"
    if row.get("diagnosis_available") and not row.get("api_metadata_available") and not row.get("analytics_available"):
        return "diagnosis_only"
    if row.get("api_metadata_available") and not row.get("archive_miner_v1_available"):
        return "missing_from_current_archive_miner"
    if not row.get("api_metadata_available") and (
        row.get("analytics_available") or row.get("diagnosis_available") or row.get("archive_miner_v1_available")
    ):
        return "unavailable_or_deleted_candidate"
    return "studio_gap_unknown"


def _reconcile_row(
    video_id: str,
    api_index: dict[str, dict[str, Any]],
    indices: dict[str, dict[str, dict[str, Any]]],
    analytics_rows30: dict[str, dict[str, Any]],
    analytics_rows90: dict[str, dict[str, Any]],
    analysis_date: dt.date,
) -> dict[str, Any]:
    api_row = api_index.get(video_id, {})
    diagnosis_row = indices["diagnosisById"].get(video_id, {})
    v1_row = indices["v1ById"].get(video_id, {})
    candidate_row = indices["candidateById"].get(video_id, {}) or indices["candidateByTitle"].get(api_row.get("title", ""), {})
    proposal_row = indices["proposalById"].get(video_id, {}) or indices["proposalByTitle"].get(api_row.get("title", ""), {})
    opportunity_hit = api_row.get("title", "") in indices["opportunityTitles"] or diagnosis_row.get("title", "") in indices["opportunityTitles"]

    merged = _merge_video_sources(
        {video_id: diagnosis_row} if diagnosis_row else {},
        {video_id: v1_row} if v1_row else {},
        {video_id: api_row} if api_row else {},
    ).get(video_id, {})

    title = merged.get("title") or api_row.get("title") or diagnosis_row.get("title") or v1_row.get("title") or ""
    description = merged.get("description") or api_row.get("description") or diagnosis_row.get("description") or v1_row.get("description") or ""
    published_at = merged.get("publishedAt") or api_row.get("publishedAt") or diagnosis_row.get("publishedAt") or v1_row.get("publishedAt") or ""
    privacy_status = api_row.get("privacyStatus") or merged.get("privacyStatus") or "unknown"
    duration_seconds = _safe_int(api_row.get("durationSeconds") or merged.get("durationSeconds") or diagnosis_row.get("durationSeconds") or v1_row.get("durationSeconds") or 0)
    topic_family = merged.get("topicFamily") or infer_topic_family(f"{title} {description}")
    content_type = merged.get("contentType") or diagnosis_row.get("contentType") or v1_row.get("contentType") or ("short" if duration_seconds <= 60 else "standard")
    content_type_reason = merged.get("contentTypeReason") or diagnosis_row.get("contentTypeReason") or v1_row.get("contentTypeReason") or ""

    analytics30 = analytics_rows30.get(video_id, {})
    analytics90 = analytics_rows90.get(video_id, {})
    analytics_available = bool(analytics30 or analytics90 or v1_row)

    api_metadata_available = bool(api_row.get("apiMetadataAvailable"))
    api_metadata_missing = bool(api_row and not api_metadata_available)
    diagnosis_available = bool(diagnosis_row)
    archive_miner_v1_available = bool(v1_row)

    if api_row.get("apiMetadataAvailable"):
        api_source = "api_metadata_available"
    elif api_row:
        api_source = "metadata_missing"
    else:
        api_source = "not_recovered_by_api"

    if has_crypto_legacy_signals(f"{title} {description}") and not has_explicit_ai_hardware_signals(f"{title} {description}"):
        topic_family = "crypto_legacy"
        if content_type == "hardware":
            content_type = "otro"
            content_type_reason = "Contenido crypto/minería heredado; no debe clasificarse como hardware IA por defecto."

    row = {
        "videoId": video_id,
        "videoUrl": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "description": description,
        "publishedAt": published_at,
        "durationSeconds": duration_seconds,
        "privacyStatus": privacy_status,
        "uploadStatus": api_row.get("uploadStatus", ""),
        "embeddable": api_row.get("embeddable", None),
        "license": api_row.get("license", ""),
        "viewCount": _safe_int(api_row.get("viewCount")),
        "likeCount": _safe_int(api_row.get("likeCount")),
        "commentCount": _safe_int(api_row.get("commentCount")),
        "liveBroadcastContent": api_row.get("liveBroadcastContent", ""),
        "madeForKids": api_row.get("madeForKids", None),
        "selfDeclaredMadeForKids": api_row.get("selfDeclaredMadeForKids", None),
        "tags": api_row.get("tags", []),
        "categoryId": api_row.get("categoryId", merged.get("categoryId", "")),
        "thumbnails": api_row.get("thumbnails", merged.get("thumbnails", {})),
        "apiMetadataAvailable": api_metadata_available,
        "apiMetadataMissing": api_metadata_missing,
        "analyticsAvailable": analytics_available,
        "diagnosisAvailable": diagnosis_available,
        "archiveMinerV1Available": archive_miner_v1_available,
        "metadataOnly": bool(api_metadata_available and not analytics_available),
        "analyticsOnly": bool(analytics_available and not api_metadata_available),
        "diagnosisOnly": bool(diagnosis_available and not api_metadata_available),
        "missingFromCurrentArchiveMiner": bool(api_metadata_available and not archive_miner_v1_available),
        "notRecoveredByApi": bool(not api_metadata_available and (diagnosis_available or analytics_available or archive_miner_v1_available)),
        "topicFamily": topic_family,
        "contentType": content_type,
        "contentTypeReason": content_type_reason,
        "alignedWithNewDirection": bool(merged.get("alignedWithNewDirection", False)),
        "reconciliationSource": api_source,
        "opportunityAvailable": opportunity_hit,
        "candidateAvailable": bool(candidate_row),
        "proposalAvailable": bool(proposal_row),
        "views30": _safe_int(analytics30.get("views", diagnosis_row.get("views30", v1_row.get("views30", 0)))),
        "watch30": _safe_float(analytics30.get("estimatedMinutesWatched", diagnosis_row.get("watch30", v1_row.get("watch30", 0)))),
        "retention30": _safe_float(analytics30.get("averageViewPercentage", diagnosis_row.get("retention30", v1_row.get("retention30", 0)))),
        "views90": _safe_int(analytics90.get("views", diagnosis_row.get("views90", v1_row.get("views90", 0)))),
        "watch90": _safe_float(analytics90.get("estimatedMinutesWatched", diagnosis_row.get("watch90", v1_row.get("watch90", 0)))),
        "retention90": _safe_float(analytics90.get("averageViewPercentage", diagnosis_row.get("retention90", v1_row.get("retention90", 0)))),
        "likes30": _safe_int(analytics30.get("likes", diagnosis_row.get("likes30", v1_row.get("likes30", 0)))),
        "comments30": _safe_int(analytics30.get("comments", diagnosis_row.get("comments30", v1_row.get("comments30", 0)))),
        "subs30": _safe_int(analytics30.get("subscribersGained", diagnosis_row.get("subs30", v1_row.get("subs30", 0)))),
        "likes90": _safe_int(analytics90.get("likes", diagnosis_row.get("likes90", v1_row.get("likes90", 0)))),
        "comments90": _safe_int(analytics90.get("comments", diagnosis_row.get("comments90", v1_row.get("comments90", 0)))),
        "subs90": _safe_int(analytics90.get("subscribersGained", diagnosis_row.get("subs90", v1_row.get("subs90", 0)))),
        "viewsPerDay30": 0.0,
        "viewsPerDay90": 0.0,
        "tagMatches": merged.get("tagMatches", []),
        "sourceSignals": [],
    }
    row.update(
        {
            "api_metadata_available": api_metadata_available,
            "api_metadata_missing": api_metadata_missing,
            "analytics_available": analytics_available,
            "diagnosis_available": diagnosis_available,
            "archive_miner_v1_available": archive_miner_v1_available,
            "metadata_only": bool(api_metadata_available and not analytics_available),
            "analytics_only": bool(analytics_available and not api_metadata_available),
            "diagnosis_only": bool(diagnosis_available and not api_metadata_available),
            "missing_from_current_archive_miner": bool(api_metadata_available and not archive_miner_v1_available),
            "not_recovered_by_api": bool(not api_metadata_available and (diagnosis_available or analytics_available or archive_miner_v1_available)),
        }
    )
    try:
        published_date = dt.date.fromisoformat(str((published_at or "1970-01-01")[:10]))
        days_since = max((analysis_date - published_date).days, 1)
    except Exception:
        days_since = 1
    row["viewsPerDay30"] = float(row["views30"]) / max(days_since, 1)
    row["viewsPerDay90"] = float(row["views90"]) / max(days_since, 1)
    row["sourceSignals"] = _source_presence(row)
    row["reconciliationStatus"] = _reconciliation_status(row)
    row["reconciliationCategories"] = row["sourceSignals"]
    return row


def _build_inventory_master(
    api_inventory: dict[str, Any],
    diagnosis_payload: dict[str, Any],
    opportunities_payload: dict[str, Any] | None,
    candidates_payload: dict[str, Any] | None,
    proposals_payload: dict[str, Any] | None,
    v1_payload: dict[str, Any],
    analytics_rows30: dict[str, dict[str, Any]],
    analytics_rows90: dict[str, dict[str, Any]],
    analysis_date: dt.date,
) -> list[dict[str, Any]]:
    indices = _build_source_indices(diagnosis_payload, opportunities_payload, candidates_payload, proposals_payload, v1_payload)

    api_rows = {row["videoId"]: row for row in api_inventory["inventoryRows"]}
    all_ids: set[str] = set(api_rows) | set(indices["diagnosisById"]) | set(indices["v1ById"]) | set(indices["candidateById"]) | set(indices["proposalById"])

    master_rows = [
        _reconcile_row(video_id, api_rows, indices, analytics_rows30, analytics_rows90, analysis_date)
        for video_id in sorted(all_ids)
    ]
    master_rows.sort(key=lambda row: (-row["apiMetadataAvailable"], -row["analyticsAvailable"], -row["diagnosisAvailable"], row["title"].lower()))
    return master_rows


def _reconciliation_summary(
    master_rows: list[dict[str, Any]],
    api_inventory: dict[str, Any],
    v1_payload: dict[str, Any],
    studio_total_manual: int | None,
) -> dict[str, Any]:
    counts_by_privacy = Counter(row["privacyStatus"] if row["privacyStatus"] in {"public", "unlisted", "private"} else "unknown" for row in master_rows if row["apiMetadataAvailable"] or row["apiMetadataMissing"])
    api_rows = [row for row in master_rows if row["apiMetadataAvailable"]]
    analytics_available_count = len([row for row in master_rows if row["analyticsAvailable"]])
    diagnosis_available_count = len([row for row in master_rows if row["diagnosisAvailable"]])
    metadata_only_count = len([row for row in master_rows if row["metadataOnly"]])
    analytics_only_count = len([row for row in master_rows if row["analyticsOnly"]])
    unavailable_or_deleted_count = len([row for row in master_rows if row["notRecoveredByApi"]])
    missing_from_v1_count = len([row for row in master_rows if row["missingFromCurrentArchiveMiner"]])
    diagnosis_only_count = len([row for row in master_rows if row["diagnosisOnly"] and not row["apiMetadataAvailable"]])
    api_total = len(api_inventory["inventoryRows"])
    archive_v1_total = len(v1_payload.get("records", []))
    studio_gap_count = studio_total_manual - api_total if studio_total_manual is not None else None
    studio_gap_unknown = max(studio_gap_count, 0) if studio_gap_count is not None else None

    return {
        "studioTotalManual": studio_total_manual,
        "apiInventoryTotal": api_total,
        "apiMetadataAvailableCount": len(api_inventory["metadataRows"]),
        "archiveMinerV1Total": archive_v1_total,
        "analyticsAvailableCount": analytics_available_count,
        "diagnosisAvailableCount": diagnosis_available_count,
        "publicCount": counts_by_privacy.get("public", 0),
        "unlistedCount": counts_by_privacy.get("unlisted", 0),
        "privateCount": counts_by_privacy.get("private", 0),
        "unknownPrivacyCount": counts_by_privacy.get("unknown", 0),
        "analyticsOnlyCount": analytics_only_count,
        "metadataOnlyCount": metadata_only_count,
        "missingFromCurrentArchiveMinerCount": missing_from_v1_count,
        "diagnosisOnlyCount": diagnosis_only_count,
        "unavailableOrDeletedCandidateCount": unavailable_or_deleted_count,
        "studioGapCount": studio_gap_count,
        "studioGapUnknownCount": studio_gap_unknown,
        "countsByReconciliationStatus": dict(Counter(row["reconciliationStatus"] for row in master_rows)),
        "countsByTopicFamily": dict(Counter(row["topicFamily"] for row in master_rows)),
    }


def _reconciliation_line(record: dict[str, Any]) -> str:
    categories = ", ".join(record.get("reconciliationCategories", []))
    return (
        f"- **{record['title'] or record['videoId']}** | URL `{record['videoUrl']}` | fecha `{record.get('publishedAt', '')[:10]}` | privacidad `{record['privacyStatus']}`"
        f" | estado `{record['reconciliationStatus']}` | categorías `{categories}` | tipo `{record['contentType']}` | topicFamily `{record['topicFamily']}`"
        f" | views30 {record['views30']} | watch30 {record['watch30']:.0f} | views90 {record['views90']} | watch90 {record['watch90']:.0f}"
    )


def _filter_reconciliation(records: list[dict[str, Any]], predicate, limit: int = 10) -> list[dict[str, Any]]:
    subset = [record for record in records if predicate(record)]
    subset.sort(key=lambda row: (row["reconciliationStatus"], -row["views90"], row["title"].lower()))
    return subset[:limit]


def build_reconciliation_report(result: dict[str, Any]) -> str:
    records = result["records"]
    summary = result["reconciliationSummary"]
    v1_summary = result["archiveMinerV1Summary"]
    lines = [
        f"# Content Archive Miner - {result['reportDate']}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Total manual de Studio: {summary['studioTotalManual'] if summary['studioTotalManual'] is not None else 'no facilitado'}",
        f"- Total recuperado por YouTube Data API: {summary['apiInventoryTotal']}",
        f"- Total analizado por content_archive_miner v1: {summary['archiveMinerV1Total']}",
        f"- Diferencia contra Studio: {summary['studioGapCount'] if summary['studioGapCount'] is not None else 'no calculada'}",
        f"- Reconciliación previa v1: {v1_summary['totalVideos']} vídeos, {v1_summary['recommendationCounts'].get('keep_public', 0)} keep_public, {v1_summary['recommendationCounts'].get('consider_private', 0)} consider_private.",
        "",
        "## 2. Auditoría v1.",
        "",
        f"- La v1 siguió aportando la capa editorial para {v1_summary['totalVideos']} vídeos ya analizados.",
        f"- Su reparto principal fue: {', '.join(f'{key} {value}' for key, value in sorted(v1_summary['recommendationCounts'].items(), key=lambda item: (-item[1], item[0])))}.",
        f"- Sus tipos dominantes fueron: {', '.join(f'{key} {value}' for key, value in sorted(v1_summary['typeCounts'].items(), key=lambda item: (-item[1], item[0])))}.",
        "",
        "## 3. Reconciliación de inventario.",
        "",
        f"- Vídeos con metadata API disponible: {summary['apiMetadataAvailableCount']}",
        f"- Vídeos con Analytics disponibles: {summary['analyticsAvailableCount']}",
        f"- Vídeos con diagnosis disponible: {summary['diagnosisAvailableCount']}",
        f"- Vídeos presentes en v1: {summary['archiveMinerV1Total']}",
        f"- Vídeos recuperados por API pero no analizados por v1: {summary['missingFromCurrentArchiveMinerCount']}",
        f"- Vídeos con metadata pero sin métricas recientes: {summary['metadataOnlyCount']}",
        f"- Vídeos con métricas pero sin metadata actual: {summary['analyticsOnlyCount']}",
        f"- Posibles elementos eliminados o no recuperables: {summary['unavailableOrDeletedCandidateCount']}",
        "",
        "## 4. Total manual de Studio.",
        "",
        f"- {summary['studioTotalManual'] if summary['studioTotalManual'] is not None else 'No se pasó total manual.'}",
        "",
        "## 5. Total recuperado por YouTube Data API.",
        "",
        f"- {summary['apiInventoryTotal']}",
        "",
        "## 6. Total analizado por content_archive_miner.",
        "",
        f"- {summary['archiveMinerV1Total']}",
        "",
        "## 7. Distribución por privacidad.",
        "",
        f"- public: {summary['publicCount']}",
        f"- unlisted: {summary['unlistedCount']}",
        f"- private: {summary['privateCount']}",
        f"- unknown: {summary['unknownPrivacyCount']}",
        "",
        "## 8. Vídeos recuperados por API pero no analizados por v1.",
        "",
    ]
    missing_from_v1 = _filter_reconciliation(records, lambda row: row["missingFromCurrentArchiveMiner"])
    if missing_from_v1:
        lines.extend(_reconciliation_line(row) for row in missing_from_v1)
    else:
        lines.append("- No se detectaron vídeos recuperados por API fuera de v1.")
    lines.extend([
        "",
        "## 9. Vídeos con metadata pero sin métricas.",
        "",
    ])
    metadata_only = _filter_reconciliation(records, lambda row: row["metadataOnly"])
    if metadata_only:
        lines.extend(_reconciliation_line(row) for row in metadata_only)
    else:
        lines.append("- No se detectaron piezas con metadata pero sin métricas recientes.")
    lines.extend([
        "",
        "## 10. Vídeos con métricas pero sin metadata.",
        "",
    ])
    analytics_only = _filter_reconciliation(records, lambda row: row["analyticsOnly"])
    if analytics_only:
        lines.extend(_reconciliation_line(row) for row in analytics_only)
    else:
        lines.append("- No se detectaron piezas con métricas pero sin metadata actual.")
    lines.extend([
        "",
        "## 11. Posibles elementos eliminados o no recuperables.",
        "",
    ])
    unavailable = _filter_reconciliation(records, lambda row: row["notRecoveredByApi"])
    if unavailable:
        lines.extend(_reconciliation_line(row) for row in unavailable)
    else:
        lines.append("- No se detectaron candidatos claros a no recuperables.")
    lines.extend([
        "",
        "## 12. Diferencia contra Studio.",
        "",
    ])
    if summary["studioGapCount"] is None:
        lines.append("- No se calculó porque no se pasó `--studio-total`.")
    else:
        lines.append(f"- Studio gap calculado: {summary['studioGapCount']}")
    lines.extend([
        "",
        "## 13. Advertencia sobre no asumir eliminados.",
        "",
        "- Studio gap does not mean deleted videos automatically. It means items shown/countable in Studio that were not recovered by this API inventory pass.",
        "- Usar siempre etiquetas prudentes: `unavailable_or_deleted_candidate`, `not_recovered_by_api`, `analytics_only_legacy_item`, `metadata_missing`, `unknown_gap`.",
        "",
        "## 14. Corrección de clasificación crypto/minería.",
        "",
        "- Las piezas con señales de crypto, minería, Zcash, Bitcoin, Ethereum, ASIC, trading, exchange, wallet o blockchain ahora se asignan a `topicFamily: crypto_legacy`.",
        "- En esos casos `alignedWithNewDirection` queda en `false` salvo que el vídeo sea explícitamente sobre hardware para IA actual.",
        "- Se evita confundir GPUs para minería con GPUs para IA local.",
        "",
        "## 15. Nuevo resumen por recomendación.",
        "",
    ])
    for key, value in sorted(v1_summary["recommendationCounts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{key}`: {value}")
    lines.extend([
        "",
        "## 16. Nuevo resumen por tipo.",
        "",
    ])
    for key, value in sorted(v1_summary["typeCounts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{key}`: {value}")
    lines.extend([
        "",
        "## 17. Limitaciones reales.",
        "",
        "- No se asume eliminación real sin confirmación explícita de la API.",
        "- La reconciliación depende del alcance de la cuenta autenticada y de lo que YouTube devuelva en playlists y metadata.",
        "- Algunos vídeos antiguos pueden aparecer solo por métricas o solo por metadata, sin poder cruzarse al 100%.",
        "- La diferencia contra Studio puede incluir elementos que Studio cuenta de forma distinta a la API.",
        "- No se usó Google Custom Search.",
        "",
        "## 18. Siguiente paso recomendado.",
        "",
        "- Revisar primero `consider_private` y `consider_unlisted` con valor histórico o riesgo alto.",
        "- Usar los vídeos `missing_from_current_archive_miner` como cola de investigación para comprobar qué piezas faltan en la auditoría v1.",
        "- Tratar el `studioGapCount` como una pista de inventario, nunca como una prueba automática de borrado.",
    ])
    return "\n".join(lines) + "\n"


def export_reconciliation_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "videoId": record["videoId"],
                "videoUrl": record["videoUrl"],
                "title": record["title"],
                "publishedAt": record["publishedAt"],
                "privacyStatus": record["privacyStatus"],
                "apiMetadataAvailable": record["apiMetadataAvailable"],
                "apiMetadataMissing": record["apiMetadataMissing"],
                "analyticsAvailable": record["analyticsAvailable"],
                "diagnosisAvailable": record["diagnosisAvailable"],
                "archiveMinerV1Available": record["archiveMinerV1Available"],
                "reconciliationStatus": record["reconciliationStatus"],
                "reconciliationCategories": " | ".join(record["reconciliationCategories"]),
                "topicFamily": record["topicFamily"],
                "contentType": record["contentType"],
                "contentTypeReason": record["contentTypeReason"],
                "durationSeconds": record["durationSeconds"],
                "viewCount": record["viewCount"],
                "likeCount": record["likeCount"],
                "commentCount": record["commentCount"],
                "views30": record["views30"],
                "watch30": record["watch30"],
                "retention30": record["retention30"],
                "views90": record["views90"],
                "watch90": record["watch90"],
                "retention90": record["retention90"],
                "missingFromCurrentArchiveMiner": record["missingFromCurrentArchiveMiner"],
                "metadataOnly": record["metadataOnly"],
                "analyticsOnly": record["analyticsOnly"],
                "diagnosisOnly": record["diagnosisOnly"],
                "notRecoveredByApi": record["notRecoveredByApi"],
                "opportunityAvailable": record["opportunityAvailable"],
                "candidateAvailable": record["candidateAvailable"],
                "proposalAvailable": record["proposalAvailable"],
                "alignedWithNewDirection": record["alignedWithNewDirection"],
                "apiMetadataMissingReason": "metadata not recovered by videos.list" if record["apiMetadataMissing"] else "",
            }
        )
    return rows


def _build_api_inventory_indexes(api_inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["videoId"]: row for row in api_inventory["inventoryRows"]}


def run_archive_inventory_reconciliation(
    report_date: dt.date | None = None,
    studio_total_manual: int | None = None,
) -> dict[str, Path]:
    ensure_output_dirs()
    diagnosis_payload, diagnosis_paths = load_diagnosis_payload(report_date)
    resolved_date = report_date or dt.date.fromisoformat(diagnosis_payload["dataset"]["periods"]["30d"]["end"]) + dt.timedelta(days=1)

    opportunities_payload, opportunities_path = load_latest_json_payload(OPPORTUNITIES_DATA_DIR, "channel_opportunities", report_date or resolved_date)
    candidates_payload, candidates_path = load_latest_json_payload(REWRITE_CANDIDATES_DATA_DIR, "video_rewrite_candidates", report_date or resolved_date)
    proposals_payload, proposals_path = load_latest_json_payload(REWRITE_PROPOSALS_DATA_DIR, "video_rewrite_proposals", report_date or resolved_date)
    tag_payload, tag_path = load_latest_json_payload(TAG_INTELLIGENCE_DATA_DIR, "youtube_tag_intelligence", report_date or resolved_date)
    v1_payload, v1_path = load_latest_json_payload(ARCHIVE_DATA_DIR, "content_archive_miner", report_date or resolved_date)
    if not v1_payload or not v1_path:
        raise FileNotFoundError("No content_archive_miner v1 data available to reconcile against.")

    try:
        api_inventory = fetch_api_inventory()
        api_inventory_error = ""
    except Exception as exc:
        api_inventory = {
            "channel": {},
            "uploadsPlaylist": "",
            "inventoryRows": [],
            "metadataRows": {},
            "playlistRows": {},
            "metadataErrors": [{"videoIds": [], "error": f"{type(exc).__name__}: {exc}"}],
            "apiInventoryTotal": 0,
            "apiMetadataAvailableCount": 0,
        }
        api_inventory_error = f"{type(exc).__name__}: {exc}"
    analytics = load_live_analytics(diagnosis_payload)
    master_rows = _build_inventory_master(
        api_inventory,
        diagnosis_payload,
        opportunities_payload,
        candidates_payload,
        proposals_payload,
        v1_payload,
        analytics["rows30"] if analytics["available"] else {},
        analytics["rows90"] if analytics["available"] else {},
        resolved_date,
    )

    api_index = _build_api_inventory_indexes(api_inventory)
    for row in master_rows:
        if row["videoId"] in api_index and api_index[row["videoId"]].get("title"):
            row["title"] = api_index[row["videoId"]]["title"]

    reconciliation_summary = _reconciliation_summary(master_rows, api_inventory, v1_payload, studio_total_manual)
    v1_summary = v1_payload.get("summary", {})

    result = {
        "reportDate": resolved_date.isoformat(),
        "mode": "reconcile_inventory",
        "sourcePaths": {
            "channelDiagnosisJson": str(diagnosis_paths["json"]),
            "channelDiagnosisReport": str(diagnosis_paths["report"]),
            "channelOpportunitiesJson": str(opportunities_path) if opportunities_path else None,
            "videoRewriteCandidatesJson": str(candidates_path) if candidates_path else None,
            "videoRewriteProposalsJson": str(proposals_path) if proposals_path else None,
            "youtubeTagIntelligenceJson": str(tag_path) if tag_path else None,
            "archiveMinerV1Json": str(v1_path),
        },
        "sourceAvailability": {
            "channelDiagnosis": source_status(True, "used", details={"videos": len(enrich_video_rows(diagnosis_payload))}, blocking=False),
            "youtubeDataOwn": source_status(bool(api_inventory["inventoryRows"]), "used" if api_inventory["inventoryRows"] else "skipped", reason=api_inventory_error, details={"videos": len(api_inventory["inventoryRows"])} if api_inventory["inventoryRows"] else {}, blocking=False),
            "youtubeAnalyticsOwn": source_status(analytics["available"], "used" if analytics["available"] else "skipped", reason="" if analytics["available"] else analytics["reason"], details={"rows30": len(analytics["rows30"]), "rows90": len(analytics["rows90"])} if analytics["available"] else {}, blocking=False),
            "channelOpportunities": source_status(bool(opportunities_payload), "used" if opportunities_payload else "skipped", details={"path": str(opportunities_path) if opportunities_path else ""}, blocking=False),
            "videoRewriteCandidates": source_status(bool(candidates_payload), "used" if candidates_payload else "skipped", details={"path": str(candidates_path) if candidates_path else ""}, blocking=False),
            "videoRewriteProposals": source_status(bool(proposals_payload), "used" if proposals_payload else "skipped", details={"path": str(proposals_path) if proposals_path else ""}, blocking=False),
            "youtubeTagIntelligence": source_status(bool(tag_payload), "used" if tag_payload else "skipped", details={"path": str(tag_path) if tag_path else ""}, blocking=False),
            "archiveMinerV1": source_status(True, "used", details={"videos": v1_summary.get("totalVideos", len(v1_payload.get("records", [])))}, blocking=False),
        },
        "summary": {
            "totalVideos": len(master_rows),
            "recommendationCounts": dict(Counter(row["reconciliationStatus"] for row in master_rows)),
            "typeCounts": dict(Counter(row["contentType"] for row in master_rows)),
            "privacyCounts": dict(Counter(row["privacyStatus"] if row["privacyStatus"] in {"public", "unlisted", "private"} else "unknown" for row in master_rows)),
        },
        "reconciliationSummary": reconciliation_summary,
        "archiveMinerV1Summary": v1_summary,
        "apiInventory": api_inventory,
        "records": master_rows,
    }

    stamp = resolved_date.isoformat()
    json_path = ARCHIVE_DATA_DIR / f"inventory_reconciliation_{stamp}.json"
    csv_path = ARCHIVE_DATA_DIR / f"inventory_reconciliation_{stamp}.csv"
    api_csv_path = ARCHIVE_DATA_DIR / f"api_inventory_{stamp}.csv"
    metadata_only_csv_path = ARCHIVE_DATA_DIR / f"metadata_only_{stamp}.csv"
    analytics_only_csv_path = ARCHIVE_DATA_DIR / f"analytics_only_{stamp}.csv"
    missing_from_v1_csv_path = ARCHIVE_DATA_DIR / f"missing_from_archive_miner_{stamp}.csv"
    unavailable_csv_path = ARCHIVE_DATA_DIR / f"unavailable_or_deleted_candidates_{stamp}.csv"
    gap_summary_path = ARCHIVE_DATA_DIR / f"studio_gap_summary_{stamp}.json"
    report_path = REPORTS_DIR / f"content_archive_miner_{stamp}.md"

    save_json(json_path, result)
    save_csv(csv_path, export_reconciliation_rows(master_rows))
    save_csv(api_csv_path, export_reconciliation_rows([row for row in master_rows if row["apiMetadataAvailable"]]))
    save_csv(metadata_only_csv_path, export_reconciliation_rows([row for row in master_rows if row["metadataOnly"]]))
    save_csv(analytics_only_csv_path, export_reconciliation_rows([row for row in master_rows if row["analyticsOnly"]]))
    save_csv(missing_from_v1_csv_path, export_reconciliation_rows([row for row in master_rows if row["missingFromCurrentArchiveMiner"]]))
    save_csv(unavailable_csv_path, export_reconciliation_rows([row for row in master_rows if row["notRecoveredByApi"]]))
    save_json(gap_summary_path, reconciliation_summary)
    report_path.write_text(build_reconciliation_report(result), encoding="utf-8")

    return {
        "report": report_path,
        "json": json_path,
        "csv": csv_path,
        "api_csv": api_csv_path,
        "metadata_only_csv": metadata_only_csv_path,
        "analytics_only_csv": analytics_only_csv_path,
        "missing_from_v1_csv": missing_from_v1_csv_path,
        "unavailable_csv": unavailable_csv_path,
        "gap_summary_json": gap_summary_path,
    }
